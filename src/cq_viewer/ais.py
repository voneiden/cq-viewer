from OCP.AIS import AIS_Shape
from OCP.Graphic3d import Graphic3d_MaterialAspect, Graphic3d_NOM_JADE
from OCP.Quantity import Quantity_Color


def set_color(ais: AIS_Shape, color: Quantity_Color, transparency=None):
    attrs = ais.Attributes()
    attrs.SetupOwnShadingAspect()
    attrs.ShadingAspect().SetMaterial(Graphic3d_MaterialAspect(Graphic3d_NOM_JADE))
    attrs.ShadingAspect().SetColor(color)
    if transparency is not None:
        attrs.ShadingAspect().SetTransparency(transparency)
