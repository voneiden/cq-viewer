import cadquery as cq
from cadquery.occ_impl.shapes import downcast_LUT
from OCP.TopoDS import TopoDS_Shape


def downcast(shape: TopoDS_Shape):
    return downcast_LUT[shape.ShapeType()](shape)


def same_topods_vertex(vx1: TopoDS_Shape, vx2: TopoDS_Shape):
    return cq.Vertex(vx1).Center() == cq.Vertex(vx2).Center()


def highlight_color(color: tuple[float, float, float], amount):
    def yoink(c: float):
        if c == 1.0:
            return c - amount
        return min(c + amount, 1)

    return tuple(yoink(c) for c in color)


def anti_color(color: tuple[float, float, float]):
    if sum(color) >= 1.5:
        return 0, 0, 0
    return 1, 1, 1
