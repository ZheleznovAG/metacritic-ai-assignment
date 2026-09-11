"""Create new local application config without touching operator .env or existing files."""

import argparse
import os
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--host")
    parser.add_argument("--version")
    parser.add_argument("--upgrade-scaffold", action="store_true")
    arguments = parser.parse_args()
    if arguments.production and (
        not arguments.host
        or not re.fullmatch(r"[a-zA-Z0-9.-]+", arguments.host)
        or not arguments.version
        or not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", arguments.version)
    ):
        parser.error("Preview production requires --host and a bounded build --version")
    target = ROOT / ".env.app"
    if arguments.upgrade_scaffold:
        if arguments.production or arguments.host or arguments.version:
            parser.error("Upgrade preserves existing deployment settings; omit other options")
        # Explicit append-only upgrade: preserve all original credentials/settings.
        original = target.read_text(encoding="utf-8")
        names = {line.split("=", 1)[0] for line in original.splitlines() if "=" in line}
        additions = []
        for role in ("WEB", "MIGRATE", "CHECKS", "SCHEDULER"):
            for name, value in (
                (f"{role}_DB_USER", f"metacritic_{role.lower()}"),
                (f"{role}_DB_PASSWORD", secrets.token_hex(24)),
            ):
                if name not in names:
                    additions.append(f"{name}={value}\n")
        if additions:
            with target.open("a", encoding="utf-8", newline="\n") as output:
                output.write(("\n" if not original.endswith("\n") else "") + "".join(additions))
        print("Scaffold environment upgraded; original credentials/settings preserved.")
        raise SystemExit(0)
    template = (ROOT / ".env.app.example").read_text(encoding="utf-8")
    template = template.replace(
        "DJANGO_SECRET_KEY=\n", f"DJANGO_SECRET_KEY={secrets.token_hex(40)}\n"
    )
    template = template.replace(
        "POSTGRES_PASSWORD=\n", f"POSTGRES_PASSWORD={secrets.token_hex(24)}\n"
    )
    for role in ("WEB", "MIGRATE", "CHECKS", "SCHEDULER"):
        template = template.replace(
            f"{role}_DB_PASSWORD=\n", f"{role}_DB_PASSWORD={secrets.token_hex(24)}\n"
        )
    if arguments.production:
        template = template.replace("APP_ENV=local", "APP_ENV=production")
        template = template.replace(
            "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1",
            f"DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,{arguments.host}",
        )
        template = template.replace("APP_VERSION=local", f"APP_VERSION={arguments.version}")
        template += f"APP_IMAGE=metacritic-imp01:{arguments.version}\n"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(template)
    print(
        "Created application-only .env.app; values are not printed. Operator .env was not changed."
    )
