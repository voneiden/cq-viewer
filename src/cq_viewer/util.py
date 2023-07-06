from typing import Union

import cadquery as cq
from cadquery.occ_impl.shapes import downcast_LUT
from OCP.gp import gp_Pln
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.TopoDS import TopoDS_Compound, TopoDS_Edge, TopoDS_Face, TopoDS_Shape

try:
    import build123d as b3d
except ImportError:
    b3d = None


def downcast(shape: TopoDS_Shape):
    return downcast_LUT[shape.ShapeType()](shape)


def same_topods_vertex(vx1: TopoDS_Shape, vx2: TopoDS_Shape):
    return cq.Vertex(vx1).Center() == cq.Vertex(vx2).Center()


def quantity_to_tuple(color: Quantity_Color):
    return color.Red(), color.Green(), color.Blue()


def highlight_color(
    color: Union[tuple[float, float, float], Quantity_Color], amount
) -> Quantity_Color:
    def yoink(c: float):
        if c == 1.0:
            return c - amount
        return min(c + amount, 1)

    rgb = quantity_to_tuple(color) if isinstance(color, Quantity_Color) else color
    new_rgb = tuple(yoink(c) for c in rgb)
    return Quantity_Color(*new_rgb, Quantity_TOC_RGB)


def anti_color(color: tuple[float, float, float]):
    rgb = quantity_to_tuple(color) if isinstance(color, Quantity_Color) else color
    if sum(rgb) >= 1.5:
        return 0, 0, 0
    return 1, 1, 1


def color_str_to_quantity_color(color: str) -> Quantity_Color:
    import OCP.Quantity as Quantity

    if noc_color := getattr(Quantity, f"Quantity_NOC_{color.upper()}", None):
        return Quantity_Color(noc_color)
    raise ValueError(f"Unknown color {color}")


def collect_b3d_builder_pending(
    builder: "b3d.Builder",
) -> list[tuple[list[TopoDS_Face], list[TopoDS_Compound], list[gp_Pln]]]:
    pending = []
    pending_faces = getattr(builder, "pending_faces", [])
    pending_edges = getattr(builder, "pending_edges", [])
    workplanes = builder.workplanes_context.workplanes

    # Edges need to be transformed from local to global
    if pending_edges:
        edge_compound = b3d.Compound.make_compound(pending_edges)
        workplane_edge_compounds = []

        for workplane in builder.workplanes_context.workplanes:
            workplane_edge_compounds.append(workplane.from_local_coords(edge_compound))

        pending_edges = workplane_edge_compounds

    if pending_faces or pending_edges:
        if pending_edges:
            planes = [workplane.wrapped for workplane in workplanes]
        else:
            # For pending faces (from a BuildPart)
            # We want to use the plane of the last sketch
            builder_children = getattr(builder, "builder_children", [])
            if builder_children:
                planes = [
                    plane.wrapped
                    for plane in builder_children[-1].workplanes_context.workplanes
                ]
            else:
                print("Could not find planes!")
                planes = []

        pending = [
            (
                [face.wrapped for face in pending_faces],
                [compound.wrapped for compound in pending_edges],
                planes,
            )
        ]
    else:
        pending = []

    for child in getattr(builder, "builder_children", []):
        child_pending = collect_b3d_builder_pending(child)
        if child_pending:
            pending += child_pending

    return pending


def pending_contains_edges(
    pending: list[tuple[list[TopoDS_Face], list[TopoDS_Compound], list[gp_Pln]]]
):
    for _, edges, _ in pending:
        if edges:
            return True
    return False
