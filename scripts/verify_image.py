"""IMP-01: verify a loaded image and the container actually running it; no env output."""

import argparse
import json
import re
import shutil
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--container")
    arguments = parser.parse_args()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", arguments.image_id):
        parser.error("Provide the full image ID recorded before transfer")
    docker = shutil.which("docker")
    if not docker:
        raise SystemExit("Docker CLI not found")

    def inspect(kind: str, name: str) -> dict:
        result = subprocess.run(
            [docker, kind, "inspect", "--", name], capture_output=True, check=False
        )
        if result.returncode:
            raise SystemExit(f"Unable to inspect {kind}; no raw metadata printed")
        return json.loads(result.stdout)[0]

    loaded = inspect("image", arguments.image)
    version = loaded["Config"].get("Labels", {}).get("org.opencontainers.image.version")
    if loaded["Id"] != arguments.image_id or version != arguments.version:
        raise SystemExit("Loaded image ID/version does not match the release record")
    if arguments.container:
        container = inspect("container", arguments.container)
        if not container["State"]["Running"] or container["Image"] != arguments.image_id:
            raise SystemExit("Running container does not use the expected image")
    print(f"PASS image identity: {arguments.image_id}, build {arguments.version}")


if __name__ == "__main__":
    main()
