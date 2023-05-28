import typing

import wx
from OCP.AIS import AIS_DisplayMode, AIS_InteractiveContext, AIS_SelectionScheme_Add
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
from OCP.Quantity import Quantity_Color
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

    def evt_left_up(self, event):
        left_up_pos = event.GetPosition()
        if not self._left_dragged:
            self.context.SelectDetected(AIS_SelectionScheme_Add)
            self.context.InitSelected()

            if self.context.NbSelected() > len(self.cq_viewer_ctx.selected_shapes):
                for i in range(len(self.cq_viewer_ctx.selected_shapes)):
                    self.context.NextSelected()
                self.cq_viewer_ctx.selected_shapes.append(self.context.SelectedShape())
                self.viewer.Update()
                self.cq_viewer_ctx.update_measurement()

            elif self.cq_viewer_ctx.selected_shapes:
                self.cq_viewer_ctx.selected_shapes = []
                self.context.ClearSelected(True)
                self.cq_viewer_ctx.update_measurement()

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
            if self.context.MoreDetected():
                self.cq_viewer_ctx.update_measurement(self.context.DetectedShape())

    def get_win_id(self):
        return self.GetHandle()

    def set_window(self):
        from OCP.Xw import Xw_Window

        window = Xw_Window(self.display_connection, self.get_win_id())
        self.view.SetWindow(window)
        if not window.IsMapped():
            window.Map()


class MainFrame(wx.Frame):
    def __init__(self, *args, cq_viewer_ctx: "CQViewerContext", **kwargs):
        super().__init__(
            None, *args, title="Title", style=wx.DEFAULT_FRAME_STYLE, **kwargs
        )
        cq_viewer_ctx.main_frame = self
        self.cq_viewer_ctx = cq_viewer_ctx

        self.canvas = V3dPanel(self, cq_viewer_ctx)
        self.Show()
        self.Maximize(True)
        self.canvas.set_window()
        self.Layout()
        self.resize_timer = wx.Timer(self)
        self.startup_timer = wx.Timer(self)

        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_TIMER, self.on_timer)
        self.Bind(wx.EVT_FSWATCHER, self.on_fs_watcher)

        self.startup_timer.StartOnce(1)

        self.file_system_watcher = None

    def on_timer(self, event):
        if event.GetTimer() == self.resize_timer:
            self.canvas.view.MustBeResized()
        if event.GetTimer() == self.startup_timer:
            self.startup()

    def startup(self):
        self.file_system_watcher = wx.FileSystemWatcher()
        self.file_system_watcher.SetOwner(self)

        if self.cq_viewer_ctx.file_path:
            self.cq_viewer_ctx.watch_file()
            self.cq_viewer_ctx.exec_and_display(fit=True)

    def on_size(self, event: wx.SizeEvent):
        self.resize_timer.Stop()
        self.resize_timer.StartOnce(50)
        self.Layout()

    def on_fs_watcher(self, event: wx.FileSystemWatcherEvent):
        if event.GetChangeType() == wx.FSW_EVENT_MODIFY:
            self.cq_viewer_ctx.exec_and_display()
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
        else:
            print(event.GetKeyCode())
