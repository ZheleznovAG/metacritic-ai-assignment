"""Architecture fitness functions: the module dependency graph is checked, not only described.

`docs/design.md` assigns each package one responsibility, but Python does not stop one package
from importing another. This test derives the graph between first-party packages from the
production source (tests and migrations excluded; imports inside functions included) and compares
it with `ALLOWED` in both directions:

- a new edge fails until it is deliberately added here with a reason;
- a removed edge fails until it is deleted here, so the list only ever shrinks when the code does.

`ALLOWED` records the graph as found on 2026-09-30, including cycles (for example
`catalog <-> processing`) that are known debt, not a target. Pure packages additionally must not
import Django or network clients.
"""

import ast
from pathlib import Path

from django.test import SimpleTestCase

APP = Path(__file__).resolve().parents[1]
PACKAGES = frozenset(
    {
        "catalog",
        "config",
        "metacritic",
        "presentation",
        "processing",
        "reviews",
        "similarity",
        "summaries",
    }
)
ALLOWED = frozenset(
    {
        ("catalog", "metacritic"),
        ("catalog", "processing"),
        ("catalog", "reviews"),
        ("catalog", "similarity"),
        ("config", "presentation"),
        ("presentation", "catalog"),
        ("presentation", "processing"),
        ("presentation", "reviews"),
        ("presentation", "summaries"),
        ("processing", "catalog"),
        ("processing", "metacritic"),
        ("processing", "reviews"),
        ("processing", "summaries"),
        ("reviews", "catalog"),
        ("reviews", "metacritic"),
        ("reviews", "processing"),
        ("reviews", "summaries"),
        ("similarity", "catalog"),
        ("summaries", "processing"),
        ("summaries", "reviews"),
    }
)
# Packages that must stay free of the ORM, HTTP and provider clients (`docs/design.md`).
PURE = {"similarity": frozenset({"django", "httpx", "groq"})}


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _production_files(package: str) -> list[Path]:
    return [
        path
        for path in sorted((APP / package).rglob("*.py"))
        if "migrations" not in path.relative_to(APP).parts
    ]


def dependency_graph() -> dict[tuple[str, str], list[str]]:
    """Edge -> the files that create it, for readable failure messages."""
    edges: dict[tuple[str, str], list[str]] = {}
    for package in sorted(PACKAGES):
        for path in _production_files(package):
            for target in _imported_roots(path) & PACKAGES - {package}:
                edges.setdefault((package, target), []).append(path.relative_to(APP).as_posix())
    return edges


class ModuleDependencyTests(SimpleTestCase):
    def test_no_new_dependency_between_packages(self) -> None:
        new = {edge: files for edge, files in dependency_graph().items() if edge not in ALLOWED}
        self.assertEqual(new, {}, "new package dependency; decide it explicitly in ALLOWED")

    def test_removed_dependencies_are_removed_from_the_allowlist(self) -> None:
        stale = ALLOWED - dependency_graph().keys()
        self.assertEqual(stale, set(), "dependency no longer exists; delete it from ALLOWED")

    def test_pure_packages_import_no_framework_or_network_client(self) -> None:
        for package, forbidden in PURE.items():
            for path in _production_files(package):
                with self.subTest(path=path.relative_to(APP).as_posix()):
                    self.assertEqual(_imported_roots(path) & forbidden, set())

    def test_the_graph_is_derived_from_real_files(self) -> None:
        # Guards the scanner itself: a known edge and its source file must be found.
        self.assertIn("processing/runner.py", dependency_graph()[("processing", "catalog")])
