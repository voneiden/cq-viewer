from collections import defaultdict
from typing import Optional

import cadquery as cq
import wx


class CQObject:
    def __init__(self, obj, name, **options):
        self.obj = obj
        self.name = name


class WPObject(CQObject):
    def __init__(self, obj, name, **options):
        super().__init__(obj, name, **options)

        self.wp_history = [obj]
        o = obj
        while o.parent:
            o = o.parent
            self.wp_history.append(o)

    def objects_by_index(self, index):
        safe_index = min(max(0, index), len(self.wp_history) - 1)
        return self.wp_history[safe_index].objects


class ExecutionContext:
    def __init__(self):
        self.cq_objects: list[CQObject] = []
        self.wp_render_index = defaultdict(lambda: 0)

    def add_cq_object(self, cq_obj: CQObject):
        self.cq_objects.append(cq_obj)

    def reset(self):
        self.cq_objects = []

    @property
    def generic_objects(self) -> list[CQObject]:
        wp_objects = self.wp_objects
        return [cq_obj for cq_obj in self.cq_objects if cq_obj not in wp_objects]

    @property
    def wp_objects(self) -> list[WPObject]:
        # noinspection PyTypeChecker
        return list(filter(lambda x: isinstance(x, WPObject), self.cq_objects))

    def wp_objects_by_name(self, name: Optional[str] = None) -> list[wp_objects]:
        if name is None:
            return self.wp_objects
        return [wp_object for wp_object in self.wp_objects if wp_object.name == name]

    def modify_wp_render_index(self, i: int, name: Optional[str] = None):
        for wp_obj in self.wp_objects_by_name(name):
            new_index = self.wp_render_index[wp_obj.name] + i
            new_safe_index = max(min(new_index, len(wp_obj.wp_history)), 0)
            self.wp_render_index[wp_obj.name] = new_safe_index

    def increment_wp_render_index(self, name: Optional[str] = None):
        self.modify_wp_render_index(1, name)

    def decrement_wp_render_index(self, name: Optional[str] = None):
        self.modify_wp_render_index(-1, name)

    @property
    def single_wp(self) -> Optional[WPObject]:
        wp_objects = self.wp_objects
        if len(wp_objects) == 0:
            return wp_objects[0]
        return None


execution_context = ExecutionContext()


def show_object(obj, name=None, options=None, **kwargs):
    """
    Similar to CQ-Editor, this method can be used to display
    various objects in the viewer.
    """
    if options:
        kwargs.update(options)

    if isinstance(obj, cq.Workplane):
        if name is None:
            name = f"wp-{len(execution_context.wp_objects)}"
        cq_obj = WPObject(obj, name=name, **kwargs)
    else:
        if name is None:
            name = f"obj-{len(execution_context.generic_objects)}"
        cq_obj = CQObject(obj, name=name, **kwargs)

    execution_context.add_cq_object(cq_obj)


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
