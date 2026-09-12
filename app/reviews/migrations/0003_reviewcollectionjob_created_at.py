import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0002_review_collection_and_corpus"),
    ]

    operations = [
        migrations.AddField(
            model_name="reviewcollectionjob",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True, null=True, default=django.utils.timezone.now
            ),
            preserve_default=False,
        ),
    ]
