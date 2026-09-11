from datetime import UTC, datetime
from decimal import Decimal
from unittest import mock

from catalog.ingest import ingest_game
from catalog.models import Game, GameAlias, GamePlatform, SourceFetch
from django.test import TestCase
from metacritic.dto import BrowsePage, FetchEvidence, GameDTO, GameIdentityDTO, GamePlatformDTO
from processing.models import DailyCandidate
from reviews.models import ReviewCollectionJob

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
DETAIL_URL = "https://www.metacritic.com/game/elden-ring/"


class FakeClock:
    def now_utc(self) -> datetime:
        return NOW


def _evidence(
    outcome: str = "succeeded", error_code: str | None = None, kind: str = "game_detail"
) -> FetchEvidence:
    return FetchEvidence(
        kind=kind,
        url=DETAIL_URL,
        started_at=NOW,
        completed_at=NOW,
        http_status=200 if outcome == "succeeded" else None,
        response_sha256="a" * 64 if outcome == "succeeded" else None,
        parser_contract_version="1.0.0",
        outcome=outcome,
        error_code=error_code,
    )


def _platform(
    source_platform_id: str = "p1",
    source_game_platform_id: str = "r1",
    slug: str = "pc",
    name: str = "PC",
    metascore: int | None = 94,
    userscore: Decimal | None = Decimal("7.6"),
    critic_path: str | None = "/game/elden-ring/critic-reviews/?platform=pc",
    user_path: str | None = "/game/elden-ring/user-reviews/?platform=pc",
) -> GamePlatformDTO:
    return GamePlatformDTO(
        source_platform_id=source_platform_id,
        source_game_platform_id=source_game_platform_id,
        slug=slug,
        name=name,
        is_lead_platform=True,
        metascore=metascore,
        userscore=userscore,
        critic_reviews_path=critic_path,
        user_reviews_path=user_path,
    )


def _game(
    source_game_id: str = "1300501979",
    canonical_locator: str = "/game/elden-ring/",
    title: str = "Elden Ring",
    platforms: tuple[GamePlatformDTO, ...] | None = None,
) -> GameDTO:
    return GameDTO(
        source_game_id=source_game_id,
        canonical_locator=canonical_locator,
        title=title,
        cover_url="https://example.invalid/cover.jpg",
        developer="From Software",
        description="A fantasy action-RPG.",
        video_embed_url="https://example.invalid/embed",
        video_content_url="https://example.invalid/content",
        platforms=platforms if platforms is not None else (_platform(),),
    )


class FakeGateway:
    def __init__(
        self,
        game_dto: GameDTO | None,
        evidence: FetchEvidence | None = None,
        platform_userscores: dict[str, Decimal | None] | None = None,
        platform_userscore_failures: set[str] | None = None,
    ) -> None:
        self._game_result = (game_dto, evidence or _evidence())
        self._platform_userscores = platform_userscores or {}
        self._platform_userscore_failures = platform_userscore_failures or set()

    def fetch_game(self, url: str) -> tuple[GameDTO | None, FetchEvidence]:
        return self._game_result

    def fetch_platform_userscore(self, url: str) -> tuple[Decimal | None, FetchEvidence]:
        if url in self._platform_userscore_failures:
            return None, _evidence(
                outcome="failed", error_code="http_503", kind="platform_userscore"
            )
        return self._platform_userscores[url], _evidence(kind="platform_userscore")

    def list_new_releases(self) -> tuple[list[GameIdentityDTO] | None, FetchEvidence]:
        raise NotImplementedError("not used by catalog.ingest tests")

    def iter_browse(self, page: int) -> tuple[BrowsePage | None, FetchEvidence]:
        raise NotImplementedError("not used by catalog.ingest tests")


class IngestCreateTests(TestCase):
    def test_creates_game_platforms_candidate_and_jobs(self) -> None:
        gateway = FakeGateway(_game())
        result = ingest_game(gateway, FakeClock(), DETAIL_URL)

        self.assertTrue(result.ok)
        self.assertTrue(result.game_created)
        self.assertEqual(result.platforms_created, 1)
        self.assertEqual(result.jobs_created, 2)  # critic + user for the one platform
        self.assertEqual(result.candidate_state, "processed")

        assert result.game_id is not None
        game = Game.objects.get(pk=result.game_id)
        self.assertEqual(game.source_game_id, "1300501979")
        self.assertEqual(GameAlias.objects.filter(game=game).count(), 1)
        self.assertEqual(GamePlatform.objects.filter(game=game).count(), 1)
        self.assertEqual(DailyCandidate.objects.filter(game=game).count(), 1)
        self.assertEqual(ReviewCollectionJob.objects.count(), 2)
        self.assertEqual(SourceFetch.objects.filter(outcome="succeeded").count(), 1)

    def test_failed_fetch_creates_no_domain_rows(self) -> None:
        gateway = FakeGateway(None, evidence=_evidence(outcome="invalid", error_code="boom"))
        result = ingest_game(gateway, FakeClock(), DETAIL_URL)

        self.assertFalse(result.ok)
        self.assertEqual(Game.objects.count(), 0)
        self.assertEqual(SourceFetch.objects.filter(outcome="invalid").count(), 1)


class IngestUpdateTests(TestCase):
    def test_repeat_ingest_of_the_same_identity_updates_not_duplicates(self) -> None:
        gateway = FakeGateway(_game())
        first = ingest_game(gateway, FakeClock(), DETAIL_URL)
        second = ingest_game(gateway, FakeClock(), DETAIL_URL)

        self.assertTrue(first.ok and second.ok)
        self.assertFalse(second.game_created)
        self.assertEqual(second.platforms_created, 0)
        self.assertEqual(second.platforms_updated, 1)
        self.assertEqual(Game.objects.count(), 1)
        self.assertEqual(GamePlatform.objects.count(), 1)

    def test_title_change_updates_the_existing_game(self) -> None:
        gateway_a = FakeGateway(_game(title="Elden Ring"))
        ingest_game(gateway_a, FakeClock(), DETAIL_URL)
        gateway_b = FakeGateway(_game(title="Elden Ring: Renamed"))
        ingest_game(gateway_b, FakeClock(), DETAIL_URL)

        self.assertEqual(Game.objects.count(), 1)
        self.assertEqual(Game.objects.get().title, "Elden Ring: Renamed")

    def test_new_locator_becomes_alias_old_locator_retained(self) -> None:
        gateway_a = FakeGateway(_game(canonical_locator="/game/elden-ring/"))
        ingest_game(gateway_a, FakeClock(), DETAIL_URL)
        gateway_b = FakeGateway(_game(canonical_locator="/game/elden-ring-new-slug/"))
        ingest_game(gateway_b, FakeClock(), DETAIL_URL)

        game = Game.objects.get()
        self.assertEqual(game.canonical_locator, "/game/elden-ring-new-slug/")
        locators = set(GameAlias.objects.filter(game=game).values_list("locator", flat=True))
        self.assertEqual(locators, {"/game/elden-ring/", "/game/elden-ring-new-slug/"})

    def test_locator_collision_with_a_different_identity_is_an_identity_conflict(self) -> None:
        gateway_a = FakeGateway(_game(source_game_id="1", canonical_locator="/game/shared/"))
        first = ingest_game(gateway_a, FakeClock(), DETAIL_URL)
        gateway_b = FakeGateway(_game(source_game_id="2", canonical_locator="/game/shared/"))
        second = ingest_game(gateway_b, FakeClock(), DETAIL_URL)

        self.assertTrue(first.ok)
        self.assertFalse(second.ok)
        self.assertEqual(Game.objects.count(), 1)

    def test_platform_missing_from_a_later_response_is_retained_not_deleted(self) -> None:
        two_platforms = (
            _platform(source_platform_id="p1", slug="pc"),
            _platform(source_platform_id="p2", slug="xbox", source_game_platform_id="r2"),
        )
        gateway_a = FakeGateway(_game(platforms=two_platforms))
        ingest_game(gateway_a, FakeClock(), DETAIL_URL)

        one_platform = (_platform(source_platform_id="p1", slug="pc"),)
        gateway_b = FakeGateway(_game(platforms=one_platform))
        ingest_game(gateway_b, FakeClock(), DETAIL_URL)

        self.assertEqual(GamePlatform.objects.count(), 2)

    def test_a_later_null_field_does_not_clobber_a_previously_known_value(self) -> None:
        gateway_a = FakeGateway(_game(platforms=(_platform(metascore=94),)))
        ingest_game(gateway_a, FakeClock(), DETAIL_URL)

        gateway_b = FakeGateway(_game(platforms=(_platform(metascore=None),)))
        ingest_game(gateway_b, FakeClock(), DETAIL_URL)

        self.assertEqual(GamePlatform.objects.get().metascore, 94)

    def test_an_unclaimed_new_platform_assertion_id_is_synced_on_update(self) -> None:
        gateway_a = FakeGateway(_game(platforms=(_platform(source_game_platform_id="r1"),)))
        ingest_game(gateway_a, FakeClock(), DETAIL_URL)

        gateway_b = FakeGateway(_game(platforms=(_platform(source_game_platform_id="r-new"),)))
        ingest_game(gateway_b, FakeClock(), DETAIL_URL)

        self.assertEqual(GamePlatform.objects.get().source_game_platform_id, "r-new")

    def test_a_later_blank_string_does_not_clobber_a_previously_known_value(self) -> None:
        gateway_a = FakeGateway(_game(title="Elden Ring", platforms=(_platform(),)))
        ingest_game(gateway_a, FakeClock(), DETAIL_URL)
        Game.objects.filter(source_game_id="1300501979").update(developer="From Software")

        blank_dto = GameDTO(
            source_game_id="1300501979",
            canonical_locator="/game/elden-ring/",
            title="Elden Ring",
            cover_url=None,
            developer="   ",
            description=None,
            video_embed_url=None,
            video_content_url=None,
            platforms=(_platform(),),
        )
        gateway_b = FakeGateway(blank_dto)
        ingest_game(gateway_b, FakeClock(), DETAIL_URL)

        self.assertEqual(Game.objects.get().developer, "From Software")


class IngestAtomicityTests(TestCase):
    def test_a_failure_creating_jobs_rolls_back_the_whole_transaction(self) -> None:
        gateway = FakeGateway(_game())
        with mock.patch("catalog.ingest.ensure_jobs", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                ingest_game(gateway, FakeClock(), DETAIL_URL)

        self.assertEqual(Game.objects.count(), 0)
        self.assertEqual(GamePlatform.objects.count(), 0)
        self.assertEqual(DailyCandidate.objects.count(), 0)

    def test_repeat_ingest_does_not_duplicate_jobs(self) -> None:
        gateway = FakeGateway(_game())
        ingest_game(gateway, FakeClock(), DETAIL_URL)
        result = ingest_game(gateway, FakeClock(), DETAIL_URL)

        self.assertEqual(result.jobs_created, 0)
        self.assertEqual(ReviewCollectionJob.objects.count(), 2)


class IngestPlatformUserscoreFanOutTests(TestCase):
    def test_non_lead_platform_userscore_comes_from_its_own_fetch(self) -> None:
        lead = _platform(
            source_platform_id="p1", slug="ps5", metascore=96, userscore=Decimal("8.4")
        )
        non_lead = GamePlatformDTO(
            source_platform_id="p2",
            source_game_platform_id="r2",
            slug="pc",
            name="PC",
            is_lead_platform=False,
            metascore=94,
            userscore=None,
            critic_reviews_path="/game/elden-ring/critic-reviews/?platform=pc",
            user_reviews_path="/game/elden-ring/user-reviews/?platform=pc",
        )
        gateway = FakeGateway(
            _game(platforms=(lead, non_lead)),
            platform_userscores={
                "https://www.metacritic.com/game/elden-ring/user-reviews/?platform=pc": Decimal(
                    "7.6"
                )
            },
        )
        ingest_game(gateway, FakeClock(), DETAIL_URL)

        pc = GamePlatform.objects.get(slug="pc")
        self.assertEqual(pc.userscore, Decimal("7.6"))

    def test_a_fanned_out_platforms_provenance_points_at_its_own_fetch(self) -> None:
        lead = _platform(source_platform_id="p1", slug="ps5")
        non_lead = GamePlatformDTO(
            source_platform_id="p2",
            source_game_platform_id="r2",
            slug="pc",
            name="PC",
            is_lead_platform=False,
            metascore=94,
            userscore=None,
            critic_reviews_path="/game/elden-ring/critic-reviews/?platform=pc",
            user_reviews_path="/game/elden-ring/user-reviews/?platform=pc",
        )
        gateway = FakeGateway(
            _game(platforms=(lead, non_lead)),
            platform_userscores={
                "https://www.metacritic.com/game/elden-ring/user-reviews/?platform=pc": Decimal(
                    "7.6"
                )
            },
        )
        ingest_game(gateway, FakeClock(), DETAIL_URL)

        game_detail_fetch = SourceFetch.objects.get(kind="game_detail")
        platform_fetch = SourceFetch.objects.get(kind="platform_userscore")
        ps5 = GamePlatform.objects.get(slug="ps5")
        pc = GamePlatform.objects.get(slug="pc")
        # Metascore always comes from the game_detail fetch, for every platform.
        self.assertEqual(ps5.metascore_last_changed_fetch_id, game_detail_fetch.id)
        self.assertEqual(pc.metascore_last_changed_fetch_id, game_detail_fetch.id)
        # Userscore comes from the game_detail fetch only for the lead platform; every other
        # platform's Userscore provenance points at its own platform_userscore fetch.
        self.assertEqual(ps5.userscore_last_changed_fetch_id, game_detail_fetch.id)
        self.assertEqual(pc.userscore_last_changed_fetch_id, platform_fetch.id)
        self.assertNotEqual(pc.userscore_last_changed_fetch_id, game_detail_fetch.id)

    def test_a_failed_userscore_fetch_does_not_claim_provenance_over_a_preserved_value(
        self,
    ) -> None:
        pc_url = "https://www.metacritic.com/game/elden-ring/user-reviews/?platform=pc"
        non_lead = GamePlatformDTO(
            source_platform_id="p2",
            source_game_platform_id="r2",
            slug="pc",
            name="PC",
            is_lead_platform=False,
            metascore=94,
            userscore=None,
            critic_reviews_path="/game/elden-ring/critic-reviews/?platform=pc",
            user_reviews_path="/game/elden-ring/user-reviews/?platform=pc",
        )
        gateway_a = FakeGateway(
            _game(platforms=(non_lead,)), platform_userscores={pc_url: Decimal("7.6")}
        )
        ingest_game(gateway_a, FakeClock(), DETAIL_URL)
        good_fetch = SourceFetch.objects.get(kind="platform_userscore")

        gateway_b = FakeGateway(_game(platforms=(non_lead,)), platform_userscore_failures={pc_url})
        ingest_game(gateway_b, FakeClock(), DETAIL_URL)

        pc = GamePlatform.objects.get(slug="pc")
        # The value is preserved by the non-destructive merge...
        self.assertEqual(pc.userscore, Decimal("7.6"))
        # ...and its provenance must still point at the fetch that actually produced it, not the
        # failed one that merely left it alone.
        self.assertEqual(pc.userscore_last_changed_fetch_id, good_fetch.id)
        failed_fetch = SourceFetch.objects.get(kind="platform_userscore", outcome="failed")
        self.assertNotEqual(pc.userscore_last_changed_fetch_id, failed_fetch.id)
