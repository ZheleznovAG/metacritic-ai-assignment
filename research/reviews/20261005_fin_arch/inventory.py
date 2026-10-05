import ast
import json
import sys
from pathlib import Path

root = Path("app")
packages = {p.name for p in root.iterdir() if (p / "__init__.py").exists() and p.name != "tests"}
edges = {}
functions = []
for package in sorted(packages):
    for path in sorted((root / package).rglob("*.py")):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module.split(".")[0]]
            for target in set(names) & packages - {package, "core"}:
                edges.setdefault(f"{package}->{target}", set()).add(path.as_posix())
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                branches = sum(
                    isinstance(n, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.IfExp))
                    for n in ast.walk(node)
                )
                functions.append(
                    {
                        "path": path.as_posix(),
                        "function": node.name,
                        "line": node.lineno,
                        "lines": node.end_lineno - node.lineno + 1,
                        "branch_nodes": branches,
                    }
                )
cycles = set()


def walk(start, path):
    for target in packages:
        if f"{path[-1]}->{target}" not in edges:
            continue
        if target == start:
            cycle = tuple(path)
            cycles.add(min(cycle[n:] + cycle[:n] for n in range(len(cycle))))
        elif target not in path:
            walk(start, [*path, target])


for package in packages:
    walk(package, [package])
result = {
    "packages": sorted(packages),
    "edges": {k: sorted(v) for k, v in sorted(edges.items())},
    "cycles": [list(c) for c in sorted(cycles)],
    "hotspots": sorted(functions, key=lambda f: (f["branch_nodes"], f["lines"]), reverse=True)[:25],
    "functions": functions,
}
out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
print("packages", len(packages), "edges", len(edges), "cycles", result["cycles"])
print(json.dumps(result["hotspots"][:7], indent=2))
