#!/usr/bin/env python3
"""Generate the curated STL test corpus under ../stl/.

We generate a small (~20-mesh, < 1 MiB total) deterministic set of
procedural shapes rather than vendoring third-party content. Rationale:

  - Full Thingi10K is 24 GB and can't be redistributed in this repo.
  - The STL importer's synthetic unit tests already cover format-level
    edge cases (truncated binary, ASCII trailing whitespace, ...). The
    nightly integration tests just need real-shaped STLs that parse,
    finalize, and validate cleanly.
  - Procedural generation gives us full control: stable file IDs,
    predictable bbox/triangle counts, both binary and ASCII formats,
    a mix of small + medium meshes.

Each generated shape is a watertight closed mesh (box, sphere, torus,
icosahedron, ...) emitted as STL triangle soup (three unique vertices
per triangle, no shared positions — the canonical STL pathology that
the importer's weld pass exists to repair).

Usage:
    python scripts/refresh_stl_subset.py        # generate all
    python scripts/refresh_stl_subset.py --binary-only   # only binary STL
    python scripts/refresh_stl_subset.py --ascii-only    # only ASCII STL

Requires: Python 3.8+, stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import math
import struct
import sys
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
TARGET_DIR = SCRIPT_DIR.parent / "stl"
CREDITS_CSV = TARGET_DIR / "CREDITS.csv"


# ---------------------------------------------------------------------------
# Shape generators — each returns a list of triangles, where each triangle
# is ((x0,y0,z0), (x1,y1,z1), (x2,y2,z2)).
# ---------------------------------------------------------------------------


def axis_box(sx: float, sy: float, sz: float) -> list[tuple[tuple[float, float, float], ...]]:
    """Axis-aligned box centered at origin with the given half-extents."""
    hx, hy, hz = sx, sy, sz
    # 8 vertices.
    v = [
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (hx, hy, hz),
        (-hx, hy, hz),
    ]
    # 12 triangles, two per face, CCW from outside.
    faces = [
        (0, 3, 2), (0, 2, 1),  # -z
        (4, 5, 6), (4, 6, 7),  # +z
        (0, 1, 5), (0, 5, 4),  # -y
        (3, 7, 6), (3, 6, 2),  # +y
        (0, 4, 7), (0, 7, 3),  # -x
        (1, 2, 6), (1, 6, 5),  # +x
    ]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


def tetrahedron(r: float) -> list[tuple[tuple[float, float, float], ...]]:
    """Regular tetrahedron with circumradius r."""
    s = r / math.sqrt(3.0)
    v = [
        (s, s, s),
        (s, -s, -s),
        (-s, s, -s),
        (-s, -s, s),
    ]
    faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


def octahedron(r: float) -> list[tuple[tuple[float, float, float], ...]]:
    """Regular octahedron, vertices on the unit axes scaled by r."""
    v = [
        (r, 0, 0), (-r, 0, 0),
        (0, r, 0), (0, -r, 0),
        (0, 0, r), (0, 0, -r),
    ]
    faces = [
        (0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
        (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5),
    ]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


def icosahedron(r: float) -> list[tuple[tuple[float, float, float], ...]]:
    """Regular icosahedron with circumradius r."""
    t = (1.0 + math.sqrt(5.0)) / 2.0
    raw = [
        (-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0),
        (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
        (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1),
    ]
    norm = math.sqrt(1.0 + t * t)
    v = [(x * r / norm, y * r / norm, z * r / norm) for x, y, z in raw]
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


def uv_sphere(r: float, u_segs: int, v_segs: int) -> list[tuple[tuple[float, float, float], ...]]:
    """Latitude/longitude sphere. `u_segs` slices around, `v_segs` rings (≥ 3)."""
    tris: list[tuple[tuple[float, float, float], ...]] = []
    for j in range(v_segs):
        v0 = j / v_segs
        v1 = (j + 1) / v_segs
        phi0 = math.pi * v0 - math.pi / 2  # -π/2 .. π/2
        phi1 = math.pi * v1 - math.pi / 2
        for i in range(u_segs):
            u0 = i / u_segs
            u1 = (i + 1) / u_segs
            th0 = 2 * math.pi * u0
            th1 = 2 * math.pi * u1

            def p(th: float, phi: float) -> tuple[float, float, float]:
                c = math.cos(phi)
                return (r * c * math.cos(th), r * c * math.sin(th), r * math.sin(phi))

            a = p(th0, phi0)
            b = p(th1, phi0)
            c = p(th1, phi1)
            d = p(th0, phi1)
            if j != 0:
                tris.append((a, b, c))
            if j != v_segs - 1:
                tris.append((a, c, d))
    return tris


def torus(major_r: float, minor_r: float, n_major: int, n_minor: int):
    tris: list[tuple[tuple[float, float, float], ...]] = []
    for i in range(n_major):
        u0 = i / n_major
        u1 = (i + 1) / n_major
        th0 = 2 * math.pi * u0
        th1 = 2 * math.pi * u1
        for j in range(n_minor):
            v0 = j / n_minor
            v1 = (j + 1) / n_minor
            ph0 = 2 * math.pi * v0
            ph1 = 2 * math.pi * v1

            def p(th: float, ph: float):
                cph = math.cos(ph)
                return (
                    (major_r + minor_r * cph) * math.cos(th),
                    (major_r + minor_r * cph) * math.sin(th),
                    minor_r * math.sin(ph),
                )

            a = p(th0, ph0)
            b = p(th1, ph0)
            c = p(th1, ph1)
            d = p(th0, ph1)
            tris.append((a, b, c))
            tris.append((a, c, d))
    return tris


def cylinder(r: float, h: float, segs: int):
    tris: list[tuple[tuple[float, float, float], ...]] = []
    z0, z1 = -h / 2, h / 2
    for i in range(segs):
        u0 = i / segs
        u1 = (i + 1) / segs
        th0 = 2 * math.pi * u0
        th1 = 2 * math.pi * u1
        c0, s0 = math.cos(th0), math.sin(th0)
        c1, s1 = math.cos(th1), math.sin(th1)
        # Side wall.
        a = (r * c0, r * s0, z0)
        b = (r * c1, r * s1, z0)
        c = (r * c1, r * s1, z1)
        d = (r * c0, r * s0, z1)
        tris.append((a, b, c))
        tris.append((a, c, d))
        # Caps (triangle fan to center).
        tris.append(((0, 0, z0), b, a))
        tris.append(((0, 0, z1), d, c))
    return tris


def cone(r: float, h: float, segs: int):
    tris: list[tuple[tuple[float, float, float], ...]] = []
    z_base = 0.0
    z_apex = h
    for i in range(segs):
        u0 = i / segs
        u1 = (i + 1) / segs
        th0 = 2 * math.pi * u0
        th1 = 2 * math.pi * u1
        c0, s0 = math.cos(th0), math.sin(th0)
        c1, s1 = math.cos(th1), math.sin(th1)
        a = (r * c0, r * s0, z_base)
        b = (r * c1, r * s1, z_base)
        apex = (0, 0, z_apex)
        # Side.
        tris.append((a, b, apex))
        # Base cap.
        tris.append(((0, 0, z_base), b, a))
    return tris


# ---------------------------------------------------------------------------
# STL writers
# ---------------------------------------------------------------------------


def _face_normal(tri):
    (a, b, c) = tri
    e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (
        e1[1] * e2[2] - e1[2] * e2[1],
        e1[2] * e2[0] - e1[0] * e2[2],
        e1[0] * e2[1] - e1[1] * e2[0],
    )
    L = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
    if L > 1e-12:
        return (n[0] / L, n[1] / L, n[2] / L)
    return (0.0, 0.0, 1.0)


def write_binary_stl(path: Path, tris: Iterable[tuple]) -> None:
    tris = list(tris)
    with path.open("wb") as f:
        f.write(b"\x00" * 80)
        f.write(struct.pack("<I", len(tris)))
        for t in tris:
            n = _face_normal(t)
            f.write(struct.pack("<fff", *n))
            for v in t:
                f.write(struct.pack("<fff", *v))
            f.write(b"\x00\x00")


def write_ascii_stl(path: Path, tris: Iterable[tuple], name: str) -> None:
    with path.open("w", encoding="ascii") as f:
        f.write(f"solid {name}\n")
        for t in tris:
            n = _face_normal(t)
            f.write(f"  facet normal {n[0]} {n[1]} {n[2]}\n")
            f.write("    outer loop\n")
            for v in t:
                f.write(f"      vertex {v[0]} {v[1]} {v[2]}\n")
            f.write("    endloop\n")
            f.write("  endfacet\n")
        f.write(f"endsolid {name}\n")


# ---------------------------------------------------------------------------
# Fixture catalog
# ---------------------------------------------------------------------------


FIXTURES = [
    ("box_unit",            "binary", lambda: axis_box(0.5, 0.5, 0.5)),
    ("box_thin_x",          "binary", lambda: axis_box(2.0, 0.05, 0.05)),
    ("box_large_y",         "binary", lambda: axis_box(0.5, 100.0, 0.5)),
    ("box_unit",            "ascii",  lambda: axis_box(0.5, 0.5, 0.5)),
    ("tetrahedron_unit",    "binary", lambda: tetrahedron(1.0)),
    ("octahedron_unit",     "binary", lambda: octahedron(1.0)),
    ("icosahedron_unit",    "binary", lambda: icosahedron(1.0)),
    ("icosahedron_unit",    "ascii",  lambda: icosahedron(1.0)),
    ("sphere_coarse",       "binary", lambda: uv_sphere(1.0, 12, 8)),
    ("sphere_medium",       "binary", lambda: uv_sphere(1.0, 24, 16)),
    ("sphere_fine",         "binary", lambda: uv_sphere(1.0, 48, 32)),
    ("sphere_huge_radius",  "binary", lambda: uv_sphere(1000.0, 12, 8)),
    ("torus_basic",         "binary", lambda: torus(2.0, 0.5, 24, 12)),
    ("torus_thin",          "binary", lambda: torus(5.0, 0.2, 32, 16)),
    ("cylinder_short",      "binary", lambda: cylinder(1.0, 2.0, 24)),
    ("cylinder_tall",       "binary", lambda: cylinder(0.3, 8.0, 16)),
    ("cylinder_short",      "ascii",  lambda: cylinder(1.0, 2.0, 12)),
    ("cone_basic",          "binary", lambda: cone(1.0, 2.0, 24)),
    ("cone_squat",          "binary", lambda: cone(2.0, 0.5, 16)),
    ("cone_basic",          "ascii",  lambda: cone(1.0, 2.0, 12)),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary-only", action="store_true")
    parser.add_argument("--ascii-only", action="store_true")
    args = parser.parse_args()

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Target directory: {TARGET_DIR}")

    written = 0
    rows: list[dict[str, str]] = []
    for stem, fmt, factory in FIXTURES:
        if args.binary_only and fmt != "binary":
            continue
        if args.ascii_only and fmt != "ascii":
            continue
        suffix = "_bin.stl" if fmt == "binary" else "_ascii.stl"
        path = TARGET_DIR / f"{stem}{suffix}"
        tris = factory()
        if fmt == "binary":
            write_binary_stl(path, tris)
        else:
            write_ascii_stl(path, tris, stem)
        written += 1
        size_kib = path.stat().st_size // 1024
        rows.append(
            {
                "file": path.name,
                "format": fmt,
                "shape": stem,
                "triangles": str(len(tris)),
                "size_kib": str(size_kib),
                "source": "generated by scripts/refresh_stl_subset.py",
                "license": "MIT (procedural generation)",
            }
        )
        print(f"  OK   {path.name}  ({len(tris)} tris, {size_kib} KiB)")

    with CREDITS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["file", "format", "shape", "triangles", "size_kib", "source", "license"],
        )
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["file"]):
            writer.writerow(row)

    print(f"\nDone. {written} STL files in {TARGET_DIR}, credits in {CREDITS_CSV.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
