"""Normal live detail ingestion of two existing IDs; scheduler role, no AI calls."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

root = (Path.home() / 'metacritic-ai-assignment-imp01').resolve()
assert root.parent == Path.home().resolve() and root.is_dir()
os.umask(0o077)
cfg = dict(line.split('=', 1) for line in (root / '.env.app').read_text().splitlines()
           if '=' in line and not line.startswith('#'))
version = '408bd62bce72b2bfb6bfb53788b50bf9db618b28'
assert cfg['APP_IMAGE'] == 'metacritic-imp01:' + version
web = json.loads(subprocess.check_output(['docker', 'inspect', 'metacritic-imp01-prod-web-1'], text=True))[0]
assert web['Image'] == 'sha256:d6f6e12fc9098089f70e4f4946c8e9632bfe543a6e3ea6d62ca166d86e18d914'
assert web['State']['Health']['Status'] == 'healthy'
processes = subprocess.check_output(['ps', '-eo', 'args'], text=True)
assert not any(x in processes for x in ['run_scheduler.py', 'run_worker.py', 'manage.py run_scheduler', 'manage.py run_worker'])
snapshot_code = '''
import os,sys,json
sys.path.insert(0,'/opt/app/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from catalog.models import Game,SourceFetch
from summaries.models import ReviewSummary,SummaryAttempt
result={'games':list(Game.objects.order_by('id').values('id','source_game_id','canonical_locator','title','genres','genres_last_changed_fetch_id')),
    'summary_count':ReviewSummary.objects.count(),'summary_attempt_count':SummaryAttempt.objects.count(),
    'genre_fetches':list(SourceFetch.objects.filter(pk__in=Game.objects.filter(pk__in=[1,13]).values('genres_last_changed_fetch_id')).values('id','url','response_sha256','parser_contract_version','outcome','http_status','completed_at'))}
print(json.dumps(result,default=str,sort_keys=True))
'''

def snapshot():
    return json.loads(subprocess.check_output(['docker','exec','metacritic-imp01-prod-web-1','python','-B','-c',snapshot_code], text=True))

before = snapshot()
targets = [game for game in before['games'] if game['id'] in [1,13]]
assert {game['id'] for game in targets} == {1,13}
assert all(not game['genres'] for game in before['games']), 'Expected first normal genre refresh after additive migration'
print('BEFORE', json.dumps(before,sort_keys=True), flush=True)
environment = {
    'APP_ENV':'production','DJANGO_SECRET_KEY':cfg['DJANGO_SECRET_KEY'],
    'DJANGO_ALLOWED_HOSTS':cfg['DJANGO_ALLOWED_HOSTS'],'DJANGO_HTTPS':cfg.get('DJANGO_HTTPS','false'),
    'POSTGRES_DB':cfg['POSTGRES_DB'],'POSTGRES_HOST':'db','POSTGRES_PORT':'5432',
    'DATABASE_USER':cfg['SCHEDULER_DB_USER'],'DATABASE_PASSWORD':cfg['SCHEDULER_DB_PASSWORD'],
}
assert all('\n' not in value and '\r' not in value for value in environment.values())
env_path = None
try:
    with tempfile.NamedTemporaryFile(mode='w',prefix='.sim-ver-env-',dir=root,delete=False) as file:
        env_path = Path(file.name)
        file.write('\n'.join(k+'='+v for k,v in environment.items())+'\n')
    env_path.chmod(0o600)
    for game in targets:
        assert game['canonical_locator'].startswith('/game/')
        url = 'https://www.metacritic.com' + game['canonical_locator']
        result = subprocess.run(['docker','run','--rm','--name','metacritic-sim-ver-refresh-'+str(game['id']),
            '--network','metacritic-imp01-prod_backend','--network','metacritic-imp01-prod_edge',
            '--env-file',str(env_path),'--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--memory','384m','--tmpfs','/tmp:size=32m,mode=1777',cfg['APP_IMAGE'],
            'python','-B','app/manage.py','ingest_game',url],capture_output=True,text=True,timeout=240)
        print('INGEST',game['id'],'exit',result.returncode,result.stdout.strip(),result.stderr.strip(),flush=True)
        if result.returncode:
            print('AFTER_FAILURE',json.dumps(snapshot(),sort_keys=True),flush=True)
            raise SystemExit(result.returncode)
    after = snapshot()
    print('AFTER',json.dumps(after,sort_keys=True),flush=True)
    assert [(g['id'],g['source_game_id']) for g in before['games']] == [(g['id'],g['source_game_id']) for g in after['games']]
    assert before['summary_count'] == after['summary_count']
    assert before['summary_attempt_count'] == after['summary_attempt_count']
    refreshed = [g for g in after['games'] if g['id'] in [1,13]]
    assert all(g['genres'] and g['genres_last_changed_fetch_id'] for g in refreshed)
    assert set(refreshed[0]['genres']) & set(refreshed[1]['genres']), 'No real shared genre observed; do not fabricate a match'
    assert len(after['genre_fetches']) == 2
    assert all(f['outcome']=='succeeded' and f['http_status']==200 and f['parser_contract_version']=='1.1.0' for f in after['genre_fetches'])
    assert all(not g['genres'] for g in after['games'] if g['id'] not in [1,13])
    print('PASS normal source -> stored genre/provenance for IDs 1 and 13; stable catalog identities; no AI attempts',flush=True)
finally:
    if env_path is not None:
        assert env_path.resolve().parent == root
        env_path.unlink()
