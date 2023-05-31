import logging
import pathlib
from typing import Optional

import cadquery as cq
import wx
from OCP.AIS import AIS_Shaded, AIS_Shape
from OCP.gp import gp_Pnt
from OCP.Prs3d import Prs3d_Drawer
from OCP.Quantity import Quantity_Color, Quantity_NOC_RED
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from OCP.TopoDS import TopoDS_Shape, TopoDS_Vertex

from cq_viewer import wx_components
from cq_viewer.cq import (
    B123dBuildPart,
    WPObject,
    exec_file,
    execution_context,
    knife_cq,
)
from cq_viewer.measurement import Measurement, create_measurement, create_midpoint
from cq_viewer.str_enum import StrEnum
from cq_viewer.util import downcast, same_topods_vertex
from cq_viewer.wx_components import MainFrame

logger = logging.getLogger(__name__)


class ConfigKey(StrEnum):
    FILE_PATH = "file_path"


class CQViewerContext:
    def __init__(self):
        self.main_frame: Optional[wx_components.MainFrame] = None
        self.config = wx.FileConfig(
            appName="cq-viewer-v1", style=wx.CONFIG_USE_LOCAL_FILE
        )
        self.file_path = self.config.Read(ConfigKey.FILE_PATH, "") or None

        self.selected_shapes = []
        self.detected_shape = None
        self.measurement = Measurement.blank()
        self.midpoint: Optional[AIS_Shape] = None
        self.selected_midpoints: list[AIS_Shape] = []

    @property
    def selected_vx(self):
        return [
            shape
            for shape in self.selected_shapes
            if shape.ShapeType() == TopAbs_VERTEX
        ]

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
        for cq_obj in execution_context.display_objects:
            if isinstance(cq_obj, WPObject):
                index = execution_context.cq_wp_render_index[cq_obj.name]
                compound = cq.Compound.makeCompound(cq_obj.objects_by_index(index))
            elif isinstance(cq_obj, B123dBuildPart):
                compound = cq_obj.obj.part
            else:
                compound = cq.Compound.makeCompound(cq_obj.obj)

            shape = AIS_Shape(compound.wrapped)
            shape.SetHilightMode(AIS_Shaded)
            style: Prs3d_Drawer = shape.HilightAttributes()
            style.SetColor(Quantity_Color(Quantity_NOC_RED))

            ctx.Display(shape, False)
            ctx.Deactivate(shape)
            ctx.Activate(shape, shape.SelectionMode_s(TopAbs_VERTEX), True)
            ctx.Activate(shape, shape.SelectionMode_s(TopAbs_EDGE), True)
            ctx.Activate(shape, shape.SelectionMode_s(TopAbs_FACE), True)

            if fit:
                self.fit_and_project()

        else:
            self.main_frame.canvas.viewer.Update()

    def fit_and_project(self, x=1, y=-1, z=1):
        view = self.main_frame.canvas.view
        view.SetProj(1, -1, 1)
        view.SetTwist(0)
        view.FitAll()

    def update_measurement(self, detected_shapes: Optional[list[TopoDS_Shape]] = None):
        print("Update measurements")
        if self.selected_shapes:
            measurement_shapes = self.selected_shapes[:]
            if detected_shapes:
                # We use only the first hit for measurements!
                detected_shape = detected_shapes[0]
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

                self.measurement = create_measurement(*measurement_shapes)
                if self.measurement:
                    print("Measurements", self.measurement.measurements)
                    for ais_shape in self.measurement.ais_shapes:
                        ctx.Display(ais_shape, False)
                        # AddZLayer?
                    self.main_frame.canvas.viewer.Update()

                else:
                    print("No measurement")
                self.detected_shape = detected_shapes[0] if detected_shapes else None

        elif self.measurement:
            ctx = self.main_frame.canvas.context
            for ais_shape in self.measurement.ais_shapes:
                ctx.Remove(ais_shape, False)
            self.measurement = Measurement.blank()
            self.main_frame.canvas.viewer.Update()
        print("Update measurements done")
        self.main_frame.info_panel.update_info()

    def clean_up_selected_midpoints(self) -> bool:
        ctx = self.main_frame.canvas.context
        needs_update = False
        for selected_midpoint in self.selected_midpoints[:]:
            if not any(
                same_topods_vertex(selected_midpoint.Shape(), selected_vx)
                for selected_vx in self.selected_vx
            ):
                self.selected_midpoints.remove(selected_midpoint)
                print("MP: Removing selected midpoint")
                ctx.Remove(selected_midpoint, False)
                needs_update = True
        return needs_update

    def update_midpoint(self, detected_shape: Optional[TopoDS_Shape] = None):
        # A midpoint must be kept visible if
        # 1) create_midpoint suggests the same midpoint
        # 2) highlighted vertex is the same
        # 3) it is selected

        print("Update midpoints..")
        ctx = self.main_frame.canvas.context
        needs_update = False

        needs_update |= self.clean_up_selected_midpoints()

        new_midpoint = None
        highlighted_vertex = None
        if detected_shape:
            shape_type = detected_shape.ShapeType()
            if shape_type == TopAbs_EDGE:
                new_midpoint = create_midpoint(detected_shape)
                if any(
                    same_topods_vertex(new_midpoint.Shape(), selected_vx)
                    for selected_vx in self.selected_vx
                ):
                    # Don't need to show if it is already selected
                    print("MP: Already selected - NOP")
                    new_midpoint = None

            elif shape_type == TopAbs_VERTEX:
                highlighted_vertex = detected_shape

        if self.midpoint:
            if any(
                same_topods_vertex(self.midpoint.Shape(), selected_vx)
                for selected_vx in self.selected_shapes
                if selected_vx.ShapeType() == TopAbs_VERTEX
            ):
                self.selected_midpoints.append(self.midpoint)
                print("MP: Moving current midpoint to selected_midpoints")
                self.midpoint = None

            elif new_midpoint and same_topods_vertex(
                self.midpoint.Shape(), new_midpoint.Shape()
            ):
                # NOP - already showing the correct things
                print("MP: Already visible - NOP")
                new_midpoint = None
            elif highlighted_vertex and same_topods_vertex(
                self.midpoint.Shape(), highlighted_vertex
            ):
                # NOP - already showing the correct things
                print("MP: Already highlighted - NOP")
                new_midpoint = None
            else:
                print("MP: Removing unneeded midpoint")
                ctx.Remove(self.midpoint, False)
                self.midpoint = None
                needs_update = True

        if new_midpoint and self.midpoint is None:
            print("MP: Showing new midpoint")
            self.midpoint = new_midpoint
            ctx.Display(self.midpoint, False)
            needs_update = True

        if needs_update:
            self.main_frame.canvas.viewer.Update()


def run():
    app = wx.App(False)
    cq_viewer_ctx = CQViewerContext()
    frame = MainFrame(cq_viewer_ctx=cq_viewer_ctx)
    knife_cq(frame)
    app.MainLoop()


if __name__ == "__main__":
    run()
