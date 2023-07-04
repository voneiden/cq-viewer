from typing import Union

import cadquery as cq
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from cadquery.occ_impl.shapes import downcast_LUT
from OCP.TopoDS import TopoDS_Shape


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
