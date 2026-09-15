from catalog.models import Game, GamePlatform
from django.test import TestCase


class GameDetailViewTests(TestCase):
    def test_full_game_renders_all_data_fields(self) -> None:
        game = Game.objects.create(
            source="metacritic",
            source_game_id="1300501979",
            canonical_locator="/game/elden-ring/",
            title="Elden Ring",
            cover_url="https://example.invalid/cover.jpg",
            developer="From Software",
            description="A fantasy action-RPG.",
            video_embed_url="https://example.invalid/embed",
        )
        GamePlatform.objects.create(
            game=game,
            source="metacritic",
            source_platform_id="p1",
            source_game_platform_id="r1",
            slug="pc",
            name="PC",
            metascore=94,
            userscore="7.6",
        )

        response = self.client.get(f"/games/{game.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Elden Ring")
        self.assertContains(response, "From Software")
        self.assertContains(response, "A fantasy action-RPG.")
        self.assertContains(response, "PC")
        self.assertContains(response, "94")
        self.assertContains(response, "7.6")
        self.assertNotContains(response, "No data")

    def test_missing_optional_fields_show_an_explicit_no_data_state(self) -> None:
        game = Game.objects.create(
            source="metacritic",
            source_game_id="1",
            canonical_locator="/game/incomplete/",
            title="Incomplete Game",
        )
        GamePlatform.objects.create(
            game=game,
            source="metacritic",
            source_platform_id="p1",
            source_game_platform_id="r1",
            slug="pc",
            name="PC",
            metascore=75,
            userscore="6.0",
        )

        response = self.client.get(f"/games/{game.id}/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertEqual(content.count("No data"), 3)  # developer, description, trailer

    def test_unknown_game_id_is_404(self) -> None:
        response = self.client.get("/games/999999/")
        self.assertEqual(response.status_code, 404)

    def test_mutating_verbs_are_rejected(self) -> None:
        game = Game.objects.create(
            source="metacritic", source_game_id="1", canonical_locator="/game/a/", title="A"
        )
        self.assertEqual(self.client.post(f"/games/{game.id}/").status_code, 405)

    def test_untrusted_source_text_is_escaped_not_rendered_as_html(self) -> None:
        """HRD-05: title/developer/description are untrusted source text (never sanitised or
        stripped -- ASM/design.md preserve source text verbatim), so the template's own default
        auto-escaping is the only defense. `grep -rn '|safe\\|mark_safe' app/presentation` finds
        zero uses anywhere in this app, so this one concrete payload through the template exercises
        the same, only, mechanism every other rendered field (claim text, genres, platform names)
        also relies on."""
        payload = "<script>alert(1)</script>"
        game = Game.objects.create(
            source="metacritic",
            source_game_id="2",
            canonical_locator="/game/b/",
            title=f"Evil Game {payload}",
            developer=payload,
            description=payload,
        )
        GamePlatform.objects.create(
            game=game,
            source="metacritic",
            source_platform_id="p1",
            source_game_platform_id="r1",
            slug="pc",
            name="PC",
        )

        response = self.client.get(f"/games/{game.id}/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(payload, content)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", content)
