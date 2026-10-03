"""Let's plays per game: the durable job, what was heard, the conclusion and provider usage.

Rows are only inserted and updated (the worker role has no DELETE). The web role reads them.
"""

from django.db import models


class LetsPlay(models.Model):
    """One per game: its search, listens and the chosen video, advanced one step per worker tick.

    `searching` -> `listening` (up to three candidates) -> `concluding` -> `done`; `not_found`
    when no candidate qualifies; `failed` after repeated errors. `available_at` defers a step for
    back-off or provider capacity; `refresh_at` schedules the next search.
    """

    STATE_CHOICES = [
        ("searching", "searching"),
        ("listening", "listening"),
        ("concluding", "concluding"),
        ("done", "done"),
        ("not_found", "not_found"),
        ("failed", "failed"),
    ]

    game = models.OneToOneField("catalog.Game", on_delete=models.PROTECT, related_name="letsplay")
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default="searching")
    policy_version = models.CharField(max_length=16)
    available_at = models.DateTimeField(null=True, blank=True)
    refresh_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    searched_at = models.DateTimeField(null=True, blank=True)
    # The policy's shortlist after the search: public metadata, most viewed first.
    shortlist = models.JSONField(default=list, blank=True)
    # One entry per listen: video id, decision, words per minute, text source.
    checks = models.JSONField(default=list, blank=True)

    video_id = models.CharField(max_length=16, null=True, blank=True)
    video_title = models.CharField(max_length=200, null=True, blank=True)
    channel = models.CharField(max_length=120, null=True, blank=True)
    views = models.PositiveBigIntegerField(null=True, blank=True)
    seconds = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["state", "available_at"], name="letsplay_due")]

    def __str__(self) -> str:
        return f"let's play for game {self.game_id}: {self.state}"


class LetsPlayTranscript(models.Model):
    """The text heard from the chosen video, tied to its id (AC-YT-03)."""

    SOURCE_CHOICES = [("captions", "captions"), ("whisper", "whisper")]

    letsplay = models.ForeignKey(LetsPlay, on_delete=models.PROTECT, related_name="transcripts")
    video_id = models.CharField(max_length=16)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES)
    language = models.CharField(max_length=32, null=True, blank=True)
    seconds_covered = models.FloatField()
    text = models.TextField()
    text_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField()

    def __str__(self) -> str:
        return f"{self.source} transcript of {self.video_id}"


class LetsPlayConclusion(models.Model):
    STATUS_CHOICES = [("sufficient", "sufficient"), ("insufficient", "insufficient")]

    letsplay = models.ForeignKey(LetsPlay, on_delete=models.PROTECT, related_name="conclusions")
    transcript = models.ForeignKey(
        LetsPlayTranscript, on_delete=models.PROTECT, related_name="conclusions"
    )
    contour_fingerprint = models.CharField(max_length=64)
    contour_versions = models.JSONField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    verdict = models.CharField(max_length=300, blank=True)
    sponsored = models.BooleanField(default=False)
    # [{"polarity": "like"|"dislike", "point", "segment", "quote"}] in output order; the quote is
    # the cited transcript segment, never text written by the model.
    opinions = models.JSONField(default=list, blank=True)
    returned_model = models.CharField(max_length=64, null=True, blank=True)
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    generated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "contour_fingerprint"],
                name="uq_letsplay_conclusion_transcript_contour",
            )
        ]

    def __str__(self) -> str:
        return f"conclusion for {self.transcript_id}: {self.status}"


class ProviderCall(models.Model):
    """Every external call the let's-play contour makes, in the provider's own units.

    Admission reads this ledger before each call: YouTube API units per day, caption reads per
    two minutes and per day, Whisper requests and audio seconds per hour and day, chat tokens per
    minute and day (`evals/letsplays/metric.md`). A provider refusal is stored with its headers.
    """

    KIND_CHOICES = [
        ("youtube_api", "youtube_api"),
        ("captions", "captions"),
        ("audio", "audio"),
        ("whisper", "whisper"),
        ("chat", "chat"),
    ]

    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    letsplay = models.ForeignKey(
        LetsPlay, on_delete=models.PROTECT, related_name="calls", null=True, blank=True
    )
    video_id = models.CharField(max_length=16, null=True, blank=True)
    # Reserved before the call: API units, audio seconds or request tokens.
    units = models.PositiveIntegerField(default=0)
    # Measured after the call when the provider reports it.
    actual_units = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=24, null=True, blank=True)
    error_code = models.CharField(max_length=64, null=True, blank=True)
    headers = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["kind", "started_at"], name="provider_call_window")]

    def __str__(self) -> str:
        return f"{self.kind} at {self.started_at:%Y-%m-%d %H:%M}: {self.outcome}"
