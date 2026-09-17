"""REL-03 / DEL-03 / NFR-06: scoped, sanitised local conversation export.

No network, account stores or application changes. Private values are supplied in an
ignored JSON file, never embedded in this module or the public verification report.
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

MARK = "[REDACTED]"
SECRET_KEY = re.compile(
    r"password|passwd|secret|(?:^|_)token(?:$|_)|api[_-]?key|apikey|authorization|cookie|private[_-]?key",
    re.I,
)
ASSIGNMENT = re.compile(
    r"(?i)([\"']?\b[\w-]*(?:password|passwd|secret|(?<![a-z])token|api[_-]?key|apikey|"
    r"authorization|cookie|private[_-]?key)[\w-]*[\"']?\s*[=:]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;}]+)"
)
SHAPES = [
    re.compile(r"(?:gsk_|sk-(?:proj-|ant-)?|gh[pousr]_|github_pat_)[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    re.compile(r"b3BlbnNzaC1rZXktdjE[A-Za-z0-9+/=]{20,}"),
    re.compile(
        r"-----BEGIN(?:[ A-Z]*)PRIVATE KEY-----[\s\S]*?"
        r"(?:-----END(?:[ A-Z]*)PRIVATE KEY-----|\Z)"
    ),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9+/_.=-]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(r"(?i)(?:[a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@"),
]
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
HOME_PATH = re.compile(
    r"(?i)(?:[a-z]:[\\/]+Users[\\/]+[^\\/\s\"'<>]+|/home/[^/\s\"'<>]+"
    r"|/(?:[a-z]|mnt/[a-z])/Users/[^/\s\"'<>]+)"
)
IMAGE_DATA = re.compile(r"data:image/[^;\s]+;base64,[A-Za-z0-9+/=\s]+")


def canonical(path: str) -> str:
    return re.sub(r"/+", "/", path.replace("\\", "/")).casefold().rstrip("/")


def in_project(cwd: str, project: str) -> bool:
    value, root = canonical(cwd), canonical(project)
    return value == root or value.startswith(root + "/")


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return result.astimezone(UTC)


class Redactor:
    def __init__(self, values=(), owner_email="", private_usernames=()):
        # JSON tool arguments can contain several layers of escaping.
        variants = set()
        for value in values:
            if not isinstance(value, str) or not value:
                raise ValueError("Private values must be nonempty strings")
            variants.add(value)
            for _ in range(3):
                value = json.dumps(value, ensure_ascii=False)[1:-1]
                variants.add(value)
        self.values = sorted(variants, key=len, reverse=True)
        self.owner_email = owner_email.casefold()
        self.private_usernames = private_usernames
        self.counts = Counter()

    def text(self, value: str) -> str:
        for secret in self.values:
            if secret in value:
                self.counts["private_value"] += value.count(secret)
                value = value.replace(secret, MARK)
        for pattern in SHAPES:
            value, n = pattern.subn(MARK, value)
            self.counts["credential_shape"] += n
        value, n = ASSIGNMENT.subn(lambda m: m[1] + MARK, value)
        self.counts["credential_assignment"] += n
        value, n = HOME_PATH.subn("<user-home>", value)
        self.counts["home_path"] += n
        value, n = IMAGE_DATA.subn("[REDACTED_IMAGE]", value)
        self.counts["embedded_image"] += n
        for username in self.private_usernames:
            # Preserve owner email and ordinary prose; redact login contexts only.
            pattern = re.compile(r"(?i)(?<![\w.])" + re.escape(username) + r"(?=@|[\"']|\s*$)")
            value, n = pattern.subn("<private-user>", value)
            self.counts["login_name"] += n

        def email(match):
            if match[0].casefold() == self.owner_email:
                return match[0]
            self.counts["email"] += 1
            return "<redacted-email>"

        return EMAIL.sub(email, value)

    def walk(self, value, depth=0):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if SECRET_KEY.search(key) and isinstance(item, str) and item:
                    result[self.text(key)] = MARK
                    self.counts["credential_field"] += 1
                elif key == "data" and value.get("type") == "base64":
                    result[key] = "[REDACTED_IMAGE]"
                    self.counts["embedded_image"] += 1
                else:
                    result[self.text(key)] = self.walk(item, depth + 1)
            return result
        if isinstance(value, list):
            return [self.walk(item, depth + 1) for item in value]
        if isinstance(value, str):
            if depth < 30 and value.lstrip().startswith(("{", "[")):
                try:
                    nested = json.loads(value)
                except (ValueError, RecursionError):
                    pass
                else:
                    return json.dumps(self.walk(nested, depth + 1), ensure_ascii=False)
            return self.text(value)
        return value


def read_session(path: Path):
    # Fixed byte boundary: an active writer cannot extend this snapshot while read.
    size = path.stat().st_size
    with path.open("rb") as stream:
        raw = stream.read(size)
    if raw and not raw.endswith(b"\n"):
        raise ValueError("Incomplete JSONL tail; retry after the writer flushes")
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    dates, directories = [], set()
    for row in rows:
        if row.get("timestamp"):
            dates.append(timestamp(row["timestamp"]))
        if row.get("cwd"):
            directories.add(row["cwd"])
        if row.get("type") == "session_meta":
            meta = row["payload"]
            if meta.get("timestamp"):
                dates.append(timestamp(meta["timestamp"]))
            if meta.get("cwd"):
                directories.add(meta["cwd"])
    return raw, rows, dates, directories


def collect(codex_root: Path, claude_root: Path, project: str, since: datetime):
    sessions, counts = [], Counter()
    for tool, directory in (("codex", codex_root), ("claude", claude_root)):
        if not directory.is_dir():
            raise ValueError(f"Missing {tool} session directory")
        for path in sorted(directory.rglob("*.jsonl")):
            raw, rows, dates, directories = read_session(path)
            if not dates:
                counts["undated"] += 1
                continue
            # Claude subagents without cwd inherit only from a verified parent.
            if not directories and tool == "claude" and "subagents" in path.parts:
                parent = claude_root / (path.relative_to(claude_root).parts[0] + ".jsonl")
                if parent.is_file():
                    directories = read_session(parent)[3]
            if not directories or not all(in_project(cwd, project) for cwd in directories):
                counts["outside_project_or_mixed"] += 1
                continue
            if min(dates) < since:
                counts["before_start"] += 1
                continue
            sessions.append(
                {
                    "tool": tool,
                    "path": path,
                    "raw": raw,
                    "rows": rows,
                    "start": min(dates).isoformat(),
                    "end": max(dates).isoformat(),
                    "kind": "subagent" if "subagents" in path.parts else "session",
                    "parent": path.relative_to(directory).parts[0]
                    if "subagents" in path.parts
                    else None,
                }
            )
    retained = []
    for session in sessions:
        duplicates = [
            other
            for other in sessions
            if other is not session
            and other["tool"] == session["tool"]
            and other["raw"].startswith(session["raw"])
            and (
                len(other["raw"]) > len(session["raw"]) or str(other["path"]) < str(session["path"])
            )
        ]
        if duplicates:
            counts["duplicate_prefix"] += 1
        else:
            retained.append(session)
    return sorted(retained, key=lambda s: (s["start"], s["tool"], s["path"].name)), counts


def select(sessions, decisions, excluded):
    """Require an explicit Git/artifact-based decision for every candidate session."""
    by_id = {(s["tool"], s["id"]): s for s in decisions}
    if len(by_id) != len(decisions):
        raise ValueError("Duplicate selection decision")
    selected = []
    for session in sessions:
        identifier = session["path"].stem
        if session["tool"] == "codex":
            identifier = identifier[-36:]
        decision = by_id.pop((session["tool"], identifier), None)
        if not decision or not decision.get("reason"):
            raise ValueError("Unreviewed session: update the Git correlation before exporting")
        if decision["include"]:
            if not decision.get("artifacts"):
                raise ValueError("Included session needs a repository artifact")
            session["correlation"] = decision
            selected.append(session)
        else:
            excluded[decision["category"]] += 1
    if by_id:
        raise ValueError("Selection refers to sessions missing from the source stores")
    return selected


def export(sessions, redactor: Redactor, output: Path, since: datetime, excluded):
    manifest = []
    temporary = output.with_suffix(".pending.zip")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(temporary, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for index, session in enumerate(sessions, 1):
            identifier = session["path"].stem
            if session["tool"] == "codex":
                identifier = identifier[-36:]
            name = f"{index:03}_{session['tool']}_{identifier}.jsonl"
            rows = [redactor.walk(row) for row in session["rows"]]
            data = ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode()
            # Validate serialized AND decoded values, including escaped exact values.
            parsed = [json.loads(line) for line in data.splitlines()]
            text = json.dumps(parsed, ensure_ascii=False)
            if any(value in text for value in redactor.values):
                raise ValueError(f"Private value remained in export member {index}")
            archive.writestr(name, data)
            manifest.append(
                {
                    "file": name,
                    "tool": session["tool"],
                    "kind": session["kind"],
                    "start": session["start"],
                    "end": session["end"],
                    "lines": len(rows),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            if index % 10 == 0:
                print(f"Archived {index}/{len(sessions)} verified sessions", flush=True)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
    with ZipFile(temporary) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != len(manifest) + 1:
            raise ValueError("Archive integrity failure")
    temporary.replace(output)
    return {
        "task": "REL-03",
        "requirements": ["DEL-03", "NFR-06"],
        "generated_at": datetime.now(UTC).isoformat(),
        "since": since.isoformat(),
        "sessions": len(manifest),
        "lines": sum(s["lines"] for s in manifest),
        "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "excluded_counts": dict(excluded),
        "redaction_counts": dict(redactor.counts),
        "known_value_residuals": 0,
        "jsonl_valid": True,
        "zip_crc_valid": True,
        "manifest": manifest,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--codex-root", type=Path, required=True)
    parser.add_argument("--claude-root", type=Path, required=True)
    parser.add_argument("--private-values", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--owner-email", default="")
    parser.add_argument("--since", default="2026-09-01T00:00:00+07:00")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    since = timestamp(args.since)
    private = json.loads(args.private_values.read_text(encoding="utf-8"))
    values = private if isinstance(private, list) else private["values"]
    usernames = [] if isinstance(private, list) else private.get("usernames", [])
    sessions, excluded = collect(args.codex_root, args.claude_root, str(args.project), since)
    decisions = json.loads(args.selection.read_text(encoding="utf-8"))["decisions"]
    sessions = select(sessions, decisions, excluded)
    if not sessions:
        raise ValueError("No matching sessions; refusing empty archive")
    report = export(
        sessions, Redactor(values, args.owner_email, usernames), args.output, since, excluded
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "manifest"}, indent=2))


if __name__ == "__main__":
    main()
