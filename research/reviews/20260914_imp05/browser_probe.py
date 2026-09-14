"""One-off IMP-05 observation; public access data never enters the report."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / '.artifacts/imp05-revalidation'
EVIDENCE = ROOT / 'docs/evidence'
mode = sys.argv[1]
if mode == 'public':
    cfg = dotenv_values(ROOT / '.env')
    base = 'http://' + cfg['DEPLOY_SSH_HOST'] + ':18081'
else:
    base = 'http://127.0.0.1:18765'
report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'mode': mode, 'checks': [], 'screenshots': []}

def check(label, actual, expected=True):
    report['checks'].append({'check': label, 'actual': actual, 'expected': expected, 'pass': actual == expected})
    if actual != expected:
        print('FAIL:', label, flush=True)

def capture(page, name):
    filename = 'imp-05-' + name + '-2026-09-14.png'
    page.screenshot(path=str(EVIDENCE / filename), full_page=True)
    report['screenshots'].append(filename)

def listing(page):
    return page.locator('.game-list__item').evaluate_all('''items => items.map(el => ({
        title: el.querySelector('.game-list__title').textContent.trim(),
        score: el.querySelector('.game-list__score').textContent.trim(),
        path: el.querySelector('a').getAttribute('href')
    }))''')

def fit(page, label):
    report.setdefault('layout', []).append({'page': label, 'viewport': page.viewport_size, 'scroll_width': page.evaluate('document.documentElement.scrollWidth')})
    check(label + ' has no horizontal overflow', page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))

def navigate(page, path):
    response = page.goto(base + path, wait_until='networkidle')
    check('HTTP ' + path, response.status, 200)

def run():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        report['browser'] = browser.version
        page = browser.new_page(viewport={'width':1280,'height':1050}, device_scale_factor=1)
        errors = []
        page.on('pageerror', lambda error: errors.append(type(error).__name__))
        health = page.request.get(base + '/health/ready/')
        check('readiness', health.status, 200)
        report['build_version'] = health.json()['version']
        navigate(page, '/')
        initial = listing(page)
        report['initial_list'] = initial
        check('every card ID appears once', len(set(x['path'] for x in initial)), len(initial))
        check('CSS applied', page.locator('main').evaluate('el => getComputedStyle(el).maxWidth') != 'none')
        css_path = page.locator('link[rel="stylesheet"]').get_attribute('href')
        css = page.request.get(base + css_path)
        check('CSS response', css.status, 200)
        report['css_sha256'] = hashlib.sha256(css.body()).hexdigest()
        fit(page, 'desktop list')

        if mode == 'public':
            expected = json.loads((ROOT / 'docs/evidence/imp-02-revalidation-2026-09-14.json').read_text(encoding='utf-8'))['oracle']
            saved = json.loads((EVIDENCE/'imp-05-public-db-2026-09-14.json').read_text(encoding='utf-8'))
            def oracle(query='', platform=None):
                items = []
                for game in saved['games']:
                    if query.casefold() not in game['title'].casefold():
                        continue
                    platforms = [p for p in game['platforms'] if platform is None or p['slug']==platform]
                    if platform is not None and not platforms:
                        continue
                    scores = [p['metascore'] for p in platforms if p['metascore'] is not None]
                    items.append((game['id'],game['title'],max(scores) if scores else None))
                items.sort(key=lambda x:(x[2] is None,-(x[2] or 0),x[1].casefold()))
                return [(title,str(score) if score is not None else 'No score', '/games/'+str(pk)+'/') for pk,title,score in items]
            def actual_rows():
                return [(x['title'],x['score'],urlsplit(x['path']).path) for x in listing(page)]
            check('entire real catalog matches independent DB snapshot', actual_rows(), oracle())
            capture(page, 'public-list')
            for platform in ('pc','playstation-5','xbox-one'):
                navigate(page,'/?platform='+platform)
                check('public '+platform+' membership and order match DB',actual_rows(),oracle(platform=platform))
            navigate(page,'/?q=ELDEN')
            check('public uppercase substring matches DB',actual_rows(),oracle(query='ELDEN'))
            navigate(page,'/')
            page.locator('#q').fill('ELDEN')
            page.locator('#platform').select_option('pc')
            page.get_by_role('button', name='Filter', exact=True).click()
            page.wait_for_load_state('networkidle')
            check('case-insensitive search plus PC uses matched score', [(x['title'],x['score']) for x in listing(page)], [('Elden Ring','94')])
            selected_query = urlsplit(page.url).query
            page.locator('.game-list__title').click()
            page.wait_for_load_state('networkidle')
            check('card title', page.locator('h1').inner_text(), expected['game']['title'])
            facts = page.locator('dl').evaluate('el => Object.fromEntries([...el.querySelectorAll("dt")].map(dt => [dt.textContent.trim(), dt.nextElementSibling.textContent.trim()]))')
            check('developer matches source oracle', facts['Developer'], expected['game']['developer'])
            check('description matches source oracle', hashlib.sha256(facts['Description'].encode()).hexdigest(), expected['description_sha256'])
            check('trailer matches source oracle', page.get_by_role('link',name='Watch trailer').get_attribute('href'), expected['game']['video_embed_url'])
            check('cover matches source oracle', page.locator('.game-card__cover').get_attribute('src'), expected['game']['cover_url'])
            check('cover actually loaded', page.locator('.game-card__cover').evaluate('el => el.complete && el.naturalWidth > 0'))
            rows = page.locator('.game-card__platforms tbody tr').evaluate_all('rows => rows.map(row => [...row.children].map(cell => cell.textContent.trim()))')
            check('five real platforms',len(rows),5)
            for name, score, userscore in rows:
                item = next(p for p in expected['platforms'] if p['name'] == name)
                check(name + ' Metascore', score, str(item['metascore']) if item['metascore'] is not None else 'No data')
                check(name + ' Userscore', Decimal(userscore) == Decimal(item['userscore']))
            check('two summaries pending', ['Pending' in text for text in page.locator('.game-card__summary').all_inner_texts()], [True,True])
            fit(page, 'desktop card')
            capture(page,'public-card-desktop')
            page.set_viewport_size({'width':390,'height':844})
            fit(page,'mobile card')
            capture(page,'public-card-mobile')
            page.get_by_role('link',name='Back to results').click()
            page.wait_for_load_state('networkidle')
            check('navigation retains query', urlsplit(page.url).query, selected_query)
            check('form query retained', page.locator('#q').input_value(),'ELDEN')
            check('form platform retained', page.locator('#platform').input_value(),'pc')
            fit(page,'mobile combined list')
            capture(page,'public-filter-mobile')
        else:
            expected_titles = ['Alpha fixture','Audit fixture: cached summary','Audit fixture: collection in progress','Apple fixture','banana fixture','Zero fixture','No platforms fixture','Null fixture','W'*255]
            check('unfiltered sort: max, ties, zero, null, no platforms', [x['title'] for x in initial],expected_titles)
            capture(page,'fixture-list-desktop')
            page.set_viewport_size({'width':390,'height':844})
            fit(page,'fixture mobile list with 255-character title')
            capture(page,'fixture-list-mobile')
            navigate(page,'/?q=FiXtUrE&platform=pc')
            check('combined filter changes order and excludes wrong platforms',[(x['title'],x['score']) for x in listing(page)],[(name,score) for name,score in [('Audit fixture: cached summary','82'),('Audit fixture: collection in progress','82'),('Apple fixture','80'),('banana fixture','80'),('Alpha fixture','40'),('Zero fixture','0'),('Null fixture','No score')]])
            before = listing(page)
            page.locator('.game-list__title',has_text='Alpha fixture').click()
            page.wait_for_load_state('networkidle')
            check('missing core fields honest', page.locator('.game-card__facts .no-data').count(),3)
            check('pending audiences on new game', ['Pending' in text for text in page.locator('.game-card__summary').all_inner_texts()],[True,True])
            page.get_by_role('link',name='Back to results').click()
            page.wait_for_load_state('networkidle')
            check('filtered list survives navigation',listing(page),before)
            manifest=json.loads((OUT/'ui-preview.json').read_text(encoding='utf-8'))
            navigate(page,manifest['fresh'])
            check('fresh cached summary has current coverage','10 of 11 fetched' in page.locator('body').inner_text())
            check('fresh card has no stale marker',page.locator('.summary-stale').count(),0)
            check('insufficient audience explained','Not enough meaningful reviews yet' in page.locator('body').inner_text())
            check('content-only trailer fallback',page.get_by_role('link',name='Watch trailer').get_attribute('href'),'https://example.invalid/trailer.mp4')
            capture(page,'fixture-fresh-mobile')
            navigate(page,manifest['stale'])
            check('both previous summaries marked stale',page.locator('.summary-stale').count(),2)
            check('stale collection reason readable','New reviews are being collected.' in page.locator('body').inner_text())
            check('stale insufficient explanation preserved','Not enough meaningful reviews yet' in page.locator('body').inner_text())
            fit(page,'mobile stale card')
            capture(page,'fixture-stale-mobile')
            navigate(page,'/games/9/')
            check('255-character title preserved on card',len(page.locator('h1').inner_text()),255)
            fit(page,'mobile 255-character unbroken title card')
            capture(page,'fixture-long-title-mobile')

        navigate(page,'/?q=zzznotagame')
        check('unknown search empty', page.locator('.game-list__item').count(),0)
        check('empty message',page.locator('.game-list__empty').inner_text(),'No games match this search/filter combination.')
        page.get_by_role('link',name='Reset',exact=True).click()
        page.wait_for_load_state('networkidle')
        check('reset restores entire catalog',listing(page),initial)
        navigate(page,'/?platform=not-a-platform')
        check('unknown platform yields no cards',page.locator('.game-list__item').count(),0)
        check('unknown card is 404',page.request.get(base+'/games/999999/').status,404)
        rejected = page.request.post(base+'/').status
        report['post_status'] = rejected
        check('read-only method boundary',rejected in (403,405))
        check('no browser script errors',errors,[])
        browser.close()

try:
    run()
except Exception as error:
    report['exception'] = type(error).__name__
    print('Probe error:', type(error).__name__, '(private URL omitted)')
finally:
    report['all_pass'] = 'exception' not in report and all(item['pass'] for item in report['checks'])
    (OUT/(mode+'-browser.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(mode, 'checks',len(report['checks']),'all_pass', report['all_pass'])
sys.exit(0 if report['all_pass'] else 1)
