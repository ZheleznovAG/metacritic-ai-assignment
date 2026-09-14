"""Disposable PostgreSQL browser fixture for SIM-VER-01; never application data."""
import json
import os
import sys
import uuid
from pathlib import Path
from wsgiref.simple_server import make_server

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / '.artifacts/sim-ver-01'
OUT.mkdir(exist_ok=True)
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
from catalog.models import Game, GamePlatform
from django.core.wsgi import get_wsgi_application
from django.db import connections
from django.db.backends.signals import connection_created
from django.test.runner import DiscoverRunner

connections['default'].settings_dict['TEST']['NAME'] = 'test_metacritic_sim_' + uuid.uuid4().hex[:10]
runner = DiscoverRunner(verbosity=0, interactive=False)
runner.setup_test_environment()
old_config = runner.setup_databases()

def readonly(sender, connection, **kwargs):
    with connection.cursor() as cursor:
        cursor.execute('SET default_transaction_read_only = on')

try:
    for pk, title, genres in (
        (101, 'Cinderbound', ['Action RPG', 'Role-Playing']),
        (102, 'Stone Oath', ['Action RPG', 'Role-Playing']),
        (103, 'Ashen Pilgrim', ['Action RPG', 'Role-Playing']),
        (104, 'Mosaic', ['Puzzle']),
        (105, 'Unknown genres', []),
        (106, 'W' * 255, ['Role-Playing']),
        (107, 'Ashen Pilgrim', ['Action RPG', 'Role-Playing']),
    ):
        game = Game.objects.create(id=pk, source_game_id=f'sim-{pk}',
            canonical_locator=f'/game/sim-{pk}/', title=title, genres=genres,
            developer='Example Studio', description=f'Synthetic saved identity {pk}.')
        for slug, name in [('pc', 'PC'), ('ps5', 'PlayStation 5')]:
            GamePlatform.objects.create(game=game, source_platform_id=slug,
                source_game_platform_id=f'sim-{pk}-{slug}', slug=slug, name=name)
    games = list(Game.objects.order_by('id').values('id', 'title', 'genres'))
    (OUT / 'fixture-snapshot.json').write_text(json.dumps({'games': games,
        'query_id': 101, 'empty_id': 105, 'expected_query_ids': [103, 107, 102, 106]}),
        encoding='utf-8', newline='\n')
    application = get_wsgi_application()
    connections.close_all()
    connection_created.connect(readonly)
    with make_server('127.0.0.1', 18766, application) as server:
        server.timeout = 1
        print('READY: isolated similarity fixture on 127.0.0.1:18766', flush=True)
        while not (OUT / 'preview.stop').exists():
            server.handle_request()
finally:
    connection_created.disconnect(readonly)
    connections.close_all()
    runner.teardown_databases(old_config)
    runner.teardown_test_environment()
    print('Fixture database removed.', flush=True)
