import typing

import wx
from OCP.AIS import (
    AIS_DisplayMode,
    AIS_InteractiveContext,
    AIS_SelectionScheme_Add,
    AIS_SelectionScheme_Remove,
)
from OCP.Aspect import (
    Aspect_DisplayConnection,
    Aspect_IS_SOLID,
    Aspect_TOL_SOLID,
    Aspect_TypeOfTriedronPosition,
)
from OCP.Graphic3d import (
    Graphic3d_AspectFillArea3d,
    Graphic3d_MaterialAspect,
    Graphic3d_NameOfMaterial_Gold,
)
from OCP.OpenGl import OpenGl_GraphicDriver
from OCP.Prs3d import Prs3d_Drawer
from OCP.Quantity import Quantity_Color, Quantity_NOC_GREEN, Quantity_NOC_RED
from OCP.V3d import V3d_Viewer

if typing.TYPE_CHECKING:
    from cq_viewer.app import CQViewerContext


class KeyboardHandlerMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)

    def on_key_down(self, event: wx.KeyEvent):
        self.Parent.on_key_down(event)


class V3dPanel(KeyboardHandlerMixin, wx.Panel):
    def __init__(self, parent, cq_viewer_ctx: "CQViewerContext"):
        super().__init__(parent)
        self.cq_viewer_ctx = cq_viewer_ctx
        self.display_connection = Aspect_DisplayConnection()
        self.graphics_driver = OpenGl_GraphicDriver(self.display_connection)
        self.viewer = V3d_Viewer(self.graphics_driver)
        self.view = self.viewer.CreateView()
        self.context = AIS_InteractiveContext(self.viewer)

        params = self.view.ChangeRenderingParams()
        params.NbMsaaSamples = 8
        params.IsAntialiasingEnabled = True

        self.view.TriedronDisplay(
            Aspect_TypeOfTriedronPosition.Aspect_TOTP_RIGHT_LOWER, Quantity_Color(), 0.1
        )

        viewer = self.viewer

        viewer.SetDefaultLights()
        viewer.SetLightOn()

        ctx = self.context

        ctx.SetDisplayMode(AIS_DisplayMode.AIS_Shaded, True)
        ctx.DefaultDrawer().SetFaceBoundaryDraw(True)
        # style: Prs3d_Drawer = ctx.SelectionStyle()
        style = Prs3d_Drawer()
        style.SetColor(Quantity_Color(Quantity_NOC_GREEN))
        fill_aspect = Graphic3d_AspectFillArea3d(
            Aspect_IS_SOLID,
            Quantity_Color(Quantity_NOC_RED),
            Quantity_Color(Quantity_NOC_RED),
            Aspect_TOL_SOLID,
            1.0,
            Graphic3d_MaterialAspect(Graphic3d_NameOfMaterial_Gold),
            Graphic3d_MaterialAspect(Graphic3d_NameOfMaterial_Gold),
        )
        # style.SetShadingAspect(Prs3d_ShadingAspect(fill_aspect))
        style.SetupOwnShadingAspect()
        shading_aspect = style.ShadingAspect()
        shading_aspect.SetColor(Quantity_Color(Quantity_NOC_RED))

        # ctx.SetSelectionStyle(style)
        # ctx.SetHighlightStyle(style)
        # ctx.SetHighlightStyle(Prs3d_TypeOfHighlight_LocalSelected, style)
        # ctx.SetHighlightStyle(Prs3d_TypeOfHighlight_LocalDynamic, style)
        # ctx.Display(test_ais(), True)
        self.view.SetProj(0, 0, 1)
        self.view.SetTwist(0)

        self.view.MustBeResized()
        self.view.Redraw()
        self.viewer.Redraw()

        self.Bind(wx.EVT_LEFT_DOWN, self.evt_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.evt_left_up)
        self.Bind(wx.EVT_MIDDLE_DOWN, self.evt_middle_down)
        self.Bind(wx.EVT_RIGHT_DOWN, self.evt_right_down)

        self._left_down_pos = False
        self._left_dragged = False
        self._middle_down_pos = False
        self._right_down_pos = False

        self.Bind(wx.EVT_MOUSEWHEEL, self.evt_mousewheel)
        self.Bind(wx.EVT_MOTION, self.evt_motion)

    def evt_left_down(self, event):
        self._left_down_pos = event.GetPosition()
        self._left_dragged = False
        x, y = self._left_down_pos
        self.view.StartRotation(x, y)

    def evt_left_up(self, event: wx.KeyEvent):
        if not self._left_dragged:
            if event.ShiftDown():
                self.context.SelectDetected(AIS_SelectionScheme_Remove)
            else:
                self.context.SelectDetected(AIS_SelectionScheme_Add)
            self.context.InitSelected()

            if self.context.NbSelected() and self.context.HasDetected():
                self.cq_viewer_ctx.selected_shapes = []
                while self.context.MoreSelected():
                    self.cq_viewer_ctx.selected_shapes.append(
                        self.context.SelectedShape()
                    )
                    self.context.NextSelected()

                self.cq_viewer_ctx.update_measurement()
                self.cq_viewer_ctx.clean_up_selected_midpoints()
                self.viewer.Update()

            elif self.cq_viewer_ctx.selected_shapes:
                self.cq_viewer_ctx.selected_shapes = []
                self.context.ClearSelected(True)
                self.cq_viewer_ctx.update_measurement()
                self.cq_viewer_ctx.clean_up_selected_midpoints()
                self.viewer.Update()

    def evt_middle_down(self, event):
        self._middle_down_pos = event.GetPosition()

    def evt_right_down(self, event):
        self._right_down_pos = event.GetPosition()
        x, y = self._right_down_pos
        self.view.StartZoomAtPoint(x, y)

    def evt_mousewheel(self, event):
        x, y = event.GetPosition()
        delta = event.GetWheelRotation()
        if event.GetWheelAxis() == wx.MOUSE_WHEEL_VERTICAL:
            ZOOM_STEP = 0.9
            factor = ZOOM_STEP if delta < 0 else 1 / ZOOM_STEP
            delta_factor = 10
            x_step = x + delta_factor if delta > 0 else x - delta_factor
            # self.view.SetZoom(factor)
            self.view.StartZoomAtPoint(x, y)
            self.view.ZoomAtPoint(x, y, x_step, y)

    def evt_motion(self, event):
        pos = event.GetPosition()
        x, y = pos
        if event.Dragging():
            if event.LeftIsDown():
                self._left_dragged = True
                self._left_down_pos = pos
                self.view.Rotation(x, y)

            if event.MiddleIsDown():
                dx, dy = pos - self._middle_down_pos
                self._middle_down_pos = pos
                self.view.Pan(dx, -dy)

            if event.RightIsDown():
                ox, oy = self._right_down_pos
                self._right_down_pos = pos
                self.view.ZoomAtPoint(ox, -oy, x, -y)
        else:
            self.context.MoveTo(x, y, self.view, True)
            self.context.InitDetected()
            all_detected = []
            while self.context.MoreDetected():
                if self.context.HasDetectedShape():
                    all_detected.append(self.context.DetectedShape())
                else:
                    print("!!! Detected was NOT a shape")

                self.context.NextDetected()
            if all_detected:
                self.cq_viewer_ctx.update_measurement(all_detected)
                self.cq_viewer_ctx.update_midpoint(all_detected[0])
            else:
                self.cq_viewer_ctx.update_measurement(None)
                self.cq_viewer_ctx.update_midpoint(None)

    def get_win_id(self):
        return self.GetHandle()

    def set_window(self):
        from OCP.Xw import Xw_Window

        print("canvas win id", self.get_win_id())
        window = Xw_Window(self.display_connection, self.get_win_id())
        self.view.SetWindow(window)
        if not window.IsMapped():
            window.Map()


class InfoPanel(wx.Panel):
    def __init__(self, parent, cq_viewer_ctx: "CQViewerContext", *args, **kwargs):
        super().__init__(parent, *args, size=wx.Size(100, 60), **kwargs)
        self.cq_viewer_ctx = cq_viewer_ctx
        self.measurements_hash = None
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.text_elements: list[wx.StaticText] = []

    def update_info(self):
        measurements = self.cq_viewer_ctx.measurement.measurements
        measurements_hash = hash(frozenset(measurements.items()))
        if measurements_hash != self.measurements_hash:
            self.sizer.Clear()
            for t in self.text_elements:
                t.Destroy()
            self.text_elements = []

            for k, v in measurements.items():
                t = wx.StaticText(self, label=f"{k}: {v}")
                self.text_elements.append(t)
                self.sizer.Add(t)
            self.SetSizerAndFit(self.sizer)


class MainFrame(wx.Frame):
    def __init__(self, *args, cq_viewer_ctx: "CQViewerContext", **kwargs):
        super().__init__(
            None, *args, title="Title", style=wx.DEFAULT_FRAME_STYLE, **kwargs
        )
        cq_viewer_ctx.main_frame = self
        self.cq_viewer_ctx = cq_viewer_ctx

        self.canvas = V3dPanel(self, cq_viewer_ctx)
        self.info_panel = InfoPanel(self, cq_viewer_ctx)

        print("info panel win id", self.info_panel.GetHandle())
        self.Maximize(True)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.canvas, 1, flag=wx.EXPAND | wx.ALL)
        self.sizer.Add(self.info_panel, 0, flag=wx.EXPAND | wx.ALL)
        self.SetSizerAndFit(self.sizer)
        self.Show()
        self.canvas.set_window()
        self.Layout()
        self.resize_timer = wx.Timer(self)
        self.startup_timer = wx.Timer(self)
        self.file_reload_timer = wx.Timer(self)

        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_TIMER, self.on_timer)
        self.Bind(wx.EVT_FSWATCHER, self.on_fs_watcher)

        self.startup_timer.StartOnce(1)

        self.file_system_watcher = None

    def on_timer(self, event):
        if event.GetTimer() == self.resize_timer:
            self.canvas.view.MustBeResized()
        elif event.GetTimer() == self.startup_timer:
            self.startup()
        elif event.GetTimer() == self.file_reload_timer:
            self.cq_viewer_ctx.exec_and_display()

    def startup(self):
        self.file_system_watcher = wx.FileSystemWatcher()
        self.file_system_watcher.SetOwner(self)

        if self.cq_viewer_ctx.file_path:
            self.cq_viewer_ctx.watch_file()
            self.cq_viewer_ctx.exec_and_display(fit=True, reset_projection=True)

    def on_size(self, event: wx.SizeEvent):
        self.resize_timer.Stop()
        self.resize_timer.StartOnce(50)
        self.Layout()

    def on_fs_watcher(self, event: wx.FileSystemWatcherEvent):
        if event.GetChangeType() == wx.FSW_EVENT_MODIFY:
            self.file_reload_timer.Stop()
            self.file_reload_timer.StartOnce(50)
        else:
            print("Unknown event type", event.GetChangeType())

    def on_key_down(self, event: wx.KeyEvent):
        # ctrl+o
        code = event.GetKeyCode()
        if event.ControlDown() and code == 79:
            self.cq_viewer_ctx.open_file()
        elif code == 90:
            # z
            self.cq_viewer_ctx.increment_wp_render_index()
        elif code == 88:
            # x
            self.cq_viewer_ctx.decrement_wp_render_index()
        elif code == 82:
            # r
            self.cq_viewer_ctx.isometric()
            self.cq_viewer_ctx.fit()
        else:
            print(event.GetKeyCode())
