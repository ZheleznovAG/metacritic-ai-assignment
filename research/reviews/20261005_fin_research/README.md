# FIN-RESEARCH: offline freeze and replay evidence

The [research contract](../../../docs/research_freeze.md) freezes existing methods
under ADR-0004/0006's accepted limitations. No new method, paid call or independent
holdout is introduced. The original reports/labels are preserved byte-for-byte.

## Freeze and negative controls

```powershell
.\.venv-app\Scripts\python.exe -B research/reviews/20261005_fin_research/verify.py
.\.venv-app\Scripts\python.exe -B -m unittest discover -s research/reviews/20261005_fin_research -p "test_*.py"
```

The verifier checks the manifest's source hashes and closed file membership, complete
case sets and published scores. It keeps the similarity regression and conclusion
quality failure explicit. It does not independently regrade semantics or verify model
cache files; those are separately hashed from the replay image. Negative controls
cover altered/missing/new files, path escape, fake holdout claims and omitted cases.

## Container evaluator integrity

Build images with README's canonical command first. Tests use fake embeddings and
saved public labels, without database or network:

```powershell
docker run --rm --pull never --network none --no-healthcheck --read-only --tmpfs /tmp:size=64m -e PYTHONPATH=/opt/app/app metacritic-imp01-checks:local python -B -m unittest discover -s evals/similarity -p "test_*.py"
docker run --rm --pull never --network none --no-healthcheck --read-only --tmpfs /tmp:size=64m -e PYTHONPATH=/opt/app/app metacritic-imp01-checks:local python -B -m unittest discover -s evals/letsplays -p "test_*.py"
```

## Original-input replay

Raw inputs stay outside Git. Snapshot SHA-256 must match the original report before
the real-model comparison is meaningful. Do not use `--write` against frozen reports.
The model and runtime are baked into the local image; network is disabled.

```powershell
$repoRoot = (Get-Location).Path
docker run --rm --pull never --network none --no-healthcheck --read-only --cap-drop ALL --security-opt no-new-privileges --memory 768m --cpus 2 --tmpfs /tmp:size=64m -e APP_ENV=production -e PYTHONPATH=/opt/app/app --mount "type=bind,source=$repoRoot/evals/similarity,target=/opt/app/evals/similarity,readonly" --mount "type=bind,source=$repoRoot/.artifacts/sim-v2/snapshot.json,target=/snapshot.json,readonly" metacritic-imp01:local python -B evals/similarity/score_text.py --snapshot /snapshot.json
docker run --rm --pull never --network none --no-healthcheck --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:size=64m --mount "type=bind,source=$repoRoot/research/reviews/20261005_fin_research,target=/opt/app/research/reviews/20261005_fin_research,readonly" --mount "type=bind,source=$repoRoot/.artifacts/ytp02,target=/opt/app/.artifacts/ytp02,readonly" metacritic-imp01-checks:local python -B research/reviews/20261005_fin_research/replay_letsplays.py
```

The second command validates saved speech/transcript hashes, replays selection twice,
checks contour fingerprint, token reservations, structural validation and exact quote
materialization on saved provider outputs. It calls no provider and prints no raw text.
It does not regenerate provider outputs or certify correct opinion attribution.

Evidence: [freeze](../../../docs/evidence/fin-research/freeze.json),
[audit](../../../docs/evidence/fin-research/audit.json),
[similarity replay/drift](../../../docs/evidence/fin-research/similarity_replay.json),
[Let's Play replay](../../../docs/evidence/fin-research/letsplays_replay.json).
Review/acceptance boundary: [FIN-RESEARCH review](../../../docs/requirements/fin_research_review.md).
