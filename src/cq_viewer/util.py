from cadquery.occ_impl.shapes import downcast_LUT
from OCP.TopoDS import TopoDS_Shape


def downcast(shape: TopoDS_Shape):
    return downcast_LUT[shape.ShapeType()](shape)
