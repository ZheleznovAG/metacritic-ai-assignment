import ast
import argparse
import json
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description="FIN-ARCH source-preservation countercheck.")
parser.add_argument("--baseline", default="9b82da0")
parser.add_argument("--output", type=Path, default=Path(".artifacts/fin-arch-preservation.json"))
args = parser.parse_args()


def old(path):
    return ast.parse(
        subprocess.check_output(
            ["git", "show", f"{args.baseline}:{path}"], text=True, encoding="utf-8"
        )
    )


def new(path):
    return ast.parse(Path(path).read_text(encoding="utf-8"))


def function(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


before = function(old("app/reviews/collector.py"), "collect_one_page")
after = function(new("app/reviews/collector.py"), "_commit_page")
b = [n for n in before.body if isinstance(n, ast.With)][-1]
a = [n for n in after.body if isinstance(n, ast.With)][-1]
assert ast.dump(b) == ast.dump(a)
assert ast.dump(before.body[-1]) == ast.dump(after.body[-1])
assert ast.dump(function(old("app/reviews/dispatch.py"), "claim_next")) == ast.dump(
    function(new("app/orchestration/jobs.py"), "claim_next")
)


class RenameDispatch(ast.NodeTransformer):
    def visit_Name(self, node):
        if node.id == "dispatch":
            node.id = "jobs"
        return node


original = RenameDispatch().visit(old("app/reviews/management/commands/run_worker.py"))
current = new("app/orchestration/management/commands/run_worker.py")
before_class = next(n for n in original.body if isinstance(n, ast.ClassDef))
after_class = next(n for n in current.body if isinstance(n, ast.ClassDef))
assert ast.dump(before_class) == ast.dump(after_class)
result = {
    "collector_commit_transaction_ast_unchanged": True,
    "collector_return_ast_unchanged": True,
    "durable_dispatch_function_ast_unchanged": True,
    "worker_command_class_ast_unchanged_except_dispatch_alias": True,
    "method": "AST dump comparison ignoring source locations; node bodies remain identical to parent source, worker dispatch alias normalized.",
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps(result, indent=2))
