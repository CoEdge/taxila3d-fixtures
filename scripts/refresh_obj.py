#!/usr/bin/env python3
"""Refresh the OBJ test corpus under ../obj/.

Pulls a small curated set of well-known triangle meshes from two public
sources:

  * alecjacobson/common-3d-test-models  (Suzanne, Spot, Nefertiti, …)
  * Stanford 3D Scanning Repository      (bunny)

These give the OBJ importer integration tests in taxila3d-rust a stable,
free-to-redistribute set of fixtures. About 10 meshes total, < 30 MiB.

Usage:
    python scripts/refresh_obj.py

Requires:
    Python 3.8+, `urllib` from the stdlib only — no third-party deps.

Run this when:
  - An upstream sample renames or removes a file.
  - We want to add a new mesh to the corpus.
After running, commit the resulting `obj/*.obj` files to this repo.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TARGET_DIR = SCRIPT_DIR.parent / "obj"

COMMON_3D_BASE = (
    "https://raw.githubusercontent.com/alecjacobson/common-3d-test-models/master/data/"
)
COMMON_3D_FILES = [
    "armadillo.obj",
    "beast.obj",
    "bob.obj",
    "cheburashka.obj",
    "cow.obj",
    "happy.obj",
    "nefertiti.obj",
    "ogre.obj",
    "spot.obj",
    "suzanne.obj",
]

# Stanford bunny in OBJ form is not hosted on the Stanford repo
# directly; pull from a permissive mirror (Common 3D Test Models
# already has it as `stanford-bunny.obj`).
STANFORD_FALLBACK = [("stanford-bunny.obj", COMMON_3D_BASE + "stanford-bunny.obj")]


def download(url: str, dst: Path) -> bool:
    if dst.exists() and dst.stat().st_size > 0:
        return True
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, dst.open("wb") as out:
            shutil.copyfileobj(resp, out)
    except urllib.error.URLError as e:
        print(f"  FAIL {url}: {e}", file=sys.stderr)
        if dst.exists():
            dst.unlink()
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Skip files already present (default).",
    )
    args = parser.parse_args()
    _ = args  # keep-existing is the only behavior

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Target directory: {TARGET_DIR}")

    ok = 0
    fail = 0
    for name in COMMON_3D_FILES:
        url = COMMON_3D_BASE + name
        dst = TARGET_DIR / name
        if download(url, dst):
            ok += 1
            print(f"  OK   {name}  ({dst.stat().st_size // 1024} KiB)")
        else:
            fail += 1
    for name, url in STANFORD_FALLBACK:
        dst = TARGET_DIR / name
        if download(url, dst):
            ok += 1
            print(f"  OK   {name}  ({dst.stat().st_size // 1024} KiB)")
        else:
            fail += 1

    print(f"\nDone. {ok} OK, {fail} failed.")
    if ok < 10:
        print(
            "WARNING: fewer than 10 OBJ fixtures fetched. The downstream\n"
            "         integration tests require >= 10 fixtures to pass.",
            file=sys.stderr,
        )
        return 1
    # Partial-failure tolerance: upstream sample asset paths drift over time
    # (e.g. bob.obj removed from alecjacobson/common-3d-test-models). The
    # integration test passes once >= 10 fixtures exist locally, so a few
    # missing entries is not a corpus-refresh-failing condition.
    return 0


if __name__ == "__main__":
    sys.exit(main())