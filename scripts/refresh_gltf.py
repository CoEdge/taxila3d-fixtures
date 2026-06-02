#!/usr/bin/env python3
"""Refresh the glTF test corpus under ../gltf/.

Pulls a small, well-known subset of the official KhronosGroup
glTF-Sample-Assets repository — covers data-URI, external-buffer,
and binary (.glb) container variants. Each picked sample exercises
a distinct feature of the importer.

Usage:
    python scripts/refresh_gltf.py

Requires:
    Python 3.8+, stdlib only.

Run this when:
  - An upstream sample renames a file (e.g. the per-model .bin filenames
    have been renamed multiple times in glTF-Sample-Assets history).
  - We want to add another model to the corpus.
After running, commit the resulting `gltf/**` files to this repo.
"""

from __future__ import annotations

import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TARGET_DIR = SCRIPT_DIR.parent / "gltf"

GH_BASE = (
    "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/"
)

# Each entry: (display name, list of relative URLs to fetch into the
# same local directory under TARGET_DIR/<display>/...). The first URL
# of each model is the .gltf or .glb entry point.
SAMPLES: list[tuple[str, list[str]]] = [
    ("Triangle", ["Triangle/glTF/Triangle.gltf", "Triangle/glTF/Triangle.bin"]),
    (
        "TriangleWithoutIndices",
        [
            "TriangleWithoutIndices/glTF/TriangleWithoutIndices.gltf",
            "TriangleWithoutIndices/glTF/TriangleWithoutIndices.bin",
        ],
    ),
    ("Box", ["Box/glTF-Embedded/Box.gltf"]),
    ("BoxTextured", ["BoxTextured/glTF-Embedded/BoxTextured.gltf"]),
    ("BoxVertexColors", ["BoxVertexColors/glTF-Embedded/BoxVertexColors.gltf"]),
    ("Cube", ["Cube/glTF/Cube.gltf", "Cube/glTF/Cube.bin"]),
    ("Duck", ["Duck/glTF-Binary/Duck.glb"]),
    ("Avocado", ["Avocado/glTF-Binary/Avocado.glb"]),
    ("Lantern", ["Lantern/glTF-Binary/Lantern.glb"]),
    ("Suzanne", ["Suzanne/glTF/Suzanne.gltf", "Suzanne/glTF/Suzanne.bin"]),
]


def download(url: str, dst: Path) -> bool:
    if dst.exists() and dst.stat().st_size > 0:
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
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
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Target directory: {TARGET_DIR}")

    # Each sample lives in its own subdirectory under TARGET_DIR so the
    # .gltf and its sidecar .bin / .png stay together — the importer
    # resolves buffer URIs relative to the .gltf, so flattening would
    # orphan external buffers. The taxila3d-rust fixture loader walks
    # the format dir recursively.
    ok = 0
    fail = 0
    for display, urls in SAMPLES:
        for rel in urls:
            url = GH_BASE + rel
            local_name = Path(rel).name
            dst = TARGET_DIR / display / local_name
            if download(url, dst):
                ok += 1
                print(f"  OK   {display}/{local_name}  ({dst.stat().st_size // 1024} KiB)")
            else:
                fail += 1

    print(f"\nDone. {ok} OK, {fail} failed.")
    if ok < 10:
        print(
            "WARNING: fewer than 10 glTF fixtures fetched. The downstream\n"
            "         integration tests require >= 10 fixtures to pass.",
            file=sys.stderr,
        )
        return 1
    # Partial-failure tolerance: upstream sample asset paths drift over time.
    # The integration test passes once >= 10 fixtures exist locally.
    return 0


if __name__ == "__main__":
    sys.exit(main())