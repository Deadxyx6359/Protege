#!/usr/bin/env python3
"""Download a GGUF into models/, safely.

    python tools/fetch_model.py <url> [--name NAME.gguf]

Fetches to `<name>.part` and renames only once the transfer completes, so a
partial download is never visible to Protégé as a model. Without that the
application discovers a half-written file, assigns it to a route, and fails to
load it — the failure arrives later and looks unrelated to the download.

This is one of the two moments in the project's lifecycle that touches the
network, the other being `pip install`. It is deliberately a separate script
run by hand rather than anything the application can trigger.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODELS = REPO / "models"

GGUF_MAGIC = b"GGUF"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fetch_model", description=__doc__)
    parser.add_argument("url", help="direct link to a .gguf file")
    parser.add_argument("--name", help="filename to save as (default: from the URL)")
    parser.add_argument(
        "--dir", default=str(MODELS), help="destination directory (default: models/)"
    )
    args = parser.parse_args(argv)

    name = args.name or args.url.rsplit("/", 1)[-1].split("?")[0]
    if not name.endswith(".gguf"):
        print(f"refusing: {name!r} is not a .gguf", file=sys.stderr)
        return 2

    directory = Path(args.dir)
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / name
    partial = directory / f"{name}.part"

    if final.exists():
        print(f"already present: {final}")
        return 0

    # -C - resumes an interrupted transfer rather than starting over, which
    # matters when the file is several gigabytes.
    command = [
        "curl", "-L", "--fail", "--retry", "3", "--retry-delay", "5",
        "-C", "-", "-o", str(partial), args.url,
    ]
    print(f"fetching {name} …")
    result = subprocess.run(command)
    if result.returncode != 0:
        print(f"download failed (curl exit {result.returncode}); {partial.name} kept "
              f"so it can be resumed", file=sys.stderr)
        return 1

    with partial.open("rb") as fh:
        if fh.read(4) != GGUF_MAGIC:
            print("downloaded file is not a GGUF — refusing to install it", file=sys.stderr)
            return 1

    partial.replace(final)
    size = final.stat().st_size / 1024**3
    print(f"installed {final}  ({size:.2f} GB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
