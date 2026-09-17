"""Independent REL-03 attachment check; never prints matching sensitive values."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile


def strings(value):
    if isinstance(value, str):
        yield value
        if value.lstrip().startswith(("{", "[")):
            try:
                decoded = json.loads(value)
            except (ValueError, RecursionError):
                return
            if not isinstance(decoded, str):
                yield from strings(decoded)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def verify(archive_path, audit, selection, private):
    failures = Counter()
    values = private if isinstance(private, list) else private["values"]
    expected = {s["file"]: s for s in audit["manifest"]}
    chosen = {(d["tool"], d["id"]) for d in selection["decisions"] if d["include"]}
    observed = set()
    records = 0
    signature = re.compile(
        r"(?:gsk_|sk-proj-|sk-ant-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}"
        r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
        r"|b3BlbnNzaC1rZXktdjE[A-Za-z0-9+/=]{20,}"
        r"|(?i:Bearer) [A-Za-z0-9_.-]{20,}"
        r"|(?i:postgres(?:ql)?|https?)://[^\s/@:]+:[^\s/@]+@"
    )
    home = re.compile(r"(?i)(?:[a-z]:|/[a-z]|/mnt/[a-z])/+Users/+[^/\s<>]+")
    with ZipFile(archive_path) as archive:
        names = archive.namelist()
        if set(names) != set(expected) | {"manifest.json"} or len(names) != len(expected) + 1:
            raise ValueError("Unexpected ZIP members")
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC mismatch")
        if json.loads(archive.read("manifest.json")) != audit["manifest"]:
            raise ValueError("Embedded and external manifests differ")
        for name, entry in expected.items():
            if "/" in name or "\\" in name:
                raise ValueError("Unexpected nested archive path")
            _, tool, identifier = name.removesuffix(".jsonl").split("_", 2)
            observed.add((tool, identifier))
            data = archive.read(name)
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("Member hash mismatch")
            rows = [json.loads(line) for line in data.splitlines()]
            if len(rows) != entry["lines"]:
                raise ValueError("Member line count mismatch")
            records += len(rows)
            for row in rows:
                for text in strings(row):
                    if any(secret in text for secret in values):
                        failures["known_private_value"] += 1
                    if signature.search(text):
                        failures["credential_signature"] += 1
                    if home.search(text.replace("\\", "/")):
                        failures["local_home_path"] += 1
                    if re.search(r"data:image/[^;]+;base64,[A-Za-z0-9+/]{40}", text):
                        failures["opaque_image"] += 1
    if observed != chosen:
        raise ValueError("ZIP differs from reviewed selection")
    digest = hashlib.sha256(Path(archive_path).read_bytes()).hexdigest()
    if digest != audit["archive_sha256"] or records != audit["lines"]:
        raise ValueError("Attachment hash or total line count mismatch")
    if failures:
        raise ValueError("Independent privacy scan failed: " + json.dumps(failures))
    return {
        "task": "REL-03",
        "checked_at": datetime.now(UTC).isoformat(),
        "archive_sha256": digest,
        "sessions": len(expected),
        "records": records,
        "selection_matches": True,
        "all_member_hashes_match": True,
        "zip_crc_valid": True,
        "all_records_valid_json": True,
        "privacy_residuals": dict(failures),
        "limitations": "Pattern/exact-value scan; not proof against every unknown secret format.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--private-values", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = verify(
        args.archive,
        json.loads(args.audit.read_text(encoding="utf-8")),
        json.loads(args.selection.read_text(encoding="utf-8")),
        json.loads(args.private_values.read_text(encoding="utf-8")),
    )
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
