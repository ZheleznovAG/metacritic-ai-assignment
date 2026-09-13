"""R04 upgrade: real populated PostgreSQL schema, immutable hashes and historical FKs."""

import hashlib

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from reviews import collector
from reviews.models import Review, ReviewCorpusItem, ReviewObservation
from reviews.versioning import version_fingerprint

from tests.test_reviews_collector import FakeClock, FakeGateway, _make_job
from tests.test_reviews_snapshots import NOW, page


class ReviewVersionMigrationTests(TransactionTestCase):
    def test_backfill_preserves_text_hashes_history_and_allows_metadata_only_versions(self) -> None:
        initial = _make_job()
        clock = FakeClock(NOW)
        claim = collector.claim_next_job(clock)
        assert claim is not None
        collector.collect_one_page(FakeGateway({None: page(1, 2, 3)}), clock, claim)
        # Cross the migration's 1,000-row batch boundary, including Unicode and null labels.
        Review.objects.bulk_create(
            Review(
                game_platform=initial.game_platform,
                audience="critic",
                identity_key=f"id:historical-{i}",
                text_original=f"Исторический отзыв {i}",
                content_sha256=hashlib.sha256(f"Исторический отзыв {i}".encode()).hexdigest(),
                version_sha256="before-backfill",
                first_seen_at=NOW,
            )
            for i in range(1001)
        )
        original = Review.objects.get(identity_key="id:1")
        Review.objects.filter(identity_key="id:2").update(supersedes=original)
        fields = ("id", "identity_key", "text_original", "content_sha256", "supersedes_id")
        history = list(Review.objects.order_by("id").values_list(*fields))
        observations = list(
            ReviewObservation.objects.values_list("id", "review_id", "source_fetch_id")
        )
        items = list(ReviewCorpusItem.objects.values_list("id", "review_id", "input_text"))

        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([("reviews", "0003_reviewcollectionjob_created_at")])
            # The upgrade now starts with the old production schema and populated FKs.
            MigrationExecutor(connection).migrate(latest)
        finally:
            MigrationExecutor(connection).migrate(latest)

        self.assertEqual(list(Review.objects.order_by("id").values_list(*fields)), history)
        self.assertEqual(
            list(ReviewObservation.objects.values_list("id", "review_id", "source_fetch_id")),
            observations,
        )
        self.assertEqual(
            list(ReviewCorpusItem.objects.values_list("id", "review_id", "input_text")), items
        )
        for review in Review.objects.all():
            self.assertEqual(
                review.version_sha256,
                version_fingerprint(
                    review.text_original, review.author_label, review.score_label, review.date_label
                ),
            )
        original.refresh_from_db()
        new_version = Review.objects.create(
            game_platform=original.game_platform,
            audience=original.audience,
            identity_key=original.identity_key,
            text_original=original.text_original,
            author_label=original.author_label,
            date_label=original.date_label,
            score_label="1",
            content_sha256=original.content_sha256,
            version_sha256=version_fingerprint(
                original.text_original, original.author_label, "1", original.date_label
            ),
            first_seen_at=NOW,
            supersedes=original,
        )
        self.assertNotEqual(new_version.pk, original.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            new_version.pk = None
            new_version.save(force_insert=True)
