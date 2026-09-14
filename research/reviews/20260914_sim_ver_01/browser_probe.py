"""SIM-VER-01 browser evidence; separate fixture and live modes, no provider calls."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / '.artifacts/sim-ver-01'
mode = sys.argv[1]
assert mode in {'fixture', 'public'}
snapshot = json.loads((OUT / (mode + '-snapshot.json')).read_text(encoding='utf-8'))
base = 'http://127.0.0.1:18766' if mode == 'fixture' else (
    'http://' + dotenv_values(ROOT / '.env')['DEPLOY_SSH_HOST'] + ':18081')
games = {g['id']: g for g in snapshot['games']}
report = {'mode': mode, 'checked_at': datetime.now(timezone.utc).isoformat(),
          'checks': [], 'screenshots': []}

def check(label, actual, expected=True):
    report['checks'].append({'check': label, 'actual': actual,
                            'expected': expected, 'pass': actual == expected})

def oracle(pk):
    def labels(game):
        return {' '.join(g.split()).casefold() for g in game['genres'] if g.strip()}
    query = labels(games[pk])
    candidates = []
    for peer_id, game in games.items():
        other = labels(game)
        if peer_id != pk and query.intersection(other):
            candidates.append((-len(query & other) / len(query | other),
                               game['title'].casefold(), peer_id))
    return [x[2] for x in sorted(candidates)[:5]]

def links(page):
    return page.locator('.similar-games a').evaluate_all(
        'els => els.map(e => ({title: e.textContent, path: e.getAttribute("href")}))')

def ids(rows):
    return [int(urlsplit(row['path']).path.strip('/').split('/')[-1]) for row in rows]

def fit(page, label):
    check(label + ' no horizontal overflow',
          page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))

def capture(page, label):
    filename = 'sim-ver-01-' + mode + '-' + label + '.png'
    page.screenshot(path=str(ROOT / 'docs/evidence' / filename), full_page=True)
    report['screenshots'].append(filename)

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    report['browser'] = browser.version
    page = browser.new_page(viewport={'width': 1280, 'height': 1050})
    errors = []
    page.on('pageerror', lambda error: errors.append(type(error).__name__))
    health = page.request.get(base + '/health/ready/')
    check('readiness', health.status, 200)
    report['build_version'] = health.json()['version']
    if mode == 'public':
        check('public source identity', report['build_version'], snapshot['source_sha'])
    for pk, game in games.items():
        response = page.goto(base + f'/games/{pk}/', wait_until='networkidle')
        check(f'HTTP saved ID {pk}', response.status, 200)
        check(f'title saved ID {pk}', page.locator('h1').inner_text(), game['title'])
        actual = links(page)
        check(f'saved results and order {pk}', ids(actual), oracle(pk))
        check(f'linked titles {pk}', [r['title'] for r in actual],
              [games[i]['title'] for i in oracle(pk)])
        if not actual:
            check(f'empty state {pk}', page.get_by_text('No similar games in the catalog yet.', exact=True).is_visible())
    query_id = snapshot['query_id']
    if mode == 'fixture':
        check('independent fixture expected order', oracle(query_id), snapshot['expected_query_ids'])
    response = page.goto(base + f'/games/{query_id}/?q=elden&platform=pc', wait_until='networkidle')
    original = links(page)
    check('nonempty public/fixture relation', len(original) > 0)
    check('CSS applied', page.locator('main').evaluate('e => getComputedStyle(e).maxWidth') != 'none')
    fit(page, 'desktop relation')
    capture(page, 'desktop')
    page.set_viewport_size({'width': 390, 'height': 844})
    fit(page, 'mobile relation')
    page.locator('#similar-games-heading').scroll_into_view_if_needed()
    capture(page, 'mobile')
    expected_id = query_id
    for i, row in enumerate(original):
        page.goto(base + f'/games/{query_id}/?q=elden&platform=pc', wait_until='networkidle')
        page.locator('.similar-games a').nth(i).click()
        page.wait_for_load_state('networkidle')
        expected_id = ids([row])[0]
        check(f'click opens saved ID {expected_id}', urlsplit(page.url).path, f'/games/{expected_id}/')
        check(f'click title {expected_id}', page.locator('h1').inner_text(), games[expected_id]['title'])
        check(f'list context {expected_id}', page.locator('.game-card__back').get_attribute('href'), '/?q=elden&platform=pc')
        fit(page, f'mobile destination {expected_id}')
    page.reload(wait_until='networkidle')
    check('repeat after reload', ids(links(page)), oracle(expected_id))
    page.locator('.game-card__back').click()
    page.wait_for_load_state('networkidle')
    check('back search field', page.locator('#q').input_value(), 'elden')
    check('back platform field', page.locator('#platform').input_value(), 'pc')
    check('browser errors', errors, [])
    browser.close()

report['passed'] = all(item['pass'] for item in report['checks'])
(OUT / (mode + '-browser.json')).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps({'mode': mode, 'checks': len(report['checks']), 'passed': report['passed'],
                  'failures': [item for item in report['checks'] if not item['pass']]}))
raise SystemExit(0 if report['passed'] else 1)
