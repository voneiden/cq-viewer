import logging
import os
import pathlib
from typing import Optional

import wx
from OCP.AIS import AIS_Shaded, AIS_Shape
from OCP.Aspect import Aspect_GDM_Lines, Aspect_GFM_VER, Aspect_GT_Rectangular
from OCP.gp import gp_Pln
from OCP.Graphic3d import Graphic3d_Camera
from OCP.Prs3d import Prs3d_Drawer
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from OCP.TopoDS import TopoDS_Shape

from cq_viewer import ais, wx_components
from cq_viewer.interface import exec_file, execution_context, knife_b123d, knife_cq
from cq_viewer.measurement import Measurement, create_measurement, create_midpoint
from cq_viewer.str_enum import StrEnum
from cq_viewer.util import (
    anti_color,
    color_str_to_quantity_color,
    highlight_color,
    pending_contains_edges,
    same_topods_vertex,
)
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

    @property
    def ctx(self):
        return self.main_frame.canvas.context

    def watch_file(self):
        self.main_frame.file_system_watcher.RemoveAll()
        self.main_frame.file_system_watcher.Add(str(self.file_path))

    def open_file(self) -> Optional[pathlib.Path]:
        current_file_path = self.config.Read(ConfigKey.FILE_PATH, "")
        current_dir = os.path.dirname(current_file_path) if current_file_path else ""

        with wx.FileDialog(
            self.main_frame,
            message="Open CQ file",
            defaultDir=current_dir,
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

    def exec_and_display(self, fit=False, reset_projection=False):
        print("EXEC & DISPLAY")
        execution_context.reset()
        _locals = exec_file(self.file_path)
        self.configure()
        self.display(fit, reset_projection)

    def configure(self):
        canvas = self.main_frame.canvas
        ctx = canvas.context
        view = canvas.view
        viewer = canvas.viewer
        config = execution_context.config

        if projection := config.get("projection"):
            if projection == "orthographic":
                view.Camera().SetProjectionType(
                    Graphic3d_Camera.Projection_Orthographic
                )
            elif projection == "perspective":
                view.Camera().SetProjectionType(Graphic3d_Camera.Projection_Perspective)
            else:
                raise ValueError(f"Invalid projection: {projection}")

        if bg_gradient := config.get("bg_gradient"):
            # TODO
            view.SetBgGradientColors(
                Quantity_Color(0.8, 0.8, 0.898, Quantity_TOC_RGB),
                Quantity_Color(0.0, 0.0, 0.0, Quantity_TOC_RGB),
                Aspect_GFM_VER,
                False,
            )
        elif bg := config.get("bg"):
            view.SetBackgroundColor(Quantity_Color(*bg, Quantity_TOC_RGB))
        else:
            view.SetBackgroundColor(
                Quantity_Color(0.117, 0.078, 0.368, Quantity_TOC_RGB)
            )

    def display(self, fit=False, reset_projection=False):
        print("Display..")
        ctx = self.main_frame.canvas.context
        view = self.main_frame.canvas.view
        previous_immediate_update = view.SetImmediateUpdate(False)
        ctx.RemoveAll(False)

        all_sketches = [dp_obj.sketch for dp_obj in execution_context.display_objects]
        active_sketches = [
            sketch
            for obj_sketches in [
                obj_sketches for obj_sketches in all_sketches if obj_sketches
            ]
            for sketch in obj_sketches
        ]
        contains_edges = pending_contains_edges(active_sketches)

        if active_sketches:
            if not execution_context.bp_sketching:
                planes = active_sketches[-1][2]
                if execution_context.bp_autosketch and len(planes) == 1:
                    print("Started sketching")
                    execution_context.bp_sketching = True
                    plane = planes[0]
                    execution_context.camera_scale = view.Camera().Scale()
                    view.SetViewOrientationDefault()
                    plane: gp_Pln
                    pos = plane.Position()
                    pos.Direction()
                    wp_dir = plane.Position().Direction().Reversed()
                    wp_up = plane.Position().YDirection()
                    view.Camera().SetDirection(wp_dir)
                    view.Camera().SetUp(wp_up)
                    # view.SetProj(-wp_ax.X(), -wp_ax.Y(), -wp_ax.Z())
                    # TODO how to determine twist?
                    # view.SetTwist(0)
                    fit = True
                    reset_projection = False
                    self.show_grid(plane)

        if active_sketches:
            sketching = True
            face_display_kwargs = (
                {"transparency": 0.8, "color": color_str_to_quantity_color("blue")}
                if contains_edges
                else {}
            )
            for faces, edges, _ in active_sketches:
                for face in faces:
                    self.display_ais_shape(AIS_Shape(face), **face_display_kwargs)
                for edge in edges:
                    self.display_ais_shape(AIS_Shape(edge))
        else:
            sketching = False

        if not sketching and execution_context.bp_sketching:
            print("Stopped sketching")
            execution_context.bp_sketching = False
            self.hide_grid()
            view.Reset(False)
            view.Camera().SetScale(execution_context.camera_scale)

        # Default behaviour
        for dp_obj in execution_context.display_objects:
            ais_objects = dp_obj.ais_objects
            color = dp_obj.options.get("color")
            transparency = (
                0.8 if sketching else None or dp_obj.options.get("transparency")
            )
            for ais_object in ais_objects:
                if isinstance(ais_object, AIS_Shape):
                    self.display_ais_shape(
                        ais_object,
                        selectable=not sketching,
                        color=color,
                        transparency=transparency,
                    )
                else:
                    ctx.Display(ais_object, False)

        if reset_projection:
            self.isometric()

        view.SetImmediateUpdate(previous_immediate_update)
        if fit:
            self.fit()
        self.main_frame.canvas.viewer.Update()

    def display_ais_shape(
        self, ais_shape: AIS_Shape, selectable=True, color=None, transparency=None
    ):
        if ais_shape is None:
            return

        ctx = self.main_frame.canvas.context
        ais_shape.SetHilightMode(AIS_Shaded)
        if not color:
            if ais_shape.HasColor():
                color = Quantity_Color()
                ais_shape.Color(color)
            else:
                color = Quantity_Color(
                    0.5019607843137255, 0, 0.5019607843137255, Quantity_TOC_RGB
                )
        if not transparency:
            ais_transparency = ais_shape.Transparency()
            if ais_transparency != 0:
                transparency = ais_transparency
        if transparency and (transparency < 0 or transparency > 1):
            raise ValueError("Transparency must be between 0 and 1")
        hilight_color = highlight_color(color, 0.05)
        select_color = highlight_color(color, 0.1)

        ais.set_color(
            ais_shape,
            color,
            transparency,
        )
        selection_style: Prs3d_Drawer = ais_shape.HilightAttributes()
        selection_style.SetColor(select_color)
        ais_shape.Attributes().SetupOwnFaceBoundaryAspect()
        ais_shape.Attributes().FaceBoundaryAspect().SetColor(
            Quantity_Color(*anti_color(color), Quantity_TOC_RGB)
        )

        highlight_style = ais_shape.DynamicHilightAttributes()
        highlight_style.SetColor(hilight_color)
        highlight_style.SetupOwnFaceBoundaryAspect()
        # highlight_style.FaceBoundaryAspect().SetColor does not work :-(
        # Make it at least a bit thicker..
        highlight_style.FaceBoundaryAspect().SetWidth(4)

        ctx.Display(ais_shape, False)
        if selectable:
            self.activate_selection(ais_shape)

    def show_grid(self, plane: gp_Pln):
        viewer = self.main_frame.canvas.viewer
        viewer.SetPrivilegedPlane(plane.Position())
        viewer.SetRectangularGridValues(0, 0, 1, 1, 0)
        # TODO determine the size of the grid?
        # TODO some way to mod the grid with keyboard
        viewer.SetRectangularGridGraphicValues(10, 10, 0)
        viewer.ActivateGrid(Aspect_GT_Rectangular, Aspect_GDM_Lines)

    def hide_grid(self):
        viewer = self.main_frame.canvas.viewer
        viewer.DeactivateGrid()

    def reset_view(self):
        if not execution_context.bp_sketching:
            self.isometric()
        self.fit()

    def fit(self):
        view = self.main_frame.canvas.view
        view.FitAll(0.2, False)

    def isometric(self, fit=False):
        view = self.main_frame.canvas.view
        view.SetProj(1, -1, 1)
        view.SetTwist(0)

        if fit:
            self.fit()

    def deactivate_selection(self, ais_shape: AIS_Shape):
        ctx = self.main_frame.canvas.context
        ctx.Deactivate(ais_shape)
        # ctx.SetSelectionModeActive(ais_shape, -1, False, AIS_SelectionModesConcurrency_Multiple)

    def activate_selection(self, ais_shape: AIS_Shape):
        self.deactivate_selection(ais_shape)
        ctx = self.main_frame.canvas.context
        ctx.Load(ais_shape)
        # ctx.SetSelectionModeActive(ais_shape, ais_shape.SelectionMode_s(TopAbs_VERTEX), True, AIS_SelectionModesConcurrency_Multiple)
        # ctx.SetSelectionModeActive(ais_shape, ais_shape.SelectionMode_s(TopAbs_EDGE), True, AIS_SelectionModesConcurrency_Multiple)
        # ctx.SetSelectionModeActive(ais_shape, ais_shape.SelectionMode_s(TopAbs_FACE), True, AIS_SelectionModesConcurrency_Multiple)

        ctx.Activate(ais_shape, ais_shape.SelectionMode_s(TopAbs_VERTEX), True)
        ctx.Activate(ais_shape, ais_shape.SelectionMode_s(TopAbs_EDGE), True)
        ctx.Activate(ais_shape, ais_shape.SelectionMode_s(TopAbs_FACE), True)

    def update_measurement(self, detected_shapes: Optional[list[TopoDS_Shape]] = None):
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
    knife_b123d(frame)
    app.MainLoop()


if __name__ == "__main__":
    run()
