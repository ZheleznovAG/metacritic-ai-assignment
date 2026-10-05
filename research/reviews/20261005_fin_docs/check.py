"""FIN-DOCS independent source/document audit; no runtime or acceptance claims."""

import ast
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[3]
BASELINE = "3270226"
DOCUMENTS = [
    "README.md", "PROJECT_STATUS.md", "action_plan.md", "methodology.md",
    "docs/design.md", "docs/bonus2_design.md", "docs/risks.md", "docs/evidence.md",
    "docs/development.md", "docs/history/operations.md",
    "docs/history/readme-20261005.md", "docs/learning_map.md",
    "docs/requirements/assumptions.md", "docs/requirements/imp_06_review.md",
    "docs/requirements/fin_docs_review.md",
    "deploy/README.md", "deploy/relocation_runbook.md",
]
POLICIES = {
    "app/reviews/selection.py": {"POLICY_VERSION": "1.2.0-meaningful"},
    "app/similarity/contract.py": {"POLICY_ID": "text-hybrid", "POLICY_VERSION": "3.0.0"},
    "app/summaries/contour.py": {
        "REQUESTED_MODEL": "openai/gpt-oss-20b", "PROMPT_VERSION": "3.0.0",
        "SCHEMA_VERSION": "2.1.0",
    },
    "app/letsplays/selection.py": {"POLICY_VERSION": "1.0.0"},
    "app/letsplays/conclusion.py": {
        "REQUESTED_MODEL": "openai/gpt-oss-120b", "PROMPT_VERSION": "2.1.0",
        "VALIDATION_VERSION": "2.1.0", "SCHEMA_VERSION": "2.0.0",
    },
}


def local_target(document, link):
    target = urlsplit(link)
    if target.scheme or not target.path:
        return None
    return (document.parent / unquote(target.path)).resolve()


def constants(source):
    values = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value.value
    return values


def unique_ids(ids):
    return len(ids) == len(set(ids))


def main():
    errors = []
    documents = DOCUMENTS + [str(p.relative_to(ROOT)).replace("\\", "/")
                             for p in sorted((ROOT / "docs/decisions").glob("*.md"))]
    links = 0
    for name in documents:
        p = ROOT / name
        source = p.read_text(encoding="utf-8-sig")
        source = re.sub(r"```.*?```", "", source, flags=re.S)
        for match in re.finditer(r"\[[^\]\n]*\]\(([^\s)]+)\)", source):
            target = local_target(p, match[1])
            if target is not None:
                links += 1
                if not target.exists():
                    errors.append(f"{name}: missing {match[1]}")
    ids = [re.search(r"^# (ADR-\d+):", p.read_text(encoding="utf-8"))[1]
           for p in sorted((ROOT / "docs/decisions").glob("*.md"))]
    if not unique_ids(ids):
        errors.append("Duplicate ADR IDs")
    snapshot = (ROOT / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    for name, expected in POLICIES.items():
        actual = constants((ROOT / name).read_text(encoding="utf-8"))
        for key, value in expected.items():
            if actual.get(key) != value or value not in snapshot:
                errors.append(f"Policy mismatch: {name} {key}")
    changed = subprocess.check_output(
        ["git", "diff", BASELINE, "--name-only", "--", "app", "evals"],
        cwd=ROOT, text=True,
    ).splitlines()
    if changed:
        errors.append(f"Application/frozen evaluation changed: {changed}")
    # Negative controls: missing paths, duplicated identities and source mismatches
    # must be distinguishable from valid references/identities/constant bindings.
    assert not local_target(ROOT / "README.md", "missing-fin-docs-control.md").exists()
    assert local_target(ROOT / "README.md", "https://example.invalid/a") is None
    assert not unique_ids(["ADR-0002", "ADR-0002"])
    assert unique_ids(["ADR-0002", "ADR-0007"])
    assert constants('POLICY_VERSION = "wrong"')["POLICY_VERSION"] != "3.0.0"
    result = {"baseline": BASELINE, "documents": len(documents), "local_links": links,
              "adr_ids": ids, "policy_bindings": sum(map(len, POLICIES.values())),
              "application_and_frozen_evals_unchanged": not changed,
              "negative_controls": 5, "errors": errors,
              "limits": "Local link paths only; fragments, remote URLs and prose semantics require review."}
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(errors))


if __name__ == "__main__":
    main()
