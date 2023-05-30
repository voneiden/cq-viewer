import cadquery as cq
from cadquery.occ_impl.shapes import downcast_LUT
from OCP.TopoDS import TopoDS_Shape


def downcast(shape: TopoDS_Shape):
    return downcast_LUT[shape.ShapeType()](shape)


def same_topods_vertex(vx1: TopoDS_Shape, vx2: TopoDS_Shape):
    return cq.Vertex(vx1).Center() == cq.Vertex(vx2).Center()
