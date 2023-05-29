import logging
import pathlib
from typing import Optional

import cadquery as cq
import wx
from OCP.AIS import AIS_Shaded, AIS_Shape
from OCP.Prs3d import Prs3d_Drawer
from OCP.Quantity import Quantity_Color, Quantity_NOC_RED
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from OCP.TopoDS import TopoDS_Shape

from cq_viewer import wx_components
from cq_viewer.cq import WPObject, exec_file, execution_context, knife_cq
from cq_viewer.measurement import Measurement, create_measurement, create_midpoints
from cq_viewer.str_enum import StrEnum
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
        self.midpoint_shapes: list[AIS_Shape] = []

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
            self.measurement: Optional[Measurement] = None
            self.main_frame.canvas.viewer.Update()
        print("Update measurements done")

    def update_midpoints(self, detected_shapes: Optional[list[TopoDS_Shape]] = None):
        print("Update midpoints..")
        ctx = self.main_frame.canvas.context
        # TODO this might be unnecessarily fancy

        midpoint_shapes = create_midpoints(detected_shapes)
        print("Midpoint shapes", midpoint_shapes)
        """
        for old_midpoint_ais_shape in self.midpoint_shapes:
            ctx.Remove(old_midpoint_ais_shape, False)
        for midpoint_ais_shape in midpoint_shapes:
            ctx.Display(midpoint_ais_shape, False)
        """

        unchanged = []
        added = []

        for old_ais_shape in self.midpoint_shapes:
            old_shape: TopoDS_Shape = old_ais_shape.Shape()
            if any(
                (old_shape.IsSame(detected_shape) for detected_shape in detected_shapes)
            ):
                unchanged.append(old_shape)
            else:
                ctx.Remove(old_ais_shape, False)

        for midpoint_ais_shape in midpoint_shapes:
            midpoint_shape: TopoDS_Shape = midpoint_ais_shape.Shape()
            if not any(
                (
                    midpoint_shape.IsSame(unchanged_shape)
                    for unchanged_shape in unchanged
                )
            ):
                ctx.Display(midpoint_ais_shape, False)

        self.midpoint_shapes = midpoint_shapes
        self.main_frame.canvas.viewer.Update()
        print("Update done..")


def run():
    app = wx.App(False)
    cq_viewer_ctx = CQViewerContext()
    frame = MainFrame(cq_viewer_ctx=cq_viewer_ctx)
    knife_cq(frame)
    app.MainLoop()


if __name__ == "__main__":
    run()
