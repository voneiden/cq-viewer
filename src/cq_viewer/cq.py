import cadquery as cq
import wx


class ExecutionContext:
    def __init__(self):
        self.cq_objects = []

    def add_cq_object(self, cq_obj):
        self.cq_objects.append(cq_obj)

    def reset(self):
        self.cq_objects = []


execution_context = ExecutionContext()


def show_object(obj, name=None, options=None, **kwargs):
    """
    Similar to CQ-Editor, this method can be used to display
    various objects in the viewer.
    """
    if options:
        kwargs.update(options)

    execution_context.add_cq_object({"obj": obj, "name": name, "options": kwargs})


def exec_file(file_path):
    with open(file_path, "r") as f:
        ast = compile(f.read(), file_path, "exec")

    _locals = {}
    exec(ast, _locals)
    return _locals


def knife_cq(win):
    """
    Stab cadquery with a newObject function
    that does a wx yield
    """

    def yielding_newObject(self, objlist):
        wx.SafeYield(win)
        return self.original_newObject(objlist)

    cq.Workplane.original_newObject = cq.Workplane.newObject
    cq.Workplane.newObject = yielding_newObject
