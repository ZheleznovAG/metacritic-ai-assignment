import os
import sys
import json
import uuid
from pathlib import Path
from datetime import timedelta
from wsgiref.simple_server import make_server

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
(ROOT / '.artifacts/imp05-revalidation').mkdir(parents=True, exist_ok=True)
load_dotenv(ROOT / '.env.app', override=False)
if os.environ.get('APP_ENV') == 'production':
    raise SystemExit('Preview refuses production')
os.environ['DATABASE_USER'] = os.environ['CHECKS_DB_USER']
os.environ['DATABASE_PASSWORD'] = os.environ['CHECKS_DB_PASSWORD']
os.environ['POSTGRES_DB'] += '_checks'
os.environ['APP_ENV'] = 'test'
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
sys.path.insert(0, str(ROOT / 'app'))
import django
django.setup()
from django.db import connections
from django.db.backends.signals import connection_created
from django.core.wsgi import get_wsgi_application
from django.test.runner import DiscoverRunner
from catalog.models import Game, GamePlatform
from processing.models import DailyCycle, DailyCandidate
from reviews.models import ReviewCollectionJob, ReviewCorpus
from reviews import collector
from summaries import worker
from tests.test_reviews_collector import FakeClock, FakeGateway
from tests.test_reviews_snapshots import NOW, page
from tests.test_summary_admission import process, ok

connections['default'].settings_dict['TEST']['NAME'] = 'test_metacritic_ui_' + uuid.uuid4().hex[:10]
runner = DiscoverRunner(verbosity=0, interactive=False)
runner.setup_test_environment()
old_config = runner.setup_databases()
clock = FakeClock(NOW)

def collect(game, platform, day, critic_ids):
    clock.instant = NOW + timedelta(days=day)
    cycle, _ = DailyCycle.objects.get_or_create(business_date=clock.instant.date())
    candidate = DailyCandidate.objects.create(cycle=cycle, game=game, source_order=1, state='processed')
    for audience, ids in (('critic', critic_ids), ('user', (1,))):
        ReviewCollectionJob.objects.create(daily_candidate=candidate, game_platform=platform, audience=audience)
        claim = collector.claim_next_job(clock)
        assert claim is not None
        collector.collect_one_page(FakeGateway({None: page(*ids)}), clock, claim)

def publish():
    while (claim := worker.claim_next_job(clock)) is not None:
        result = process(claim, clock, ok)
        assert result.state in ('succeeded', 'insufficient_data'), result.state
        clock.instant += timedelta(minutes=1)

def readonly(sender, connection, **kwargs):
    with connection.cursor() as cursor:
        cursor.execute('SET default_transaction_read_only = on')

try:
    games = []
    for number, title in ((1, 'Audit fixture: cached summary'), (2, 'Audit fixture: collection in progress')):
        game = Game.objects.create(source_game_id=f'audit-{number}', canonical_locator=f'/game/audit-{number}/', title=title,
            developer='Example Studio', description='Synthetic review data for checking summary freshness and coverage.',
            video_content_url='https://example.invalid/trailer.mp4')
        platform = GamePlatform.objects.create(game=game, source_platform_id='pc', source_game_platform_id=f'audit-pc-{number}',
            slug='pc', name='PC', metascore=82, userscore='8.4', critic_reviews_path='/critic/', user_reviews_path='/user/')
        collect(game, platform, number * 2, tuple(range(1, 13)))
        publish()
        if number == 1:
            corpus = ReviewCorpus.objects.get(game=game, audience='critic')
            selected = {int(item.review.source_review_id) for item in corpus.items.select_related('review')}
            removed = next(i for i in range(1, 13) if i not in selected)
            collect(game, platform, number * 2 + 1, tuple(i for i in range(1, 13) if i != removed))
        games.append((game, platform))
    game, platform = games[-1]
    cycle, _ = DailyCycle.objects.get_or_create(business_date=(NOW + timedelta(days=5)).date())
    candidate = DailyCandidate.objects.create(cycle=cycle, game=game, source_order=1, state='processed')
    for audience in ('critic', 'user'):
        ReviewCollectionJob.objects.create(daily_candidate=candidate, game_platform=platform, audience=audience)
    from tests.test_catalog_queries_list import _game, _platform
    for n, title, scores in (
        (10, 'Alpha fixture', [('pc', 'PC', 40), ('ps5', 'PlayStation 5', 95)]),
        (11, 'banana fixture', [('pc', 'PC', 80)]),
        (12, 'Apple fixture', [('pc', 'PC', 80)]),
        (13, 'Zero fixture', [('pc', 'PC', 0)]),
        (14, 'Null fixture', [('pc', 'PC', None)]),
        (15, 'No platforms fixture', []),
        (16, 'W' * 255, [('ps5', 'PlayStation 5', None)]),
    ):
        game = _game(n, title)
        for slug, name, score in scores:
            _platform(game, slug, name, score)
    application = get_wsgi_application()
    connections.close_all()
    connection_created.connect(readonly)
    with make_server('127.0.0.1', 18765, application) as server:
        server.timeout = 1
        manifest = {'base_url': 'http://127.0.0.1:18765', 'fresh': f'/games/{games[0][0].pk}/', 'stale': f'/games/{games[1][0].pk}/'}
        (ROOT / '.artifacts/imp05-revalidation/ui-preview.json').write_text(json.dumps(manifest), encoding='utf-8')
        print('READY: isolated synthetic UI preview on 127.0.0.1:18765', flush=True)
        while not (ROOT / '.artifacts/imp05-revalidation/ui-preview.stop').exists():
            server.handle_request()
finally:
    connection_created.disconnect(readonly)
    connections.close_all()
    runner.teardown_databases(old_config)
    runner.teardown_test_environment()
    print('Preview test database removed.', flush=True)
