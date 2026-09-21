# Real-catalogue text comparison (2026-09-21)

Extension of [`metric.md`](metric.md), which stays frozen. The synthetic oracle judges genre
metadata and cannot judge text methods, so this extension grades real queries:
[`text_labels.json`](text_labels.json) (11 queries, 83 graded candidates), scored by
[`score_text.py`](score_text.py) with nDCG@5 (same gain and discount as `metric.md`), precision and
result counts; [`text_report.json`](text_report.json) records the run and
[`test_score_text.py`](test_score_text.py) checks the metric, the scorer wiring and the report's
integrity offline.

Reproduce with a snapshot exported from the catalogue (third-party text, kept outside Git):

```powershell
docker exec <db> psql -U metacritic -d metacritic -Atc "select json_agg(json_build_object('source_game_id',source_game_id,'title',title,'genres',genres,'description',description) order by id) from catalog_game" > snapshot.json
$env:PYTHONPATH = "app"
.\.venv-app\Scripts\python.exe evals/similarity/score_text.py --snapshot snapshot.json
```

The absolute numbers depend on the snapshot; the report stores its SHA-256. Limits (single
non-blind grader, 11 queries, post-hoc floor) are in
[ADR-0003](../../docs/decisions/0003-text-hybrid-similarity.md).
