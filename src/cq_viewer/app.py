import logging
import pathlib
from typing import Optional

import cadquery as cq
import wx
from OCP.AIS import AIS_Shape
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX

from cq_viewer import wx_components
from cq_viewer.cq import exec_file, execution_context, knife_cq
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

    def exec_and_display(self, fit=False):
        ctx = self.main_frame.canvas.context
        execution_context.reset()
        _locals = exec_file(self.file_path)
        ctx.RemoveAll(False)

        for cq_obj in execution_context.cq_objects:
            if isinstance(cq_obj["obj"], cq.Workplane):
                compound = cq.Compound.makeCompound(cq_obj["obj"].objects)
            else:
                compound = cq.Compound.makeCompound(cq_obj["obj"])

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


def run():
    app = wx.App(False)
    cq_viewer_ctx = CQViewerContext()
    frame = MainFrame(cq_viewer_ctx=cq_viewer_ctx)
    knife_cq(frame)
    app.MainLoop()
