"""Decode HTML entities that older detail fetches left in `Game.description`.

Metacritic returns some legacy listings with entity-encoded text (`&bull;`, `&rsquo;`, `&nbsp;`).
The parser now decodes it on ingest; this brings rows saved earlier in line. One pass only, so a
literal `&amp;amp;` is not decoded twice, and rows without an entity are not touched.
"""

import html
import re

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

ENTITY = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6});")


def unescape_descriptions(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Game = apps.get_model("catalog", "Game")
    for game in Game.objects.filter(description__regex=r"&[#a-zA-Z]").iterator():
        if game.description and ENTITY.search(game.description):
            game.description = html.unescape(game.description).replace("\xa0", " ")
            game.save(update_fields=["description"])


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0007_game_release_date_publishers_content_rating"),
    ]

    operations = [
        migrations.RunPython(unescape_descriptions, migrations.RunPython.noop),
    ]
