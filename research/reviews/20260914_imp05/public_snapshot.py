"""Read catalog/summary state using the running web container's SELECT-only role."""
import json
import subprocess

container = 'metacritic-imp01-prod-web-1'
code = '''
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,'/opt/app/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from catalog.models import Game
from presentation.summaries import get_summaries
from dataclasses import asdict
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute('SHOW server_version')
    version = cursor.fetchone()[0]
result={'postgresql':version,'games':[],'source_hashes':{}}
for game in Game.objects.order_by('id'):
    item={key:getattr(game,key) for key in ('id','title','developer','cover_url','video_embed_url','video_content_url')}
    item['description_sha256']=hashlib.sha256((game.description or '').encode()).hexdigest()
    item['platforms']=list(game.platforms.order_by('slug').values('slug','name','metascore','userscore'))
    item['summaries']=[{k:v for k,v in asdict(s).items() if k not in ('likes','dislikes')} for s in get_summaries(game)]
    result['games'].append(item)
for name in ('app/catalog/queries.py','app/presentation/views.py','app/presentation/summaries.py','app/reviews/snapshots.py','app/summaries/contour.py','app/presentation/static/presentation/app.css','app/presentation/templates/presentation/index.html','app/presentation/templates/presentation/game_detail.html'):
    result['source_hashes'][name]=hashlib.sha256((Path('/opt/app')/name).read_bytes()).hexdigest()
print(json.dumps(result,default=str,sort_keys=True))
'''
raw = subprocess.check_output(['docker','exec',container,'python','-B','-c',code],text=True)
data = json.loads(raw)
info=json.loads(subprocess.check_output(['docker','inspect',container],text=True))[0]
data['image_id']=info['Image']
data['healthy']=info['State']['Health']['Status']=='healthy'
print(json.dumps(data,sort_keys=True))
