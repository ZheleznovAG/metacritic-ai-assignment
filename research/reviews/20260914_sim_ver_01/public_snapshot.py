"""Read the current saved similarity inputs/results through the web SELECT-only role."""
import json
import subprocess

code = '''
import os,sys,json,hashlib
from pathlib import Path
from dataclasses import asdict
sys.path.insert(0,'/opt/app/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from catalog.models import Game,SourceFetch
from catalog.queries import list_similar_games
result={'source_sha':Path('/opt/app/app/build-version.txt').read_text().strip(),
    'query_id':1,'games':[],'source_hashes':{}}
for game in Game.objects.order_by('id'):
    item={k:getattr(game,k) for k in ('id','title','genres','genres_last_changed_fetch_id')}
    item['similar']=[asdict(x) for x in list_similar_games(game.id)]
    result['games'].append(item)
result['genre_fetches']=list(SourceFetch.objects.filter(pk__in=Game.objects.values('genres_last_changed_fetch_id')).values('id','url','response_sha256','parser_contract_version','outcome','http_status','completed_at'))
for name in ('app/catalog/queries.py','app/similarity/policy.py','app/presentation/views.py','app/presentation/templates/presentation/game_detail.html','app/presentation/static/presentation/app.css'):
    result['source_hashes'][name]=hashlib.sha256((Path('/opt/app')/name).read_bytes()).hexdigest()
print(json.dumps(result,default=str,sort_keys=True))
'''
result = json.loads(subprocess.check_output(['docker','exec','metacritic-imp01-prod-web-1','python','-B','-c',code], text=True))
info = json.loads(subprocess.check_output(['docker','inspect','metacritic-imp01-prod-web-1'], text=True))[0]
result['image_id'] = info['Image']
result['healthy'] = info['State']['Health']['Status'] == 'healthy'
print(json.dumps(result,sort_keys=True))
