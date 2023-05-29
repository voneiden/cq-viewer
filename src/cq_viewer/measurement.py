"""
OCCT claims to support calculating maximum extrema
but either the feature was never quite finished or it
has been removed. So only minimum distances.

"""

import math
import sys
from typing import Optional

import cadquery as cq
from OCP.AIS import AIS_Line, AIS_Shape
from OCP.Aspect import Aspect_TOL_DASH, Aspect_TOL_DOT
from OCP.BRepExtrema import (
    BRepExtrema_DistShapeShape,
    BRepExtrema_ExtCC,
    BRepExtrema_ExtFF,
    BRepExtrema_ExtPC,
    BRepExtrema_ExtPF,
)
from OCP.Extrema import (
    Extrema_ExtAlgo_Tree,
    Extrema_ExtFlag_MAX,
    Extrema_ExtFlag_MINMAX,
)
from OCP.Geom import Geom_CartesianPoint
from OCP.gp import gp_Circ, gp_Pnt
from OCP.Prs3d import Prs3d_LineAspect
from OCP.Quantity import Quantity_Color, Quantity_NOC_LIMEGREEN, Quantity_NOC_PURPLE
from OCP.Standard import Standard_OutOfRange
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from OCP.TopoDS import TopoDS_Edge, TopoDS_Face, TopoDS_Shape, TopoDS_Vertex
from ocp_tessellate.ocp_utils import downcast_LUT

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


class Measurement:
    def __init__(
        self,
        base_shapes: set[TopoDS_Shape],
        measurements: Optional[dict[str, str | int | float]] = None,
        ais_shapes: Optional[list[AIS_Shape]] = None,
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
            self.base_shapes & other.base_shapes,
            {**self.measurements, **other.measurements},
            self.ais_shapes + other.ais_shapes,
        )

    @classmethod
    def blank(cls):
        return Measurement(set(), {}, [])


def create_measurement(*shapes: TopoDS_Shape):
    # Downcast shapes
    shape_types = [shape.ShapeType() for shape in shapes]
    downcasted_shapes = [downcast_LUT[shape.ShapeType()](shape) for shape in shapes]
    type_set = set(shape_types)
    print("Shape type set", type_set)
    if type_set == {TopAbs_EDGE}:
        return measure_edges(*downcasted_shapes)
    elif type_set == {TopAbs_FACE, TopAbs_EDGE}:
        pass
    elif type_set == {TopAbs_FACE}:
        return measure_faces(*downcasted_shapes)
    elif type_set == {TopAbs_VERTEX}:
        return measure_vertices(*downcasted_shapes)

    else:
        return measure_generic(*downcasted_shapes)


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

    elif len(edges) == 2:
        min_distance = measure_min_distance_between_shapes(*edges)
        max_distance = measure_max_distance_between_edges(*edges)
        return min_distance + max_distance

    elif len(edges) >= 3:
        pass

    return Measurement.blank()


def measure_faces(*faces: TopoDS_Face) -> Measurement:
    if len(faces) == 1:
        face = cq.Face(faces[0])
        return Measurement(set(faces), {"area": face.Area()})
    if len(faces) == 2:
        min_distance = measure_min_distance_between_shapes(*faces)
        max_distance = measure_max_distance_between_faces(*faces)
        return min_distance + max_distance


def measure_face_edge(self, face: TopoDS_Face, edge: TopoDS_Edge) -> Measurement:
    return Measurement.blank()


def measure_vertices(*vertices: TopoDS_Vertex) -> Measurement:
    if len(vertices) == 1:
        vertex = cq.Vertex(vertices[0])
        return Measurement(
            set(vertices),
            {
                "x": vertex.X,
                "y": vertex.Y,
                "z": vertex.Z,
            },
            [],
        )
    elif len(vertices) == 2:
        return measure_min_distance_between_shapes(*vertices)


def measure_generic(*shapes: TopoDS_Shape) -> Measurement:
    print("Measure generic")
    if len(shapes) == 2:
        measurement = measure_min_distance_between_shapes(*shapes)
        type_set = set([shape.ShapeType() for shape in shapes])
        print("Generic type set", type_set)
        if type_set == {TopAbs_VERTEX, TopAbs_FACE}:
            vertex, face = (
                (shapes[0], shapes[1])
                if shapes[0].ShapeType() == TopAbs_VERTEX
                else (shapes[1], shapes[0])
            )
            return measurement + measure_max_distance_between_vertex_and_face(
                vertex, face
            )
        elif type_set == {TopAbs_VERTEX, TopAbs_EDGE}:
            vertex, edge = (
                (shapes[0], shapes[1])
                if shapes[0].ShapeType() == TopAbs_VERTEX
                else (shapes[1], shapes[0])
            )
            return measurement + measure_max_distance_between_vertex_and_edge(
                vertex, edge
            )
        return measurement


def measure_max_distance_between_vertex_and_face(
    vertex: TopoDS_Vertex, face: TopoDS_Face
) -> Measurement:
    calc = BRepExtrema_ExtPF(vertex, face, Extrema_ExtFlag_MAX, Extrema_ExtAlgo_Tree)
    # pnt = gp_Pnt(*cq.Vertex(vertex).toTuple())
    # surface = BRepAdaptor_Surface(face)
    # calc = Extrema_ExtPS(pnt, surface, 1e-4, 1e-4, Extrema_ExtFlag_MIN, Extrema_ExtAlgo_Tree)
    print("Results", calc.NbExt())

    if calc.NbExt():
        max_i = 1
        max_dist = calc.SquareDistance(1)
        for i in range(calc.NbExt() + 1)[2:]:
            print("CHecking i", i)
            if calc.SquareDistance(i) > max_dist:
                max_i = i

        dist = math.sqrt(calc.SquareDistance(max_i))
        point_on_face: gp_Pnt = calc.Point(max_i)
        vertex_point = Geom_CartesianPoint(gp_Pnt(*cq.Vertex(vertex).toTuple()))
        print("ppp", point_on_face.Coord(), "->", vertex_point.Coord())
        return Measurement(
            {vertex, face},
            {"max_distance": dist},
            [max_ais_line(Geom_CartesianPoint(point_on_face), vertex_point)]
            if dist > 0
            else [],
        )
    return Measurement.blank()


def measure_max_distance_between_vertex_and_edge(
    vertex: TopoDS_Vertex, edge: TopoDS_Edge
) -> Measurement:
    calc = BRepExtrema_ExtPC(vertex, edge)
    # pnt = gp_Pnt(*cq.Vertex(vertex).toTuple())
    # surface = BRepAdaptor_Surface(face)
    # calc = Extrema_ExtPS(pnt, surface, 1e-4, 1e-4, Extrema_ExtFlag_MIN, Extrema_ExtAlgo_Tree)
    print("Results", calc.NbExt())

    if calc.NbExt():
        max_i = 1
        max_dist = calc.SquareDistance(1)
        for i in range(calc.NbExt() + 1)[2:]:
            print("CHecking i", i)
            if calc.SquareDistance(i) > max_dist:
                max_i = i

        dist = math.sqrt(calc.SquareDistance(max_i))
        point_on_face: gp_Pnt = calc.Point(max_i)
        vertex_point = Geom_CartesianPoint(gp_Pnt(*cq.Vertex(vertex).toTuple()))
        print("ppp", point_on_face.Coord(), "->", vertex_point.Coord())
        return Measurement(
            {vertex, edge},
            {"max_distance": dist},
            [max_ais_line(Geom_CartesianPoint(point_on_face), vertex_point)]
            if dist > 0
            else [],
        )
    return Measurement.blank()


def measure_max_distance_between_edges(
    edge1: TopoDS_Edge, edge2: TopoDS_Edge
) -> Measurement:
    calc = BRepExtrema_ExtCC(edge1, edge2)
    print("Results", calc.NbExt())
    if calc.NbExt():
        max_i = 1
        max_dist = calc.SquareDistance(1)
        for i in range(calc.NbExt() + 1)[2:]:
            print("CHecking i", i)
            if calc.SquareDistance(i) > max_dist:
                max_i = i

        dist = math.sqrt(calc.SquareDistance(max_i))

        try:
            point_on_e1: gp_Pnt = calc.PointOnE1(max_i)
            point_on_e2: gp_Pnt = calc.PointOnE2(max_i)
        except Standard_OutOfRange:
            # This algorithm blows up sometimes
            return Measurement.blank()

        p1 = Geom_CartesianPoint(point_on_e1)
        p2 = Geom_CartesianPoint(point_on_e2)

        print("ppp", p1.Coord(), "->", p2.Coord())
        return Measurement(
            {edge1, edge2},
            {"max_distance": dist},
            [max_ais_line(p1, p2)] if dist > 0 else [],
        )
    return Measurement.blank()


def measure_max_distance_between_faces(
    face1: TopoDS_Face, face2: TopoDS_Face
) -> Measurement:
    calc = BRepExtrema_ExtFF(face1, face2)
    print("Results", calc.NbExt())
    if calc.NbExt():
        max_i = 1
        max_dist = calc.SquareDistance(1)
        for i in range(calc.NbExt() + 1)[2:]:
            print("CHecking i", i)
            if calc.SquareDistance(i) > max_dist:
                max_i = i

        dist = math.sqrt(calc.SquareDistance(max_i))

        try:
            point_on_f1: gp_Pnt = calc.PointOnFace1(max_i)
            point_on_f2: gp_Pnt = calc.PointOnFace2(max_i)
        except Standard_OutOfRange:
            return Measurement.blank()

        p1 = Geom_CartesianPoint(point_on_f1)
        p2 = Geom_CartesianPoint(point_on_f2)

        print("ppp", p1.Coord(), "->", p2.Coord())
        return Measurement(
            {face1, face2},
            {"max_distance": dist},
            [max_ais_line(p1, p2)] if dist > 0 else [],
        )
    return Measurement.blank()


def measure_min_distance_between_shapes(
    shape1: TopoDS_Shape, shape2: TopoDS_Shape
) -> Measurement:
    calc = BRepExtrema_DistShapeShape(
        shape1, shape2, Extrema_ExtFlag_MINMAX, Extrema_ExtAlgo_Tree
    )
    print("solutions", calc.NbSolution())
    if calc.IsDone():
        dist = calc.Value()
        p1 = calc.PointOnShape1(1)
        p2 = calc.PointOnShape2(1)

        return Measurement(
            {shape1, shape2},
            {"min_distance": dist},
            [min_ais_line(Geom_CartesianPoint(p1), Geom_CartesianPoint(p2))]
            if dist
            else [],
        )
    return Measurement.blank()


def create_midpoints(edges: list[TopoDS_Edge]) -> list[AIS_Shape]:
    shapes = []
    for edge in edges:
        if edge.ShapeType() != TopAbs_EDGE:
            continue

        cq_edge = cq.Edge(edge)
        midpoint_vector = cq_edge.positionAt(0.5)
        vertex = cq.Vertex.makeVertex(*midpoint_vector.toTuple())
        shapes.append(AIS_Shape(vertex.wrapped))
    return shapes
