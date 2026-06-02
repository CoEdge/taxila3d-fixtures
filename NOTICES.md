# Third-party fixture attribution

This corpus redistributes 3D mesh assets from public sources. Each section
below names the upstream, its license, and the files we vendor from it.

## `obj/` — alecjacobson/common-3d-test-models

**Upstream:** https://github.com/alecjacobson/common-3d-test-models

A curated collection of small triangle meshes maintained by Alec Jacobson
for use as shared sample data in graphics research and tooling. Each file
in that repo carries its own per-asset README/license notice; we
preserve the asset names so the upstream attribution is discoverable.

**Vendored files:**

| File | Notes |
|---|---|
| `armadillo.obj` | Stanford Armadillo scan, decimated |
| `beast.obj` | Pixar "Beast" (used in many SIGGRAPH papers) |
| `bob.obj` | Geometry-processing test mesh |
| `cheburashka.obj` | Soviet animation character mesh |
| `cow.obj` | Spot's predecessor, classic teaching mesh |
| `happy.obj` | Stanford Happy Buddha, decimated |
| `nefertiti.obj` | Nefertiti bust scan |
| `ogre.obj` | Test asset |
| `spot.obj` | Keenan Crane's "Spot" the cow (CC0) |
| `suzanne.obj` | Blender Suzanne (CC0) |
| `stanford-bunny.obj` | Stanford bunny (Stanford 3D Scanning Repository) |

Refresh script: `scripts/refresh_obj.py` — fetches via GitHub raw.

## `gltf/` — KhronosGroup/glTF-Sample-Assets

**Upstream:** https://github.com/KhronosGroup/glTF-Sample-Assets
**License:** CC-BY 4.0 / CC0 mix (per `LICENSE.md` alongside each model).

The official glTF 2.0 reference asset set. Each model carries its own
`LICENSE.md` in the upstream repo; the upstream tree structure is
preserved here so the per-model license is discoverable.

**Vendored models:** `Triangle`, `TriangleWithoutIndices`, `Box`,
`BoxTextured`, `BoxVertexColors`, `Cube`, `Duck`, `Avocado`, `Lantern`,
`Suzanne`. The set covers the three glTF container variants
(`.gltf` + `.bin`, `.gltf-Embedded` with data-URI buffers, and `.glb`
binary container) and the four importer-relevant attribute combos
(positions only, +normals, +UVs, +colors).

Refresh script: `scripts/refresh_gltf.py` — fetches via GitHub raw.

## `stl/` — procedurally generated (no upstream)

**License:** MIT (per `LICENSE` — the STL files are produced from
arithmetic in `scripts/refresh_stl_subset.py`, no third-party content).

The full Thingi10K dataset (Zhou & Jacobson, arXiv:1605.04797) is
24 GB and can't be redistributed in a submodule. Instead we generate
a small (~20-mesh, < 1 MiB) deterministic set of procedural shapes —
boxes, spheres, tetrahedra, tori, cylinders, cones — covering both
binary and ASCII STL formats and a range of triangle counts. Each mesh
is emitted as STL triangle soup (three unique vertices per triangle,
no shared positions — the canonical STL pathology the importer's weld
pass exists to repair). See `stl/CREDITS.csv` for per-file shape +
triangle-count metadata.

The STL importer's synthetic unit tests (in `crates/taxila3d-io-stl/`)
cover format-level edge cases (truncated binary, ASCII trailing
whitespace, NaN scrubbing). The procedural corpus complements those by
verifying real-shaped meshes parse, finalize, and validate cleanly.

Refresh script: `scripts/refresh_stl_subset.py` — stdlib-only, no
network access.