"""PLN-03: offline structural audit, not proof of product acceptance or velocity."""

import json
import math
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]
TASK_IDS = set("""
IN-01 FOR-01 FOR-02 FOR-03 FOR-04 FOR-05 RSK-01 RSK-02
SPK-01 SPK-02 SPK-03 SPK-04 SPK-05 SPK-06 PLN-01 PLN-02 PLN-03
IMP-01 IMP-02 IMP-03 REV-EVAL-01 IMP-04 IMP-05 SIM-EVAL-01 IMP-06
SIM-VER-01 IMP-07 HRD-01 HRD-02 HRD-03 HRD-04 HRD-05 HRD-06
PUB-01 PUB-02 PUB-03 BON-00 BON-11 BON-12 BON-21 BON-22
REL-01 REL-02 REL-03 REL-04 REL-05
""".split())  # Stable identifiers from baseline 0.18, commit 0c353ec.
GATES = set("G0 G1 G2 G3 G4 G5 G6 GB G7".split())
FUTURE = {task for task in TASK_IDS if task.startswith(
    ("IMP-", "REV-", "SIM-", "HRD-", "PUB-", "BON-", "REL-")
)}
ID = re.compile(r"\b(?:[A-Z]+(?:-[A-Z]+)*-\d{2}|G[0-7B])\b")
SOURCES = {
    "action": "action_plan.md",
    "implementation": "implementation_plan.md",
    "requirements": "docs/requirements/requirements.md",
    "acceptance": "docs/requirements/acceptance.md",
    "risks": "docs/risks.md",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def tables(document):
    return [tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
            for line in document.splitlines() if line.startswith("|")]


def key(cell):
    found = ID.search(cell)
    return found.group() if found else None


def unique(rows, label):
    result = {}
    for name, value in rows:
        require(name not in result, f"Duplicate {label}: {name}")
        result[name] = value
    return result


def read_sources(root=ROOT):
    return {name: (root / path).read_text(encoding="utf-8")
            for name, path in SOURCES.items()}


def check(documents, root=ROOT):
    nodes = unique(((key(row[0]), row[1:])
                    for row in tables(documents["action"])
                    if len(row) == 5 and key(row[0])), "node")
    require(set(nodes) == TASK_IDS | GATES, "Task/gate ID set changed")
    scope_rows = re.findall(r"^- Bonus scope: `([a-z0-9]+)`\.$",
                            documents["action"], re.MULTILINE)
    require(len(scope_rows) == 1, "One explicit Bonus scope is required")
    selected = scope_rows[0]
    scopes = {"pending": (), "none": (), "bonus1": ("bonus1",),
              "bonus2": ("bonus2",), "both": ("bonus1", "bonus2")}
    require(selected in scopes, "Unknown Bonus scope")
    require((selected != "pending") == (nodes["BON-00"][2] == "Verified"),
            "Bonus scope requires a verified BON-00 decision")
    current_scope = scopes[selected]
    hours_rows = unique(((key(row[0]), row[1:])
                         for row in tables(documents["implementation"])
                         if len(row) == 3 and row[0].startswith("[")), "estimate")
    require(set(hours_rows) == FUTURE, "Missing/extra future task estimate")
    headings = re.findall(r"^### ([A-Z][A-Z0-9-]+)$",
                          documents["implementation"], re.MULTILINE)
    require(len(headings) == len(set(headings)) and set(headings) == FUTURE,
            "Missing/duplicate future task description")
    require("**Статус:**" not in documents["implementation"]
            and not any("Статус" in cell for row in tables(
                documents["implementation"]) for cell in row),
            "Competing status field in implementation plan")
    hours = {}
    for task, (total, parts) in hours_rows.items():
        require(total.isdecimal() and int(total) > 0, f"Invalid estimate: {task}")
        hours[task] = int(total)
        require(sum(map(int, re.findall(r"— (\d+) ч", parts))) == int(total),
                f"Timebox parts do not sum: {task}")

    requirements = unique(((key(row[0]), "Must" in row[1])
                           for row in tables(documents["requirements"])
                           if key(row[0]) and len(row) > 2
                           and ("Must" in row[1] or "Bonus" in row[1])), "requirement")
    acceptance_rows = [row for row in tables(documents["acceptance"])
                       if row[0].startswith("`AC-")]
    accepted_ids = {item for row in acceptance_rows for item in ID.findall(row[1])}
    require(accepted_ids == set(requirements), "Acceptance/requirements ID mismatch")
    coverage = unique(((key(row[0]), row[1:])
                       for row in tables(documents["implementation"])
                       if len(row) == 3 and row[0].startswith("`")
                       and key(row[0])), "coverage")
    require(set(coverage) == set(requirements), "Requirement coverage mismatch")
    risk_ids = set(re.findall(r"^### `(R-[A-Z0-9-]+)`",
                              documents["risks"], re.MULTILINE))
    risk_coverage = unique(((key(row[0]), row[1])
                            for row in tables(documents["implementation"])
                            if len(row) == 2 and row[0].startswith("`R-")), "risk")
    require(set(risk_coverage) == risk_ids, "Risk coverage mismatch")
    for name, cells in coverage.items():
        for cell in cells:
            refs = set(ID.findall(cell))
            require(refs and refs <= nodes.keys(), f"Missing/unknown task for {name}")
            if requirements[name]:
                require(all(nodes[task][1] == "base" for task in refs),
                        f"Must requirement depends on Bonus: {name}")
    for name, cell in risk_coverage.items():
        refs = set(ID.findall(cell))
        require(refs and refs <= nodes.keys(), f"Missing/unknown risk task: {name}")
        if not name.startswith("R-BON-"):
            require(all(nodes[task][1] == "base" for task in refs),
                    f"Must risk depends on Bonus: {name}")

    dependencies = {}
    for node, (deps, branch, status, evidence) in nodes.items():
        require(branch in {"base", "bonus1", "bonus2"}, f"Unknown branch: {node}")
        require(status in {"Planned", "Ready", "In progress", "Changes requested",
                           "Verified", "Blocked", "Dropped"}, f"Unknown status: {node}")
        require(evidence, f"Missing evidence location: {node}")
        if status == "Dropped":
            require(branch != "base", f"Mandatory task cannot be Dropped: {node}")
            require(selected != "pending" and branch not in current_scope,
                    f"Dropped task is not excluded by accepted scope: {node}")
        if branch != "base":
            if selected == "pending":
                require(status == "Planned", f"Bonus started before scope decision: {node}")
            elif branch not in current_scope:
                require(status == "Dropped", f"Unselected Bonus must be Dropped: {node}")
        if status == "Verified":
            links = re.findall(r"\[[^\]\n]+\]\(([^)\s]+)\)", evidence)
            require("Ожидается:" not in evidence and links,
                    f"Verified has no actual artifact link: {node}")
            for link in links:
                target = urlsplit(link)
                if target.scheme in {"http", "https"}:
                    require(target.netloc, f"Invalid evidence URL: {node}")
                    continue  # External availability requires separate review.
                path = (root / unquote(target.path)).resolve()
                require(not target.scheme and path.is_relative_to(root.resolve())
                        and path.is_file(), f"Missing local evidence artifact: {node}: {link}")
        deps = [] if deps == "—" else [part.strip() for part in deps.split(",")]
        require(len(deps) == len(set(deps)), f"Duplicate dependency: {node}")
        for dep in deps:
            require(dep.rstrip("?") in nodes, f"Unknown dependency: {node}: {dep}")
            if dep.endswith("?"):
                require(node == "GB" and nodes[dep[:-1]][1] != "base",
                        f"Invalid conditional dependency: {node}: {dep}")
        dependencies[node] = deps

    scenarios = {}
    for scope in ((), ("bonus1",), ("bonus2",), ("bonus1", "bonus2")):
        active = {node for node, row in nodes.items() if row[1] in {"base", *scope}}
        graph = {}
        for node in active:
            graph[node] = []
            for dep in dependencies[node]:
                target = dep.rstrip("?")
                if dep.endswith("?") and target not in active:
                    continue
                require(target in active, f"Inactive mandatory dependency: {node}")
                graph[node].append(target)
        ancestors, lengths, paths, visiting = {}, {}, {}, set()

        def visit(node):
            if node in ancestors:
                return
            require(node not in visiting, f"Dependency cycle at {node}")
            visiting.add(node)
            for dep in graph[node]:
                visit(dep)
            ancestors[node] = set(graph[node]).union(
                *(ancestors[dep] for dep in graph[node]))
            longest = max(graph[node], key=lambda dep: lengths[dep], default=None)
            lengths[node] = hours.get(node, 0) + (lengths[longest] if longest else 0)
            paths[node] = (paths[longest] if longest else []) + (
                [node] if node in hours else [])
            visiting.remove(node)

        for node in sorted(active):
            visit(node)
        require(ancestors["G7"] | {"G7"} == active, "Work disconnected from G7")
        for node in active & FUTURE:
            stage = node.split("-")[0]
            gate = {"IMP": "G3", "REV": "G3", "SIM": "G3", "HRD": "G4",
                    "PUB": "G5", "BON": "G6", "REL": "GB"}[stage]
            require(gate in ancestors[node], f"Gate bypass: {node} requires {gate}")
        for node, prerequisites in {
            "IMP-04": {"IMP-03", "REV-EVAL-01"},
            "IMP-06": {"SIM-EVAL-01"},
            "SIM-VER-01": {"IMP-05", "IMP-06"},
            "REL-01": {"REL-02", "REL-03"},
            "G7": {"REL-05"},
        }.items():
            require(prerequisites <= ancestors[node], f"Required ordering missing: {node}")
        require(not any(node.startswith("REL-") for node in ancestors["G6"]),
                "G6 improperly requires completed delivery")
        if scope == current_scope:
            for node in active:
                if nodes[node][2] in {"Ready", "In progress", "Verified"}:
                    require(all(nodes[dep][2] == "Verified" for dep in graph[node]),
                            f"Unsatisfied prerequisite of {node}")
        scenarios["+".join(scope) or "none"] = {
            "work_hours": sum(hours.get(node, 0) for node in active),
            "dependency_hours": lengths["G7"],
            "longest_chain": paths["G7"],
        }
    base = scenarios["none"]["work_hours"]
    return {
        "task_ids": len(TASK_IDS), "gate_ids": len(GATES),
        "estimated_tasks": len(hours), "must_requirements": sum(requirements.values()),
        "bonus_requirements": len(requirements) - sum(requirements.values()),
        "acceptance_scenarios": len(acceptance_rows), "risks": len(risk_ids),
        "reserve_25_percent_hours": math.ceil(base * 0.25),
        "base_with_reserve_hours": base + math.ceil(base * 0.25),
        "early_public_slice_hours": hours["IMP-01"] + hours["IMP-02"],
        "selected_bonus_scope": selected,
        "scenarios": scenarios,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(check(read_sources()), indent=2))
    except ValueError as error:
        raise SystemExit(f"PLAN CHECK FAILED: {error}") from error
