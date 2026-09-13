"""R04: preserve existing text hashes/foreign keys, version metadata-only source edits."""

import hashlib
import json

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def populate_versions(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    review_model = apps.get_model("reviews", "Review")
    manager = review_model.objects.using(schema_editor.connection.alias)
    batch = []
    for row in manager.values(
        "id", "text_original", "author_label", "score_label", "date_label"
    ).iterator(chunk_size=1000):
        # Frozen migration formula: do not import runtime code whose versions may change.
        payload = json.dumps(
            {
                "version": 1,
                "text": row["text_original"],
                "author": row["author_label"],
                "score": row["score_label"],
                "date": row["date_label"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        batch.append(
            review_model(
                id=row["id"], version_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest()
            )
        )
        if len(batch) == 1000:
            manager.bulk_update(batch, ["version_sha256"], batch_size=1000)
            batch.clear()
    if batch:
        manager.bulk_update(batch, ["version_sha256"], batch_size=1000)


class Migration(migrations.Migration):
    dependencies = [("reviews", "0003_reviewcollectionjob_created_at")]

    operations = [
        migrations.AddField(
            model_name="review",
            name="version_sha256",
            field=models.CharField(max_length=64, null=True),
        ),
        migrations.RunPython(populate_versions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="review",
            name="version_sha256",
            field=models.CharField(max_length=64),
        ),
        migrations.RemoveConstraint(
            model_name="review", name="uq_review_platform_audience_identity_content"
        ),
        migrations.AddConstraint(
            model_name="review",
            constraint=models.UniqueConstraint(
                fields=("game_platform", "audience", "identity_key", "version_sha256"),
                name="uq_review_platform_audience_identity_version",
            ),
        ),
    ]
