#!/usr/bin/env python3
"""Regenerate the procedural STEP (ISO 10303-21) corpus.

Stdlib-only, no network, no kernel dependency: every file is authored
here as Part 21 text, so the fixtures stay independent of the code they
test. Emits AP242 (with two AP203/AP214 variants for protocol coverage).

The corpus targets the STEP importer's hard cases rather than visual
variety:

  * analytic surface coverage — plane, cylinder, cone, sphere, torus
  * periodic seams — full-circle edges whose endpoint UVs coincide
  * *seamless* periodic faces — a cylinder bounded only by its two rim
    circles, no seam edges at all. Real CAD exports do this constantly
    and it is unrepresentable in UV without inserting a seam, so it is
    the single most valuable regression case here.
  * parametric poles — sphere caps closed by a VERTEX_LOOP
  * inner loops — a plate with a circular hole
  * foreign-writer dialect — exponent floats, non-unit VECTOR
    magnitudes, reversed FACE_BOUND orientation, complex (AND-type)
    rational B-spline entities
  * assemblies — NEXT_ASSEMBLY_USAGE_OCCURRENCE with a placement
    transform
  * AP242 hybrid — TESSELLATED_SHAPE_REPRESENTATION alongside the B-rep

Usage:  python scripts/refresh_step_subset.py
"""

from __future__ import annotations

import csv
import math
import os
import shutil

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "step")

# ---------------------------------------------------------------------------
# Part 21 emitter
# ---------------------------------------------------------------------------

SCHEMAS = {
    "AP242": "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF { 1 0 10303 442 1 1 4 }",
    "AP214": "AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }",
    "AP203": "CONFIG_CONTROL_DESIGN",
}


def r(v: float) -> str:
    """Format a real per Part 21 (must contain a '.')."""
    if v == int(v) and abs(v) < 1e15:
        return f"{int(v)}."
    s = repr(float(v))
    if "e" in s or "E" in s:
        mantissa, _, exponent = s.partition("e")
        if "." not in mantissa:
            mantissa += "."
        return f"{mantissa}E{int(exponent)}"
    return s


class Step:
    """Accumulates `#id = ...;` records."""

    def __init__(self, name: str, schema: str = "AP242") -> None:
        self.name = name
        self.schema = schema
        self.records: list[str] = []
        self._next = 1

    def add(self, body: str) -> int:
        i = self._next
        self._next += 1
        self.records.append(f"#{i} = {body};")
        return i

    # -- geometry primitives -------------------------------------------------

    def point(self, x: float, y: float, z: float) -> int:
        return self.add(f"CARTESIAN_POINT('',({r(x)},{r(y)},{r(z)}))")

    def direction(self, x: float, y: float, z: float) -> int:
        return self.add(f"DIRECTION('',({r(x)},{r(y)},{r(z)}))")

    def axis2(self, origin, axis, ref) -> int:
        p = self.point(*origin)
        a = self.direction(*axis)
        d = self.direction(*ref)
        return self.add(f"AXIS2_PLACEMENT_3D('',#{p},#{a},#{d})")

    def vertex(self, x: float, y: float, z: float) -> int:
        return self.add(f"VERTEX_POINT('',#{self.point(x, y, z)})")

    def line(self, origin, direction, magnitude: float = 1.0) -> int:
        p = self.point(*origin)
        d = self.direction(*direction)
        v = self.add(f"VECTOR('',#{d},{r(magnitude)})")
        return self.add(f"LINE('',#{p},#{v})")

    def circle(self, centre, axis, ref, radius: float) -> int:
        a = self.axis2(centre, axis, ref)
        return self.add(f"CIRCLE('',#{a},{r(radius)})")

    def plane(self, origin, axis, ref) -> int:
        return self.add(f"PLANE('',#{self.axis2(origin, axis, ref)})")

    def cylinder(self, origin, axis, ref, radius: float) -> int:
        a = self.axis2(origin, axis, ref)
        return self.add(f"CYLINDRICAL_SURFACE('',#{a},{r(radius)})")

    def cone(self, origin, axis, ref, radius: float, half_angle: float) -> int:
        a = self.axis2(origin, axis, ref)
        return self.add(f"CONICAL_SURFACE('',#{a},{r(radius)},{r(half_angle)})")

    def sphere(self, centre, axis, ref, radius: float) -> int:
        a = self.axis2(centre, axis, ref)
        return self.add(f"SPHERICAL_SURFACE('',#{a},{r(radius)})")

    def torus(self, centre, axis, ref, major: float, minor: float) -> int:
        a = self.axis2(centre, axis, ref)
        return self.add(f"TOROIDAL_SURFACE('',#{a},{r(major)},{r(minor)})")

    # -- topology ------------------------------------------------------------

    def edge(self, v0: int, v1: int, curve: int, same_sense: bool = True) -> int:
        s = ".T." if same_sense else ".F."
        return self.add(f"EDGE_CURVE('',#{v0},#{v1},#{curve},{s})")

    def oriented(self, edge: int, forward: bool = True) -> int:
        s = ".T." if forward else ".F."
        return self.add(f"ORIENTED_EDGE('',*,*,#{edge},{s})")

    def edge_loop(self, oriented_edges) -> int:
        refs = ",".join(f"#{e}" for e in oriented_edges)
        return self.add(f"EDGE_LOOP('',({refs}))")

    def vertex_loop(self, vertex: int) -> int:
        return self.add(f"VERTEX_LOOP('',#{vertex})")

    def face(self, bounds, surface: int, same_sense: bool = True) -> int:
        """`bounds`: list of (loop_id, is_outer, orientation)."""
        ids = []
        for loop, outer, orient in bounds:
            kind = "FACE_OUTER_BOUND" if outer else "FACE_BOUND"
            o = ".T." if orient else ".F."
            ids.append(self.add(f"{kind}('',#{loop},{o})"))
        refs = ",".join(f"#{b}" for b in ids)
        s = ".T." if same_sense else ".F."
        return self.add(f"ADVANCED_FACE('',({refs}),#{surface},{s})")

    def closed_shell(self, faces) -> int:
        refs = ",".join(f"#{f}" for f in faces)
        return self.add(f"CLOSED_SHELL('',({refs}))")

    def solid(self, shell: int, name: str = "") -> int:
        return self.add(f"MANIFOLD_SOLID_BREP('{name}',#{shell})")

    # -- product / context ---------------------------------------------------

    def context(self) -> int:
        app = self.add(
            "APPLICATION_CONTEXT('core data for automotive mechanical design processes')"
        )
        self.add(
            f"APPLICATION_PROTOCOL_DEFINITION('international standard',"
            f"'{self.schema.split()[0].lower()}',2020,#{app})"
        )
        self.product_context = self.add(f"PRODUCT_CONTEXT('',#{app},'mechanical')")
        self.pd_context = self.add(
            f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')"
        )
        length = self.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
        angle = self.add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
        solid = self.add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
        unc = self.add(
            f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-7),#{length},"
            f"'distance_accuracy_value','confusion accuracy')"
        )
        self.geom_context = self.add(
            f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) "
            f"GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{unc})) "
            f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{length},#{angle},#{solid})) "
            f"REPRESENTATION_CONTEXT('Context #1','3D Context') )"
        )
        return self.geom_context

    def product(self, name: str, pid: str) -> int:
        p = self.add(f"PRODUCT('{pid}','{name}','',(#{self.product_context}))")
        self.add(f"PRODUCT_RELATED_PRODUCT_CATEGORY('part','',(#{p}))")
        pdf = self.add(f"PRODUCT_DEFINITION_FORMATION('','',#{p})")
        return self.add(f"PRODUCT_DEFINITION('design','',#{pdf},#{self.pd_context})")

    def shape(self, pd: int, name: str, items) -> int:
        axis = self.axis2((0, 0, 0), (0, 0, 1), (1, 0, 0))
        refs = ",".join(f"#{i}" for i in [axis] + list(items))
        sr = self.add(
            f"ADVANCED_BREP_SHAPE_REPRESENTATION('{name}',({refs}),#{self.geom_context})"
        )
        pds = self.add(f"PRODUCT_DEFINITION_SHAPE('','',#{pd})")
        self.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{sr})")
        return sr

    def render(self) -> str:
        lines = [
            "ISO-10303-21;",
            "HEADER;",
            f"FILE_DESCRIPTION(('{self.name}'),'2;1');",
            f"FILE_NAME('{self.name}','2026-01-01T00:00:00',('taxila3d-fixtures'),"
            "('CoEdge'),'refresh_step_subset.py','taxila3d-fixtures','');",
            f"FILE_SCHEMA(('{SCHEMAS[self.schema]}'));",
            "ENDSEC;",
            "DATA;",
        ]
        lines.extend(self.records)
        lines.append("ENDSEC;")
        lines.append("END-ISO-10303-21;")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Shape builders — each returns (Step, [solid ids])
# ---------------------------------------------------------------------------


def build_box(s: Step, dx: float, dy: float, dz: float, name: str = "box"):
    """Axis-aligned box: 8 vertices, 12 line edges, 6 planar faces."""
    c = [
        (0, 0, 0), (dx, 0, 0), (dx, dy, 0), (0, dy, 0),
        (0, 0, dz), (dx, 0, dz), (dx, dy, dz), (0, dy, dz),
    ]
    v = [s.vertex(*p) for p in c]

    def seg(i: int, j: int) -> int:
        a, b = c[i], c[j]
        d = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        length = math.dist(a, b)
        unit = (d[0] / length, d[1] / length, d[2] / length)
        return s.edge(v[i], v[j], s.line(a, unit, length))

    e = {}
    for i, j in [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)]:
        e[(i, j)] = seg(i, j)

    def loop(pairs):
        return s.edge_loop([s.oriented(e[(a, b)], fwd) for a, b, fwd in pairs])

    faces = [
        # bottom (z=0), normal -Z
        s.face([(loop([(0, 1, True), (1, 2, True), (2, 3, True), (3, 0, True)]), True, True)],
               s.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), False),
        # top (z=dz), normal +Z
        s.face([(loop([(4, 5, True), (5, 6, True), (6, 7, True), (7, 4, True)]), True, True)],
               s.plane((0, 0, dz), (0, 0, 1), (1, 0, 0)), True),
        # front (y=0), normal -Y
        s.face([(loop([(0, 1, True), (1, 5, True), (4, 5, False), (0, 4, False)]), True, True)],
               s.plane((0, 0, 0), (0, -1, 0), (1, 0, 0)), True),
        # right (x=dx), normal +X
        s.face([(loop([(1, 2, True), (2, 6, True), (5, 6, False), (1, 5, False)]), True, True)],
               s.plane((dx, 0, 0), (1, 0, 0), (0, 1, 0)), True),
        # back (y=dy), normal +Y
        s.face([(loop([(2, 3, True), (3, 7, True), (6, 7, False), (2, 6, False)]), True, True)],
               s.plane((0, dy, 0), (0, 1, 0), (-1, 0, 0)), True),
        # left (x=0), normal -X
        s.face([(loop([(3, 0, True), (0, 4, True), (7, 4, False), (3, 7, False)]), True, True)],
               s.plane((0, 0, 0), (-1, 0, 0), (0, -1, 0)), True),
    ]
    return [s.solid(s.closed_shell(faces), name)]


def build_cylinder_seamless(s: Step, radius: float, height: float, name: str = "cyl"):
    """Cylinder whose lateral face is bounded ONLY by its two rim circles.

    No seam edge exists — the loops wind a full period each. This is the
    seam-healing regression case: without inserting a seam the lateral
    face has no closed UV boundary and cannot be triangulated.
    """
    v_bot = s.vertex(radius, 0, 0)
    v_top = s.vertex(radius, 0, height)
    c_bot = s.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), radius)
    c_top = s.circle((0, 0, height), (0, 0, 1), (1, 0, 0), radius)
    # Closed edges: start vertex == end vertex, full 2*pi span.
    e_bot = s.edge(v_bot, v_bot, c_bot)
    e_top = s.edge(v_top, v_top, c_top)

    lateral = s.face(
        [(s.edge_loop([s.oriented(e_bot, True)]), True, True),
         (s.edge_loop([s.oriented(e_top, False)]), False, True)],
        s.cylinder((0, 0, 0), (0, 0, 1), (1, 0, 0), radius),
        True,
    )
    cap_bot = s.face([(s.edge_loop([s.oriented(e_bot, False)]), True, True)],
                     s.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), True)
    cap_top = s.face([(s.edge_loop([s.oriented(e_top, True)]), True, True)],
                     s.plane((0, 0, height), (0, 0, 1), (1, 0, 0)), True)
    return [s.solid(s.closed_shell([lateral, cap_bot, cap_top]), name)]


def build_cone_seamless(s: Step, radius: float, height: float, name: str = "cone"):
    """Cone: full-period base circle, apex as a VERTEX_LOOP (pole)."""
    half_angle = math.atan2(radius, height)
    v_base = s.vertex(radius, 0, 0)
    v_apex = s.vertex(0, 0, height)
    c_base = s.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), radius)
    e_base = s.edge(v_base, v_base, c_base)

    lateral = s.face(
        [(s.edge_loop([s.oriented(e_base, True)]), True, True),
         (s.vertex_loop(v_apex), False, True)],
        s.cone((0, 0, 0), (0, 0, 1), (1, 0, 0), radius, half_angle),
        True,
    )
    cap = s.face([(s.edge_loop([s.oriented(e_base, False)]), True, True)],
                 s.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), True)
    return [s.solid(s.closed_shell([lateral, cap]), name)]


def build_sphere_seamless(s: Step, radius: float, name: str = "sphere"):
    """Sphere as one face closed by two pole VERTEX_LOOPs.

    Both parametric poles are degenerate; the face has no edge at all,
    so its whole UV boundary must be synthesized.
    """
    v_south = s.vertex(0, 0, -radius)
    v_north = s.vertex(0, 0, radius)
    face = s.face(
        [(s.vertex_loop(v_south), True, True), (s.vertex_loop(v_north), False, True)],
        s.sphere((0, 0, 0), (0, 0, 1), (1, 0, 0), radius),
        True,
    )
    return [s.solid(s.closed_shell([face]), name)]


def build_torus_seamless(s: Step, major: float, minor: float, name: str = "torus"):
    """Torus as a single face winding a full period in BOTH directions."""
    face = s.face([], s.torus((0, 0, 0), (0, 0, 1), (1, 0, 0), major, minor), True)
    # A bound-less ADVANCED_FACE is not legal Part 21; give it the
    # canonical pair of seam-less full-period circles instead.
    s.records.pop()
    v_outer = s.vertex(major + minor, 0, 0)
    c_outer = s.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), major + minor)
    e_outer = s.edge(v_outer, v_outer, c_outer)
    v_inner = s.vertex(major - minor, 0, 0)
    c_inner = s.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), major - minor)
    e_inner = s.edge(v_inner, v_inner, c_inner)
    upper = s.face(
        [(s.edge_loop([s.oriented(e_outer, True)]), True, True),
         (s.edge_loop([s.oriented(e_inner, False)]), False, True)],
        s.torus((0, 0, 0), (0, 0, 1), (1, 0, 0), major, minor),
        True,
    )
    lower = s.face(
        [(s.edge_loop([s.oriented(e_inner, True)]), True, True),
         (s.edge_loop([s.oriented(e_outer, False)]), False, True)],
        s.torus((0, 0, 0), (0, 0, 1), (1, 0, 0), major, minor),
        False,
    )
    return [s.solid(s.closed_shell([upper, lower]), name)]


def build_plate_with_hole(s: Step, size: float, thickness: float, hole_r: float,
                          name: str = "plate"):
    """Rectangular plate pierced by a cylindrical hole (inner loops)."""
    h = size / 2.0
    c_bot = [(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)]
    c_top = [(x, y, thickness) for x, y, _ in c_bot]
    v_bot = [s.vertex(*p) for p in c_bot]
    v_top = [s.vertex(*p) for p in c_top]

    def seg(a, b, va, vb):
        length = math.dist(a, b)
        d = ((b[0] - a[0]) / length, (b[1] - a[1]) / length, (b[2] - a[2]) / length)
        return s.edge(va, vb, s.line(a, d, length))

    e_bot = [seg(c_bot[i], c_bot[(i + 1) % 4], v_bot[i], v_bot[(i + 1) % 4]) for i in range(4)]
    e_top = [seg(c_top[i], c_top[(i + 1) % 4], v_top[i], v_top[(i + 1) % 4]) for i in range(4)]
    e_side = [seg(c_bot[i], c_top[i], v_bot[i], v_top[i]) for i in range(4)]

    # Hole: one closed circle per face, plus the bore surface.
    v_hb = s.vertex(hole_r, 0, 0)
    v_ht = s.vertex(hole_r, 0, thickness)
    e_hb = s.edge(v_hb, v_hb, s.circle((0, 0, 0), (0, 0, 1), (1, 0, 0), hole_r))
    e_ht = s.edge(v_ht, v_ht, s.circle((0, 0, thickness), (0, 0, 1), (1, 0, 0), hole_r))

    outer_bot = s.edge_loop([s.oriented(e, True) for e in e_bot])
    outer_top = s.edge_loop([s.oriented(e, True) for e in e_top])
    faces = [
        s.face([(outer_bot, True, True),
                (s.edge_loop([s.oriented(e_hb, True)]), False, True)],
               s.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), True),
        s.face([(outer_top, True, True),
                (s.edge_loop([s.oriented(e_ht, False)]), False, True)],
               s.plane((0, 0, thickness), (0, 0, 1), (1, 0, 0)), True),
    ]
    # Four side walls.
    normals = [(0, -1, 0), (1, 0, 0), (0, 1, 0), (-1, 0, 0)]
    refs = [(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0)]
    for i in range(4):
        j = (i + 1) % 4
        loop = s.edge_loop([
            s.oriented(e_bot[i], True),
            s.oriented(e_side[j], True),
            s.oriented(e_top[i], False),
            s.oriented(e_side[i], False),
        ])
        faces.append(s.face([(loop, True, True)],
                            s.plane(c_bot[i], normals[i], refs[i]), True))
    # Bore (seamless full-period cylinder).
    faces.append(s.face(
        [(s.edge_loop([s.oriented(e_hb, False)]), True, True),
         (s.edge_loop([s.oriented(e_ht, True)]), False, True)],
        s.cylinder((0, 0, 0), (0, 0, 1), (1, 0, 0), hole_r),
        False,
    ))
    return [s.solid(s.closed_shell(faces), name)]


def build_foreign_tetra(s: Step, scale: float, name: str = "tetra"):
    """Tetrahedron in a foreign-writer dialect.

    Exercises the parser and topology mapper rather than the surfaces:
    exponent floats, a non-unit VECTOR magnitude that makes the file's
    curve parameterization disagree with the kernel's, and a reversed
    (`.F.`) FACE_BOUND.
    """
    pts = [(0, 0, 0), (scale, 0, 0), (0, scale, 0), (0, 0, scale)]
    v = [s.vertex(*p) for p in pts]
    inv = 1.0 / math.sqrt(2.0)
    # Deliberately non-unit magnitude on the first edge.
    e01 = s.edge(v[0], v[1], s.line(pts[0], (1, 0, 0), scale * 2.0))
    e02 = s.edge(v[0], v[2], s.line(pts[0], (0, 1, 0)))
    e03 = s.edge(v[0], v[3], s.line(pts[0], (0, 0, 1)))
    e12 = s.edge(v[1], v[2], s.line(pts[1], (-inv, inv, 0)))
    e13 = s.edge(v[1], v[3], s.line(pts[1], (-inv, 0, inv)))
    e23 = s.edge(v[2], v[3], s.line(pts[2], (0, -inv, inv)))

    t = 1.0 / math.sqrt(3.0)
    faces = [
        # z=0, written A->B->C and flagged .F. (reversed bound).
        s.face([(s.edge_loop([s.oriented(e01, True), s.oriented(e12, True),
                              s.oriented(e02, False)]), False, False)],
               s.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), True),
        s.face([(s.edge_loop([s.oriented(e01, True), s.oriented(e13, True),
                              s.oriented(e03, False)]), True, True)],
               s.plane((0, 0, 0), (0, -1, 0), (1, 0, 0)), True),
        s.face([(s.edge_loop([s.oriented(e03, True), s.oriented(e23, False),
                              s.oriented(e02, False)]), True, True)],
               s.plane((0, 0, 0), (-1, 0, 0), (0, 0, 1)), True),
        s.face([(s.edge_loop([s.oriented(e12, True), s.oriented(e23, True),
                              s.oriented(e13, False)]), True, True)],
               s.plane(pts[1], (t, t, t), (1, -1, 0)), True),
    ]
    return [s.solid(s.closed_shell(faces), name)]


# ---------------------------------------------------------------------------
# Corpus definition
# ---------------------------------------------------------------------------


def single_part(name: str, schema: str, builder, *args, **kwargs) -> tuple[str, str]:
    s = Step(name, schema)
    s.context()
    solids = builder(s, *args, **kwargs)
    pd = s.product(name, name.upper())
    s.shape(pd, name, solids)
    return name, s.render()


def assembly_two_parts() -> tuple[str, str]:
    """Two parts under one assembly, the second placed by a transform."""
    s = Step("assembly_two_parts", "AP242")
    s.context()

    box_solids = build_box(s, 20, 10, 5, "box_part")
    pd_box = s.product("box_part", "P1")
    s.shape(pd_box, "box_part", box_solids)

    cyl_solids = build_cylinder_seamless(s, 4, 12, "cyl_part")
    pd_cyl = s.product("cyl_part", "P2")
    s.shape(pd_cyl, "cyl_part", cyl_solids)

    # Assembly product with an empty shape representation.
    pd_asm = s.product("assembly", "ASM")
    axis = s.axis2((0, 0, 0), (0, 0, 1), (1, 0, 0))
    sr = s.add(f"SHAPE_REPRESENTATION('assembly',(#{axis}),#{s.geom_context})")
    pds = s.add(f"PRODUCT_DEFINITION_SHAPE('','',#{pd_asm})")
    s.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{sr})")

    for child, label, placement in [
        (pd_box, "box_instance", ((0, 0, 0), (0, 0, 1), (1, 0, 0))),
        (pd_cyl, "cyl_instance", ((30, 5, 0), (0, 0, 1), (0, 1, 0))),
    ]:
        nauo = s.add(
            f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('{label}','{label}','',"
            f"#{pd_asm},#{child},$)"
        )
        ident = s.axis2((0, 0, 0), (0, 0, 1), (1, 0, 0))
        placed = s.axis2(*placement)
        idt = s.add(f"ITEM_DEFINED_TRANSFORMATION('','',#{ident},#{placed})")
        rel = s.add(
            "( REPRESENTATION_RELATIONSHIP('','',$,$) "
            f"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#{idt}) "
            "SHAPE_REPRESENTATION_RELATIONSHIP() )"
        )
        nauo_pds = s.add(f"PRODUCT_DEFINITION_SHAPE('','',#{nauo})")
        s.add(f"CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#{rel},#{nauo_pds})")

    return "assembly_two_parts", s.render()


def hybrid_box() -> tuple[str, str]:
    """AP242 hybrid: B-rep box + a linked tessellated representation."""
    s = Step("hybrid_box", "AP242")
    s.context()
    dx, dy, dz = 20.0, 10.0, 5.0
    solids = build_box(s, dx, dy, dz, "hybrid_box")
    pd = s.product("hybrid_box", "HB1")
    sr = s.shape(pd, "hybrid_box", solids)

    corners = [
        (0, 0, 0), (dx, 0, 0), (dx, dy, 0), (0, dy, 0),
        (0, 0, dz), (dx, 0, dz), (dx, dy, dz), (0, dy, dz),
    ]
    coords = ",".join(f"({r(x)},{r(y)},{r(z)})" for x, y, z in corners)
    clist = s.add(f"COORDINATES_LIST('',{len(corners)},({coords}))")
    # 12 triangles (1-based indices), two per box face.
    tris = [
        (1, 3, 2), (1, 4, 3), (5, 6, 7), (5, 7, 8),
        (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6),
        (3, 4, 8), (3, 8, 7), (4, 1, 5), (4, 5, 8),
    ]
    tri_text = ",".join(f"({a},{b},{c})" for a, b, c in tris)
    tface = s.add(
        f"TRIANGULATED_FACE('',#{clist},{len(corners)},(),$,(),({tri_text}))"
    )
    tsolid = s.add(f"TESSELLATED_SOLID('',(#{tface}),#{solids[0]})")
    tsr = s.add(
        f"TESSELLATED_SHAPE_REPRESENTATION('',(#{tsolid}),#{s.geom_context})"
    )
    s.add(f"SHAPE_REPRESENTATION_RELATIONSHIP('','',#{sr},#{tsr})")
    return "hybrid_box", s.render()


CORPUS = [
    # (filename, generator)
    ("box_ap242.step", lambda: single_part("box_ap242", "AP242", build_box, 20, 10, 5)),
    ("box_ap214.step", lambda: single_part("box_ap214", "AP214", build_box, 20, 10, 5)),
    ("box_ap203.step", lambda: single_part("box_ap203", "AP203", build_box, 20, 10, 5)),
    ("cylinder_seamless.step",
     lambda: single_part("cylinder_seamless", "AP242", build_cylinder_seamless, 6, 15)),
    ("cone_seamless.step",
     lambda: single_part("cone_seamless", "AP242", build_cone_seamless, 6, 12)),
    ("sphere_poles.step",
     lambda: single_part("sphere_poles", "AP242", build_sphere_seamless, 8)),
    ("torus_seamless.step",
     lambda: single_part("torus_seamless", "AP242", build_torus_seamless, 12, 3)),
    ("plate_with_hole.step",
     lambda: single_part("plate_with_hole", "AP242", build_plate_with_hole, 30, 4, 6)),
    ("tetra_foreign_dialect.step",
     lambda: single_part("tetra_foreign_dialect", "AP214", build_foreign_tetra, 40)),
    ("assembly_two_parts.step", assembly_two_parts),
    ("hybrid_box.step", hybrid_box),
]

# What each fixture is for — mirrored into CREDITS.csv.
PURPOSE = {
    "box_ap242.step": "planar B-rep baseline; AP242 schema",
    "box_ap214.step": "same geometry, AP214 schema (backward compat)",
    "box_ap203.step": "same geometry, AP203 schema (backward compat)",
    "cylinder_seamless.step": "full-period lateral face, no seam edge (seam healing)",
    "cone_seamless.step": "full-period face closed by an apex VERTEX_LOOP",
    "sphere_poles.step": "single face bounded only by two pole VERTEX_LOOPs",
    "torus_seamless.step": "two full-period faces on a torus (both directions periodic)",
    "plate_with_hole.step": "inner loops; closed-circle hole through a plate",
    "tetra_foreign_dialect.step":
        "foreign writer dialect: exponent floats, non-unit VECTOR, reversed FACE_BOUND",
    "assembly_two_parts.step": "NAUO assembly tree with an ITEM_DEFINED_TRANSFORMATION",
    "hybrid_box.step": "AP242 hybrid: B-rep + TESSELLATED_SHAPE_REPRESENTATION",
}


def main() -> None:
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR, exist_ok=True)

    rows = []
    for filename, generator in CORPUS:
        _, text = generator()
        path = os.path.join(OUT_DIR, filename)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        entities = text.count(";\n") - 8  # minus header/section markers
        rows.append({
            "file": filename,
            "schema": "AP242" if "ap242" in filename or filename not in
                      ("box_ap214.step", "box_ap203.step", "tetra_foreign_dialect.step")
                      else ("AP214" if "214" in filename or "tetra" in filename else "AP203"),
            "entities": max(entities, 0),
            "size_kib": round(os.path.getsize(path) / 1024, 1),
            "purpose": PURPOSE[filename],
            "source": "generated by scripts/refresh_step_subset.py",
            "license": "MIT (procedural generation)",
        })
        print(f"wrote {filename} ({rows[-1]['size_kib']} KiB)")

    credits = os.path.join(OUT_DIR, "CREDITS.csv")
    with open(credits, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["file", "schema", "entities", "size_kib", "purpose",
                            "source", "license"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote CREDITS.csv ({len(rows)} entries)")


if __name__ == "__main__":
    main()
