from dataclasses import replace

from django.test import SimpleTestCase
from reviews.selection import (
    MAX_REVIEW_TOKENS,
    MAX_SELECTED_REVIEWS,
    IncompleteCollectionError,
    ReviewRecord,
    SelectionPool,
    count_tokens,
    select_reviews,
)


def _review(
    key: str,
    *,
    platform: str = "pc",
    text: str = "Some review text.",
    duplicate_of: str | None = None,
) -> ReviewRecord:
    return ReviewRecord(
        identity_key=key,
        platform_slug=platform,
        page_offset=0,
        language="en",
        score=8,
        text=text,
        meaningful=True,
        duplicate_of=duplicate_of,
    )


class SelectReviewsTests(SimpleTestCase):
    def test_incomplete_pool_raises(self) -> None:
        pool = SelectionPool(
            audience="user", game_slug="g", collection_status="partial", reviews=(_review("k1"),)
        )
        with self.assertRaises(IncompleteCollectionError):
            select_reviews(pool)

    def test_caps_at_ten_and_reports_pool_counts(self) -> None:
        reviews = tuple(_review(f"k{i}") for i in range(15))
        pool = SelectionPool(
            audience="user", game_slug="g", collection_status="complete", reviews=reviews
        )
        result = select_reviews(pool)
        self.assertEqual(len(result.selected), MAX_SELECTED_REVIEWS)
        self.assertEqual(result.total_pool_count, 15)
        self.assertEqual(result.meaningful_pool_count, 15)

    def test_deduplicates_cross_platform_duplicates(self) -> None:
        reviews = (
            _review("p5-1", platform="ps5"),
            _review("xs-1", platform="xbox", duplicate_of="p5-1"),
        )
        pool = SelectionPool(
            audience="critic", game_slug="g", collection_status="complete", reviews=reviews
        )
        result = select_reviews(pool)
        keys = {item.identity_key for item in result.selected}
        self.assertEqual(len(keys), 1)
        # Deterministic representative: lexicographically smallest identity key in the group.
        self.assertEqual(keys, {"p5-1"})

    def test_spans_multiple_platforms_via_round_robin(self) -> None:
        reviews = tuple(_review(f"a{i}", platform="a") for i in range(6)) + tuple(
            _review(f"b{i}", platform="b") for i in range(6)
        )
        pool = SelectionPool(
            audience="user", game_slug="g", collection_status="complete", reviews=reviews
        )
        result = select_reviews(pool)
        platforms = {item.platform_slug for item in result.selected}
        self.assertEqual(platforms, {"a", "b"})

    def test_deterministic_repeat(self) -> None:
        reviews = tuple(_review(f"k{i}") for i in range(15))
        pool = SelectionPool(
            audience="user", game_slug="g", collection_status="complete", reviews=reviews
        )
        first = tuple(item.identity_key for item in select_reviews(pool).selected)
        second = tuple(item.identity_key for item in select_reviews(pool).selected)
        self.assertEqual(first, second)

    def test_long_review_is_truncated_at_a_token_boundary(self) -> None:
        long_text = "word " * 2000
        pool = SelectionPool(
            audience="user",
            game_slug="g",
            collection_status="complete",
            reviews=(_review("k1", text=long_text),),
        )
        result = select_reviews(pool)
        item = result.selected[0]
        self.assertTrue(item.truncated)
        self.assertLessEqual(item.token_count, MAX_REVIEW_TOKENS)
        self.assertEqual(count_tokens(item.text), MAX_REVIEW_TOKENS)

    def test_short_review_is_not_truncated(self) -> None:
        pool = SelectionPool(
            audience="user",
            game_slug="g",
            collection_status="complete",
            reviews=(_review("k1", text="Short review."),),
        )
        result = select_reviews(pool)
        item = result.selected[0]
        self.assertFalse(item.truncated)
        self.assertEqual(item.text, "Short review.")

    def test_selection_never_invents_a_review(self) -> None:
        reviews = tuple(_review(f"k{i}") for i in range(3))
        pool = SelectionPool(
            audience="user", game_slug="g", collection_status="complete", reviews=reviews
        )
        result = select_reviews(pool)
        known = {r.identity_key for r in reviews}
        self.assertTrue(all(item.identity_key in known for item in result.selected))


def _scored(key: str, score: float | None, platform: str = "pc") -> ReviewRecord:
    return ReviewRecord(
        identity_key=key,
        platform_slug=platform,
        page_offset=0,
        language="en",
        score=score,
        text=f"Review {key}.",
        meaningful=True,
    )


class SentimentCoverageTests(SimpleTestCase):
    def _select(self, audience: str, reviews: list[ReviewRecord]) -> list[str]:
        pool = SelectionPool(
            audience=audience, game_slug="g", collection_status="complete", reviews=tuple(reviews)
        )
        return [item.identity_key for item in select_reviews(pool).selected]

    def test_a_skewed_pool_still_reserves_three_of_each_side(self) -> None:
        reviews = [_scored(f"pos-{i:02d}", 9) for i in range(36)]
        reviews += [_scored(f"neg-{i}", 2) for i in range(4)]

        selected = self._select("user", reviews)

        self.assertEqual(len(selected), 10)
        self.assertGreaterEqual(sum(key.startswith("neg-") for key in selected), 3)
        self.assertGreaterEqual(sum(key.startswith("pos-") for key in selected), 3)

    def test_fewer_reviews_than_the_minimum_are_all_taken(self) -> None:
        reviews = [_scored(f"pos-{i:02d}", 9) for i in range(20)] + [_scored("neg-0", 1)]

        selected = self._select("user", reviews)

        self.assertIn("neg-0", selected)
        self.assertEqual(len(selected), 10)

    def test_critic_scores_use_a_hundred_point_scale(self) -> None:
        reviews = [_scored(f"pos-{i:02d}", 90) for i in range(20)] + [
            _scored(f"neg-{i}", 30) for i in range(3)
        ]

        selected = self._select("critic", reviews)

        self.assertEqual(sum(key.startswith("neg-") for key in selected), 3)

    def test_unscored_reviews_are_neither_side_and_selection_still_fills_ten(self) -> None:
        reviews = [_scored(f"none-{i:02d}", None) for i in range(20)]

        self.assertEqual(len(self._select("user", reviews)), 10)

    def test_selection_is_independent_of_review_text(self) -> None:
        reviews = [_scored(f"pos-{i:02d}", 9) for i in range(30)] + [_scored("neg-0", 1)]
        edited = [replace(r, text="completely different words") for r in reviews]

        self.assertEqual(self._select("user", reviews), self._select("user", edited))
