"""UI-OPT-02 / AC-UI-01–06, AC-SIM-03: bounded reads, honest labels and GET state."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from bs4 import BeautifulSoup
from catalog.models import Game, GameNeighbors, GamePlatform
from catalog.queries import get_game_detail, paginate_games
from django.test import TestCase
from presentation.templatetags.presentation_tags import process_label, relative_time
from similarity import text as policy


def game(n: int) -> Game:
    return Game.objects.create(
        source_game_id=f"polish-{n}", canonical_locator=f"/game/polish-{n}/", title=f"Polish {n}"
    )


def platform(item: Game, name: str, score: int, user: Decimal) -> None:
    GamePlatform.objects.create(
        game=item,
        source_platform_id=f"{item.id}-{name}",
        source_game_platform_id=f"polish-{item.id}-{name}",
        slug=name.lower(),
        name=name,
        metascore=score,
        userscore=user,
    )


class PresentationPolishTests(TestCase):
    def test_platform_labels_are_batched_for_the_current_page(self) -> None:
        first = game(0)
        platform(first, "PC", 90, Decimal("8.1"))
        platform(first, "PS5", 95, Decimal("7.9"))
        with self.assertNumQueries(3):
            small = paginate_games()
        for n in range(1, 61):
            other = game(n)
            platform(other, "PC", 80, Decimal("7.0"))
        with self.assertNumQueries(3):
            large = paginate_games(platform="pc")
        self.assertEqual(small.items[0].platforms, ("PC", "PS5"))
        self.assertEqual(large.items[0].platforms, ("PC", "PS5"))
        self.assertEqual(large.items[0].metascore, 90)
        self.assertEqual(len(large.items), 30)

    def test_filter_removal_preserves_other_filters_sort_and_resets_page(self) -> None:
        first = game(0)
        platform(first, "PC", 90, Decimal("8.1"))
        response = self.client.get(
            "/", {"q": "Polish", "platform": "pc", "sort": "release", "page": "2"}
        )
        soup = BeautifulSoup(response.content, "html.parser")
        links = soup.select(".filter-chips a")
        self.assertEqual(
            [a["href"] for a in links], ["?platform=pc&sort=release", "?q=Polish&sort=release"]
        )
        for link in links:
            self.assertEqual(self.client.get(str(link["href"])).status_code, 200)

    def test_search_chip_escapes_source_text(self) -> None:
        payload = "<script>bad()</script>"
        response = self.client.get("/", {"q": payload})
        self.assertNotContains(response, payload)
        self.assertContains(response, "&lt;script&gt;bad()&lt;/script&gt;")

    def test_hero_maxima_are_labelled_and_zero_is_a_real_score(self) -> None:
        first = game(0)
        platform(first, "PC", 0, Decimal("0.0"))
        detail = get_game_detail(first.pk)
        assert detail is not None
        self.assertEqual((detail.metascore, detail.userscore), (0, Decimal("0.0")))
        response = self.client.get(f"/games/{first.pk}/")
        soup = BeautifulSoup(response.content, "html.parser")
        badge = soup.select_one(".score-badge")
        assert badge is not None
        self.assertEqual(badge.get_text(), "0")
        self.assertContains(response, "Highest saved scores across platforms")
        self.assertContains(response, "Experimental Let's Play analysis")

    def test_similar_card_reads_saved_cover_and_score_without_per_game_queries(self) -> None:
        first, peer = game(0), game(1)
        peer.cover_url = "https://example.invalid/peer.jpg"
        peer.save()
        platform(peer, "PC", 82, Decimal("7.5"))
        GameNeighbors.objects.create(
            game=first,
            policy_version=policy.POLICY_VERSION,
            computed_at=datetime.now(UTC),
            neighbors=[{"id": peer.pk, "score": 6.5123456789}],
        )
        from catalog.queries import list_similar_games

        with self.assertNumQueries(2):
            result = list_similar_games(first.pk)
        self.assertEqual((result[0].cover_url, result[0].metascore), (peer.cover_url, 82))
        response = self.client.get(f"/games/{first.pk}/?page=3")
        self.assertContains(response, 'loading="lazy"')
        self.assertContains(response, f"/games/{peer.pk}/?page=3")
        self.assertNotContains(response, "6.5123456789")


class ObservationLabelsTests(TestCase):
    def test_relative_time_handles_boundaries_missing_and_future_without_claiming_freshness(
        self,
    ) -> None:
        now = datetime(2026, 10, 5, 12, tzinfo=UTC)
        with patch("presentation.templatetags.presentation_tags.timezone.now", return_value=now):
            self.assertEqual(relative_time(None), "Not recorded")
            self.assertEqual(relative_time("not-a-date"), "Not recorded")
            self.assertEqual(relative_time("2026-99-01T12:00:00Z"), "Not recorded")
            self.assertEqual(relative_time(now.replace(tzinfo=None)), "Not recorded")
            self.assertEqual(relative_time(now - timedelta(seconds=59)), "Just now")
            self.assertEqual(relative_time(now - timedelta(seconds=60)), "1 min ago")
            self.assertEqual(relative_time(now - timedelta(hours=1)), "1 h ago")
            self.assertEqual(relative_time(now - timedelta(days=1)), "1 d ago")
            self.assertEqual(relative_time(now + timedelta(minutes=1)), "In the future")
        self.assertEqual(process_label("busy"), "Working")
        self.assertEqual(process_label("unknown"), "Unknown")
