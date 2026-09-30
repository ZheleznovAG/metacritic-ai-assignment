"""Bring saved summaries up to the current selection policy: `manage.py refresh_summaries`.

A new selection policy or summary contour otherwise reaches a game only when its reviews are
collected again, and older games are rarely re-collected, so their cards would keep a stale
summary indefinitely. For every corpus head built under an older selection policy this command
rebuilds the corpus from the reviews already saved for the game's latest complete collection (no
Metacritic request) and makes sure a summary job exists for the current contour. The worker then
generates the summaries as usual, paced by the free Groq quota (`summaries/quota.py`); the old
summary stays visible as stale until then.

A head whose latest collection is not complete is skipped: the normal collection path builds its
corpus when that collection finishes. Running the command again only enqueues what is missing.
"""

from dataclasses import dataclass
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from summaries.models import SummaryJob
from summaries.worker import ensure_job

from reviews import corpus as corpus_module
from reviews.models import ReviewCorpusHead
from reviews.selection import POLICY_VERSION


@dataclass
class RefreshCounts:
    heads: int = 0
    outdated: int = 0
    rebuilt: int = 0
    skipped_incomplete: int = 0
    jobs_created: int = 0


def refresh(*, dry_run: bool = False, limit: int | None = None) -> RefreshCounts:
    counts = RefreshCounts()
    heads = ReviewCorpusHead.objects.select_related("game", "corpus").order_by(
        "game_id", "audience"
    )
    for head in heads:
        counts.heads += 1
        if head.corpus.policy_version == POLICY_VERSION:
            current = head.corpus
        else:
            counts.outdated += 1
            if dry_run or (limit is not None and counts.rebuilt >= limit):
                continue
            rebuilt = corpus_module.build(head.game, head.audience)
            if rebuilt is None or rebuilt.policy_version != POLICY_VERSION:
                counts.skipped_incomplete += 1
                continue
            counts.rebuilt += 1
            current = rebuilt
        if dry_run:
            continue
        before = SummaryJob.objects.count()
        ensure_job(current)
        counts.jobs_created += SummaryJob.objects.count() - before
    return counts


class Command(BaseCommand):
    help = "Rebuild corpora made under an older selection policy and enqueue their summaries."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="count only, write nothing")
        parser.add_argument("--limit", type=int, help="rebuild at most this many corpora")

    def handle(self, *args: Any, **options: Any) -> None:
        counts = refresh(dry_run=options["dry_run"], limit=options["limit"])
        self.stdout.write(
            f"policy={POLICY_VERSION} heads={counts.heads} outdated={counts.outdated} "
            f"rebuilt={counts.rebuilt} skipped_incomplete={counts.skipped_incomplete} "
            f"jobs_created={counts.jobs_created} dry_run={options['dry_run']}"
        )
