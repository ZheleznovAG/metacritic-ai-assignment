"""Identity, provenance and non-destructive upsert per `research/feasibility/game-identity.md`.

Field scope matches what IMP-02 actually populates (one game, its platforms, and the fetches
that produced them); `docs/design.md`'s fuller `source_fetch` schema (run/job ownership,
pagination) is added when `processing_run`/review generations exist in IMP-03/IMP-04.
"""

from django.db import models

SOURCE_CHOICES = [("metacritic", "metacritic")]


class SourceFetch(models.Model):
    KIND_CHOICES = [
        ("game_detail", "game_detail"),
        ("platform_userscore", "platform_userscore"),
    ]
    OUTCOME_CHOICES = [
        ("succeeded", "succeeded"),
        ("failed", "failed"),
        ("invalid", "invalid"),
    ]

    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    url = models.TextField()
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_sha256 = models.CharField(max_length=64, null=True, blank=True)
    parser_contract_version = models.CharField(max_length=32)
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES)
    error_code = models.CharField(max_length=64, null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.kind}:{self.outcome} @ {self.started_at:%Y-%m-%dT%H:%M:%SZ}"


class Game(models.Model):
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES, default="metacritic")
    source_game_id = models.CharField(max_length=64)
    canonical_locator = models.CharField(max_length=512)
    title = models.CharField(max_length=255)
    cover_url = models.TextField(null=True, blank=True)
    developer = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    video_embed_url = models.TextField(null=True, blank=True)
    video_content_url = models.TextField(null=True, blank=True)
    last_changed_fetch = models.ForeignKey(
        SourceFetch, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_game_id"], name="uq_game_source_source_game_id"
            )
        ]

    def __str__(self) -> str:
        return self.title


class GameAlias(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="aliases")
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES, default="metacritic")
    locator = models.CharField(max_length=512)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "locator"], name="uq_game_alias_source_locator"
            )
        ]

    def __str__(self) -> str:
        return self.locator


class GamePlatform(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="platforms")
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES, default="metacritic")
    source_platform_id = models.CharField(max_length=64)
    source_game_platform_id = models.CharField(max_length=64)
    slug = models.CharField(max_length=128)
    name = models.CharField(max_length=128)
    metascore = models.PositiveSmallIntegerField(null=True, blank=True)
    userscore = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    critic_reviews_path = models.CharField(max_length=512, null=True, blank=True)
    user_reviews_path = models.CharField(max_length=512, null=True, blank=True)
    last_changed_fetch = models.ForeignKey(
        SourceFetch, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["game", "source_platform_id"], name="uq_game_platform_game_source_platform"
            ),
            models.UniqueConstraint(
                fields=["source", "source_game_platform_id"],
                name="uq_game_platform_source_related_id",
            ),
            models.CheckConstraint(
                condition=models.Q(metascore__isnull=True)
                | (models.Q(metascore__gte=0) & models.Q(metascore__lte=100)),
                name="ck_game_platform_metascore_range",
            ),
            models.CheckConstraint(
                condition=models.Q(userscore__isnull=True)
                | (models.Q(userscore__gte=0) & models.Q(userscore__lte=10)),
                name="ck_game_platform_userscore_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.game_id})"
