import logging
import pathlib
import sys
from typing import Optional

import cadquery as cq
import wx
from OCP.AIS import AIS_Line, AIS_Shaded, AIS_Shape
from OCP.BRepExtrema import BRepExtrema_DistShapeShape, BRepExtrema_ExtCC
from OCP.Geom import Geom_CartesianPoint
from OCP.gp import gp_Circ
from OCP.Prs3d import Prs3d_Drawer
from OCP.Quantity import Quantity_Color, Quantity_NOC_RED
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from OCP.TopoDS import TopoDS_Edge, TopoDS_Face, TopoDS_Shape, TopoDS_Vertex
from ocp_tessellate.ocp_utils import downcast_LUT

from cq_viewer import wx_components
from cq_viewer.cq import WPObject, exec_file, execution_context, knife_cq
from cq_viewer.str_enum import StrEnum
from cq_viewer.wx_components import MainFrame

logger = logging.getLogger(__name__)


class ConfigKey(StrEnum):
    FILE_PATH = "file_path"


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


class CQViewerContext:
    def __init__(self):
        self.main_frame: Optional[wx_components.MainFrame] = None
        self.config = wx.FileConfig(
            appName="cq-viewer-v1", style=wx.CONFIG_USE_LOCAL_FILE
        )
        self.file_path = self.config.Read(ConfigKey.FILE_PATH, "") or None

        self.selected_shapes = []
        self.detected_shape = None
        self.measurement = None

    def watch_file(self):
        self.main_frame.file_system_watcher.RemoveAll()
        self.main_frame.file_system_watcher.Add(str(self.file_path))

    def open_file(self) -> Optional[pathlib.Path]:
        with wx.FileDialog(
            self.main_frame,
            "Open CQ file",
            wildcard="Python files (*.py)|*.py",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return None

            # Proceed loading the file chosen by the user
            self.file_path = pathlib.Path(fileDialog.GetPath())
            self.config.Write(ConfigKey.FILE_PATH, str(self.file_path))
            self.config.Flush()
            self.watch_file()

            self.exec_and_display(fit=True)

    def increment_wp_render_index(self, name=None):
        execution_context.increment_wp_render_index(name)
        self.exec_and_display()

    def decrement_wp_render_index(self, name=None):
        execution_context.decrement_wp_render_index(name)
        self.exec_and_display()

    def exec_and_display(self, fit=False):
        execution_context.reset()
        _locals = exec_file(self.file_path)
        self.display(fit)

    def display(self, fit=False):
        ctx = self.main_frame.canvas.context
        ctx.RemoveAll(False)
        for cq_obj in execution_context.cq_objects:
            if isinstance(cq_obj, WPObject):
                index = execution_context.wp_render_index[cq_obj.name]
                compound = cq.Compound.makeCompound(cq_obj.objects_by_index(index))
            else:
                compound = cq.Compound.makeCompound(cq_obj.obj)

            shape = AIS_Shape(compound.wrapped)

            ctx.Display(shape, False)
            ctx.Deactivate(shape)
            ctx.Activate(shape, shape.SelectionMode_s(TopAbs_VERTEX), True)
            ctx.Activate(shape, shape.SelectionMode_s(TopAbs_EDGE), True)
            ctx.Activate(shape, shape.SelectionMode_s(TopAbs_FACE), True)

        if fit:
            view = self.main_frame.canvas.view
            view.SetProj(1, -1, 1)
            view.SetTwist(0)
            view.FitAll()

        else:
            self.main_frame.canvas.viewer.Update()

    def update_measurement(self, detected_shape=None):
        if self.selected_shapes:
            measurement_shapes = self.selected_shapes[:]
            if detected_shape:
                if not any(
                    detected_shape.IsSame(measurement_shape)
                    for measurement_shape in measurement_shapes
                ):
                    measurement_shapes.append(detected_shape)
            blank_measurement = Measurement(set())
            if blank_measurement != self.measurement:
                ctx = self.main_frame.canvas.context

                if self.measurement:
                    for ais_shape in self.measurement.ais_shapes:
                        ctx.Remove(ais_shape, False)

                self.measurement = self.create_measurement(*measurement_shapes)
                if self.measurement:
                    print("Measurements", self.measurement.measurements)
                    for ais_shape in self.measurement.ais_shapes:
                        ctx.Display(ais_shape, False)
                        # AddZLayer?
                    self.main_frame.canvas.viewer.Update()

                else:
                    print("No measurement")
                self.detected_shape = detected_shape

        elif self.measurement:
            ctx = self.main_frame.canvas.context
            for ais_shape in self.measurement.ais_shapes:
                ctx.Remove(ais_shape, False)
            self.measurement: Optional[Measurement] = None
            self.main_frame.canvas.viewer.Update()

    def create_measurement(self, *shapes: TopoDS_Shape):
        # Downcast shapes
        shape_types = [shape.ShapeType() for shape in shapes]
        downcasted_shapes = [downcast_LUT[shape.ShapeType()](shape) for shape in shapes]
        type_set = set(shape_types)
        print("Shape type set", type_set)
        if type_set == {TopAbs_EDGE}:
            return self.measure_edges(*downcasted_shapes)
        elif type_set == {TopAbs_FACE, TopAbs_EDGE}:
            pass
        elif type_set == {TopAbs_FACE}:
            return self.measure_faces(*downcasted_shapes)
        elif type_set == {TopAbs_VERTEX}:
            return self.measure_vertices(*downcasted_shapes)

    def measure_edges(self, *edges: TopoDS_Edge) -> Optional[Measurement]:
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
            min_distance = self.measure_min_distance_between_edges(*edges)
            if min_distance:
                return min_distance

            return Measurement(set(edges), measurements, ais_shapes)
        elif len(edges) >= 3:
            pass

        return None

    def measure_faces(self, *faces: TopoDS_Face) -> Optional[Measurement]:
        if len(faces) == 1:
            face = cq.Face(faces[0])
            return Measurement(set(faces), {"area": face.Area()})
        if len(faces) == 2:
            return self.measure_min_distance_between_shapes(*faces)

    def measure_face_edge(
        self, face: TopoDS_Face, edge: TopoDS_Edge
    ) -> Optional[Measurement]:
        pass

    def measure_vertices(self, *vertices: TopoDS_Vertex) -> Optional[Measurement]:
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
            return self.measure_min_distance_between_shapes(*vertices)

    def measure_max_distance_between_edges(
        self, edge1: TopoDS_Edge, edge2: TopoDS_Edge
    ):
        calc = BRepExtrema_ExtCC(edge1, edge2)
        print("Got results", calc.NbExt())
        if calc.NbExt():
            dist = calc.SquareDistance(1)
            p1 = calc.ParameterOnE1(1)
            p2 = calc.ParameterOnE2(1)
            ais = AIS_Line(p1, p2)
            return dist, ais

        return None

    def measure_min_distance_between_edges(
        self, edge1: TopoDS_Edge, edge2: TopoDS_Edge
    ):
        calc = BRepExtrema_DistShapeShape(edge1, edge2)
        if calc.IsDone():
            dist = calc.Value()
            p1 = calc.PointOnShape1(1)
            p2 = calc.PointOnShape2(1)
            return Measurement(
                {edge1, edge2},
                {"min_distance": dist},
                [AIS_Line(Geom_CartesianPoint(p1), Geom_CartesianPoint(p2))]
                if dist
                else [],
            )
        print("Failed to calc min dist")

    def measure_min_distance_between_shapes(
        self, shape1: TopoDS_Shape, shape2: TopoDS_Shape
    ):
        calc = BRepExtrema_DistShapeShape(shape1, shape2)
        if calc.IsDone():
            dist = calc.Value()
            p1 = calc.PointOnShape1(1)
            p2 = calc.PointOnShape2(1)
            return Measurement(
                {shape1, shape2},
                {"min_distance": dist},
                [AIS_Line(Geom_CartesianPoint(p1), Geom_CartesianPoint(p2))]
                if dist
                else [],
            )


def run():
    app = wx.App(False)
    cq_viewer_ctx = CQViewerContext()
    frame = MainFrame(cq_viewer_ctx=cq_viewer_ctx)
    knife_cq(frame)
    app.MainLoop()
