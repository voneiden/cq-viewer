"""
OCCT claims to support calculating maximum extrema
but either the feature was never quite finished or it
has been removed. So only minimum distances.

"""

import math
import sys
from typing import Callable, Optional

import cadquery as cq
from numpy import NaN, inf
from OCP.AIS import AIS_InteractiveObject, AIS_Line, AIS_Shape
from OCP.Aspect import Aspect_TOL_DASH, Aspect_TOL_DOT
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepExtrema import (
    BRepExtrema_DistShapeShape,
    BRepExtrema_ExtCC,
    BRepExtrema_ExtFF,
    BRepExtrema_ExtPC,
    BRepExtrema_ExtPF,
)
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.Extrema import (
    Extrema_ExtAlgo_Tree,
    Extrema_ExtFlag_MAX,
    Extrema_ExtFlag_MINMAX,
)
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.Geom import Geom_CartesianPoint
from OCP.gp import gp_Circ, gp_Pnt
from OCP.GProp import GProp_GProps
from OCP.Prs3d import Prs3d_LineAspect
from OCP.Quantity import Quantity_Color, Quantity_NOC_LIMEGREEN, Quantity_NOC_PURPLE
from OCP.Standard import Standard_OutOfRange
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_ON, TopAbs_VERTEX
from OCP.TopoDS import TopoDS_Edge, TopoDS_Face, TopoDS_Shape, TopoDS_Vertex
from ocp_tessellate.ocp_utils import downcast_LUT
from scipy.optimize import minimize

min_line_aspect = Prs3d_LineAspect(
    Quantity_Color(Quantity_NOC_LIMEGREEN), Aspect_TOL_DASH, 1
)

max_line_aspect = Prs3d_LineAspect(
    Quantity_Color(Quantity_NOC_PURPLE), Aspect_TOL_DOT, 1
)


def aspect_ais_line(
    p1: Geom_CartesianPoint, p2: Geom_CartesianPoint, aspect: Prs3d_LineAspect
):
    ais_line = AIS_Line(p1, p2)
    ais_line.Attributes().SetLineAspect(aspect)
    return ais_line


def min_ais_line(p1: Geom_CartesianPoint, p2: Geom_CartesianPoint):
    return aspect_ais_line(p1, p2, min_line_aspect)


def max_ais_line(p1: Geom_CartesianPoint, p2: Geom_CartesianPoint):
    return aspect_ais_line(p1, p2, max_line_aspect)


def face_area(face: TopoDS_Face) -> float:
    """From Cadquery"""
    Properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, Properties)

    return Properties.Mass()


class Measurement:
    def __init__(
        self,
        base_shapes: set[TopoDS_Shape],
        measurements: Optional[dict[str, str | int | float]] = None,
        ais_shapes: Optional[list[AIS_Shape | AIS_InteractiveObject]] = None,
    ):
        self.base_shapes = set(base_shapes)
        self.measurements: dict[str, str | int | float] = measurements or {}
        self.ais_shapes: Optional[list[AIS_Shape]] = ais_shapes or []

    def __hash__(self):
        return tuple(shape.HashCode(sys.maxsize) for shape in self.base_shapes)

    def __add__(self, other):
        if not isinstance(other, Measurement):
            raise TypeError("Cannot add non-measurements")

        return Measurement(
            self.base_shapes | other.base_shapes,
            {**self.measurements, **other.measurements},
            self.ais_shapes + other.ais_shapes,
        )

    def __bool__(self):
        return bool(self.base_shapes and self.measurements and self.ais_shapes)

    @classmethod
    def blank(cls, shapes=()):
        return Measurement(set(shapes), {}, [])


def create_measurement(*shapes: TopoDS_Shape):
    downcasted_shapes = [downcast_LUT[shape.ShapeType()](shape) for shape in shapes]
    return measure_generic(*downcasted_shapes)


# TODO reimplement!
def measure_edges(*edges: TopoDS_Edge) -> Measurement:
    measurements = {}
    ais_shapes = []
    print("Bonk edges", edges)
    if len(edges) == 1:
        # Measure edge length or radius/circumference
        print("EDGES", edges)
        edge = cq.Edge(edges[0])
        if edge.geomType() == "CIRCLE":
            circle: gp_Circ = edge._geomAdaptor().Circle()
            measurements["radius"] = circle.Radius()
            if edge.IsClosed():
                measurements["circumference"] = edge.Length()
            else:
                measurements["arc_length"] = edge.Length()
        else:
            measurements["length"] = edge.Length()
        return Measurement(set(edges), measurements, ais_shapes)


def measure_generic(*shapes: TopoDS_Shape) -> Measurement:
    print("Measure generic")
    measurement = Measurement.blank(shapes)
    type_set = set([shape.ShapeType() for shape in shapes])
    if len(shapes) == 1:
        if type_set == {TopAbs_VERTEX}:
            point = BRep_Tool.Pnt_s(shapes[0])
            measurement += Measurement(
                set(),
                {
                    "x": point.X(),
                    "y": point.Y(),
                    "z": point.Z(),
                },
                [],
            )
    elif len(shapes) == 2:
        # Distance measurements can be performed on two shapes
        if type_set == {TopAbs_FACE}:
            measurement += optimization_result_to_measurement(
                *optimize_face_face(shapes[0], shapes[1], maximize=False), False
            )
            measurement += optimization_result_to_measurement(
                *optimize_face_face(shapes[0], shapes[1], maximize=True), True
            )

        elif type_set == {TopAbs_FACE, TopAbs_EDGE}:
            face, edge = (
                (shapes[0], shapes[1])
                if shapes[0].ShapeType() == TopAbs_FACE
                else (shapes[1], shapes[0])
            )
            measurement += optimization_result_to_measurement(
                *optimize_face_edge(face, edge, maximize=False), False
            )
            measurement += optimization_result_to_measurement(
                *optimize_face_edge(face, edge, maximize=True), True
            )

        elif type_set == {TopAbs_FACE, TopAbs_VERTEX}:
            face, vertex = (
                (shapes[0], shapes[1])
                if shapes[0].ShapeType() == TopAbs_FACE
                else (shapes[1], shapes[0])
            )
            measurement += optimization_result_to_measurement(
                *optimize_face_vertex(face, vertex, maximize=False), False
            )
            measurement += optimization_result_to_measurement(
                *optimize_face_vertex(face, vertex, maximize=True), True
            )

        elif type_set == {TopAbs_EDGE}:
            measurement += optimization_result_to_measurement(
                *optimize_edge_edge(shapes[0], shapes[1], maximize=False), False
            )
            measurement += optimization_result_to_measurement(
                *optimize_edge_edge(shapes[0], shapes[1], maximize=True), True
            )

        elif type_set == {TopAbs_EDGE, TopAbs_VERTEX}:
            edge, vertex = (
                (shapes[0], shapes[1])
                if shapes[0].ShapeType() == TopAbs_EDGE
                else (shapes[1], shapes[0])
            )

            measurement += optimization_result_to_measurement(
                *optimize_edge_vertex(edge, vertex, maximize=False), False
            )
            measurement += optimization_result_to_measurement(
                *optimize_edge_vertex(edge, vertex, maximize=True), True
            )

        elif type_set == {TopAbs_VERTEX}:
            p1 = BRep_Tool.Pnt_s(shapes[0])
            p2 = BRep_Tool.Pnt_s(shapes[1])

            measurement += optimization_result_to_measurement(
                p1, p2, math.sqrt(p1.SquareDistance(p2)), False
            )
    if type_set == {TopAbs_FACE}:
        measurement += Measurement(
            set(), {"area": sum([face_area(shape) for shape in shapes])}, []
        )

    return measurement


def create_midpoint(edge: TopoDS_Edge) -> AIS_Shape:
    cq_edge = cq.Edge(edge)
    midpoint_vector = cq_edge.positionAt(0.5)
    vertex = cq.Vertex.makeVertex(*midpoint_vector.toTuple())
    return AIS_Shape(vertex.wrapped)


def edge_position_factory(edge: TopoDS_Edge):
    """Implementation borrowed from CadQuery"""
    curve = BRepAdaptor_Curve(edge)
    curve_length = GCPnts_AbscissaPoint.Length_s(curve)

    def edge_position(d: float) -> gp_Pnt:
        param = GCPnts_AbscissaPoint(
            curve, curve_length * d, curve.FirstParameter()
        ).Parameter()
        return curve.Value(param)

    return edge_position


def face_position_factory(face: TopoDS_Face):
    BRepTools.UpdateFaceUVPoints_s(face)
    surface = BRepAdaptor_Surface(face)
    u_min, u_max, v_min, v_max = BRepTools.UVBounds_s(face)

    def face_position(u: float, v: float) -> gp_Pnt:
        return surface.Value(u_min + (u_max - u_min) * u, v_min + (v_max - v_min) * v)

    return face_position


def edge_edge_distance_squared(
    params,
    epf1: Callable[[float], gp_Pnt],
    epf2: Callable[[float], gp_Pnt],
    maximize=False,
):
    param1, param2 = params
    point1 = epf1(param1)
    point2 = epf2(param2)

    if maximize:
        return -point1.SquareDistance(point2)
    return point1.SquareDistance(point2)


def face_edge_distance_squared_factory(face: TopoDS_Face):
    def face_edge_distance_squared(
        params,
        fpf: Callable[[float, float], gp_Pnt],
        epf: Callable[[float], gp_Pnt],
        maximize=False,
    ):
        up, uv, p = params
        face_point = fpf(up, uv)
        classifier = BRepClass_FaceClassifier(face, face_point, 1e-7)
        edge_point = epf(p)
        if maximize:
            if classifier.State() not in [TopAbs_IN, TopAbs_ON]:
                return inf
            return -face_point.SquareDistance(edge_point)
        if classifier.State() not in [TopAbs_IN, TopAbs_ON]:
            return -inf
        return face_point.SquareDistance(edge_point)

    return face_edge_distance_squared


def face_face_distance_squared_factory(face1: TopoDS_Face, face2: TopoDS_Face):
    def face_face_distance_squared(
        params,
        fpf1: Callable[[float, float], gp_Pnt],
        fpf2: Callable[[float, float], gp_Pnt],
        maximize=False,
    ):
        up1, uv1, up2, uv2 = params
        face1_point = fpf1(up1, uv1)
        face2_point = fpf2(up2, uv2)

        classifier1 = BRepClass_FaceClassifier(face1, face1_point, 1e-7)
        classifier2 = BRepClass_FaceClassifier(face2, face2_point, 1e-7)
        face1_point_within_face1 = classifier1.State() in [TopAbs_IN, TopAbs_ON]
        face2_point_within_face2 = classifier2.State() in [TopAbs_IN, TopAbs_ON]

        if maximize:
            if not (face1_point_within_face1 and face2_point_within_face2):
                return inf
            return -face1_point.SquareDistance(face2_point)
        if not (face1_point_within_face1 and face2_point_within_face2):
            return -inf
        return face1_point.SquareDistance(face2_point)

    return face_face_distance_squared


def face_vertex_distance_squared_factory(face: TopoDS_Face, vertex: TopoDS_Vertex):
    point = BRep_Tool.Pnt_s(vertex)

    def face_vertex_distance_squared(
        params, fpf: Callable[[float, float], gp_Pnt], maximize=False
    ):
        up, uv = params
        face_point = fpf(up, uv)
        classifier = BRepClass_FaceClassifier(face, face_point, 1e-7)
        if maximize:
            if classifier.State() not in [TopAbs_IN, TopAbs_ON]:
                return inf
            return -face_point.SquareDistance(point)
        if classifier.State() not in [TopAbs_IN, TopAbs_ON]:
            return -inf
        return face_point.SquareDistance(point)

    return face_vertex_distance_squared, point


def edge_vertex_distance_squared_factory(vertex: TopoDS_Vertex):
    point = BRep_Tool.Pnt_s(vertex)

    def edge_vertex_distance_squared(
        params, epf: Callable[[float], gp_Pnt], maximize=False
    ):
        p = params[0]
        edge_point = epf(p)
        if maximize:
            return -edge_point.SquareDistance(point)
        return edge_point.SquareDistance(point)

    return edge_vertex_distance_squared, point


def optimize_face_face(face1: TopoDS_Face, face2: TopoDS_Face, maximize=False):
    face_face_distance_squared = face_face_distance_squared_factory(face1, face2)

    param_bounds = [(0, 1), (0, 1), (0, 1), (0, 1)]

    initial_guess = [0.5, 0.5, 0.5, 0.5]

    fpf1 = face_position_factory(face1)
    fpf2 = face_position_factory(face2)

    result = minimize(
        face_face_distance_squared,
        x0=initial_guess,
        bounds=param_bounds,
        args=(fpf1, fpf2, maximize),
    )

    distance = math.sqrt(abs(result.fun))
    p1 = fpf1(result.x[0], result.x[1])
    p2 = fpf2(result.x[2], result.x[3])

    return p1, p2, distance


def optimize_face_edge(
    face: TopoDS_Face, edge: TopoDS_Edge, maximize=False
) -> tuple[gp_Pnt, gp_Pnt, float]:
    face_edge_distance_squared = face_edge_distance_squared_factory(face)
    param_bounds = [(0, 1), (0, 1), (0, 1)]

    initial_guess = [0.5, 0.5, 0.5]

    fpf = face_position_factory(face)
    epf = edge_position_factory(edge)

    result = minimize(
        face_edge_distance_squared,
        x0=initial_guess,
        bounds=param_bounds,
        args=(fpf, epf, maximize),
    )

    distance = math.sqrt(abs(result.fun))
    p1 = fpf(result.x[0], result.x[1])
    p2 = epf(result.x[2])

    return p1, p2, distance


def optimize_edge_edge(edge1: TopoDS_Edge, edge2: TopoDS_Edge, maximize=False):
    param_bounds = [(0, 1), (0, 1)]

    initial_guess = [0.5, 0.5]

    epf1 = edge_position_factory(edge1)
    epf2 = edge_position_factory(edge2)

    result = minimize(
        edge_edge_distance_squared,
        x0=initial_guess,
        bounds=param_bounds,
        args=(epf1, epf2, maximize),
    )

    distance = math.sqrt(abs(result.fun))
    p1 = epf1(result.x[0])
    p2 = epf2(result.x[1])

    print(result)

    return p1, p2, distance


def optimize_face_vertex(face: TopoDS_Face, vertex: TopoDS_Vertex, maximize=False):
    face_vertex_distance_squared, p2 = face_vertex_distance_squared_factory(
        face, vertex
    )
    param_bounds = [(0, 1), (0, 1)]

    initial_guess = [0.5, 0.5]

    fpf = face_position_factory(face)

    result = minimize(
        face_vertex_distance_squared,
        x0=initial_guess,
        bounds=param_bounds,
        args=(fpf, maximize),
    )

    distance = math.sqrt(abs(result.fun))
    print("result uv", result.x[0], result.x[1])
    p1 = fpf(result.x[0], result.x[1])

    return p1, p2, distance


def optimize_edge_vertex(edge: TopoDS_Edge, vertex: TopoDS_Vertex, maximize=False):
    edge_vertex_distance_squared, p2 = edge_vertex_distance_squared_factory(vertex)
    param_bounds = [(0, 1)]

    initial_guess = [0.5]

    epf = edge_position_factory(edge)

    result = minimize(
        edge_vertex_distance_squared,
        x0=initial_guess,
        bounds=param_bounds,
        args=(epf, maximize),
    )

    distance = math.sqrt(abs(result.fun))
    p1 = epf(result.x[0])

    return p1, p2, distance


def optimization_result_to_measurement(
    p1: gp_Pnt, p2: gp_Pnt, distance: float, maximize: bool
) -> Measurement:
    if distance == 0:
        return Measurement.blank()

    if maximize:
        ais_f = max_ais_line
        measurement_k = "max_distance"
    else:
        ais_f = min_ais_line
        measurement_k = "min_distance"

    return Measurement(
        set(),
        {measurement_k: distance},
        [ais_f(Geom_CartesianPoint(p1), Geom_CartesianPoint(p2))],
    )


if __name__ == "__main__":
    e1 = cq.Edge.makeLine((0, 0), (1, 0)).wrapped
    e2 = cq.Edge.makeLine((7, 2), (13, -5)).wrapped

    optimize_edge_edge(e1, e2, maximize=False)
