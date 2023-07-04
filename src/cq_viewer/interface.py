import inspect
import logging
import traceback
from collections import defaultdict
from types import ModuleType
from typing import Literal, Optional

import wx
from OCP.AIS import AIS_InteractiveObject, AIS_Shape
from OCP.Quantity import Quantity_Color
from OCP.gp import gp_Pln
from OCP.TopoDS import TopoDS_Builder, TopoDS_Compound, TopoDS_Shape
from cq_editor.cq_utils import to_occ_color

from cq_viewer.conf import FAILED_BUILDERS_KEY
from cq_viewer.managers import ImportManager, PathManager

logger = logging.getLogger(__name__)

try:
    import cadquery as cq
except ImportError:
    cq = None

try:
    import build123d as b3d
except ImportError:
    b3d = None

if cq is None and b3d is None:
    raise RuntimeError("Neither cadquery or build123d was found installed")


def make_compound(shapes: list[TopoDS_Shape]) -> TopoDS_Compound:
    compound = TopoDS_Compound()
    compound_builder = TopoDS_Builder()
    compound_builder.MakeCompound(compound)
    for shape in shapes:
        compound_builder.Add(compound, shape)
    return compound


def extract_shape(obj) -> Optional[TopoDS_Shape]:
    if obj is None:
        return None

    if isinstance(obj, list):
        shapes = [extract_shape(item) for item in obj]
        shape_count = len(shapes)
        if shape_count == 0:
            return None
        elif shape_count == 1:
            return shapes[0]
        else:
            return make_compound(shapes)

    if cq:
        if isinstance(obj, cq.Workplane):
            return extract_shape(obj.objects)
        if isinstance(obj, cq.Shape):
            return obj.wrapped
    if b3d:
        if isinstance(obj, b3d.Shape):
            return obj.wrapped
        elif isinstance(obj, b3d.ShapeList):
            return extract_shape(list(obj))
        elif isinstance(obj, b3d.BuildPart):
            return extract_shape(obj.part)

    if isinstance(obj, (TopoDS_Shape)):
        return obj

    raise ValueError(f"Unable to extract shape from {type(obj)}!")


def color_str_to_quanity_color(color: str) -> Quantity_Color:
    import OCP.Quantity as Quantity

    if noc_color := getattr(Quantity, f"Quantity_NOC_{color.upper()}", None):
        return Quantity_Color(noc_color)
    raise ValueError(f"Unknown color {color}")


class DisplayObject:
    def __init__(self, context, obj, name, **options):
        self.context = context
        self.obj = obj
        self.name = name
        if color := options.get("color"):
            if isinstance(color, str):
                options["color"] = color_str_to_quanity_color(color)

        self.options = options

    @property
    def shape(self) -> TopoDS_Shape:
        return extract_shape(self.obj)

    @property
    def ais_object(self) -> Optional[AIS_InteractiveObject]:
        if isinstance(self.obj, AIS_InteractiveObject):
            return self.obj
        shape = self.shape
        if shape:
            ais_shape = AIS_Shape(shape)
            return ais_shape
        return None

    @property
    def sketch(self):
        return None

    @property
    def active_plane(self) -> Optional[gp_Pln]:
        return None


class CQWorkplane(DisplayObject):
    obj: "cq.Workplane"

    def __init__(self, context, obj, name, **options):
        super().__init__(context, obj, name, **options)

        self.wp_history = [obj]
        o = obj
        while o.parent:
            o = o.parent
            self.wp_history.append(o)

    def objects_by_index(self, index):
        safe_index = min(max(0, index), len(self.wp_history) - 1)
        return self.wp_history[safe_index].objects

    def active_plane(self):
        return self.obj.plane.toPln()


class B123dBuildPart(DisplayObject):
    obj: "b3d.Builder"

    def __init__(self, context, obj, name, **options):
        super().__init__(context, obj, name, **options)

    @property
    def _failed_sketch_build(self) -> Optional["b3d.Builder"]:
        failed_builders = getattr(self.obj, FAILED_BUILDERS_KEY, [])
        failed_sketch_builders = [
            builder
            for builder in failed_builders
            if isinstance(builder, b3d.BuildSketch)
        ]
        if failed_sketch_builders:
            return failed_sketch_builders[0]
        return None

    @property
    def sketch(self) -> Optional[tuple[TopoDS_Compound, Optional[gp_Pln]]]:
        builder = self._failed_sketch_build
        if not builder:
            builder = self.obj

        shapes = []
        pending_faces = getattr(builder, "pending_faces", [])
        pending_edges = getattr(builder, "pending_edges", [])

        if pending_faces:
            shapes += pending_faces
        if pending_edges:
            edge_compound = b3d.Compound.make_compound(pending_edges)
            for workplane in builder.workplanes_context.workplanes:
                shapes.append(workplane.from_local_coords(edge_compound))

        if shapes:
            return b3d.Compound.make_compound(shapes).wrapped, self.active_plane

        return None

    @property
    def active_plane(self) -> Optional[gp_Pln]:
        builder = self._failed_sketch_build
        if not builder:
            builder = self.obj

        pending_edges = getattr(builder, "pending_edges", [])
        pending_faces = getattr(builder, "pending_faces", [])
        if pending_edges:
            workplanes = builder.workplanes_context.workplanes
            if len(workplanes) == 1:
                return workplanes[0].wrapped
        if pending_faces:
            workplanes = builder.builder_children[-1].workplanes_context.workplanes
            if len(workplanes) == 1:
                return workplanes[0].wrapped
        # TODO this needs to be a lot more robust
        # workplanes = b3d.WorkplaneList(*pending_faces)
        # zdirs = set((plane.z_dir.to_tuple() for plane in workplanes))
        # if len(zdirs) == 1:
        #    return workplanes.workplanes[0].wrapped
        return None


class ExecutionContext:
    def __init__(self):
        self.display_objects: list[DisplayObject] = []
        self.cq_wp_render_index = defaultdict(lambda: 0)
        self.bp_sketching = False
        self.bp_autosketch = True
        self.pre_sketch_projection = None
        self.config = {}

    def add_display_object(self, cq_obj: DisplayObject):
        self.display_objects.append(cq_obj)

    def reset(self):
        self.display_objects = []

    @property
    def cq_wp_objects(self) -> list[CQWorkplane]:
        # noinspection PyTypeChecker
        return list(filter(lambda x: isinstance(x, CQWorkplane), self.display_objects))

    @property
    def bp_objects(self) -> list[B123dBuildPart]:
        # noinspection PyTypeChecker
        return list(
            filter(lambda x: isinstance(x, B123dBuildPart), self.display_objects)
        )

    @property
    def generic_objects(self) -> list[DisplayObject]:
        wp_objects = self.cq_wp_objects
        return [cq_obj for cq_obj in self.display_objects if cq_obj not in wp_objects]

    def cq_wp_objects_by_name(self, name: Optional[str] = None) -> list[cq_wp_objects]:
        if name is None:
            return self.cq_wp_objects
        return [wp_object for wp_object in self.cq_wp_objects if wp_object.name == name]

    def modify_cq_wp_render_index(self, i: int, name: Optional[str] = None):
        for wp_obj in self.cq_wp_objects_by_name(name):
            new_index = self.cq_wp_render_index[wp_obj.name] + i
            new_safe_index = max(min(new_index, len(wp_obj.wp_history)), 0)
            self.cq_wp_render_index[wp_obj.name] = new_safe_index

    def increment_wp_render_index(self, name: Optional[str] = None):
        self.modify_cq_wp_render_index(1, name)

    def decrement_wp_render_index(self, name: Optional[str] = None):
        self.modify_cq_wp_render_index(-1, name)

    @property
    def single_wp(self) -> Optional[CQWorkplane]:
        wp_objects = self.cq_wp_objects
        if len(wp_objects) == 0:
            return wp_objects[0]
        return None


execution_context = ExecutionContext()


def show_object(obj, name=None, options=None, **kwargs):
    """
    Similar to CQ-Editor, this method can be used to display
    various objects in the viewer.

    TODO this sucks make it better
    """
    if options:
        kwargs.update(options)

    if cq and isinstance(obj, cq.Workplane):
        if name is None:
            name = f"wp-{len(execution_context.cq_wp_objects)}"
        cq_obj = CQWorkplane(execution_context, obj, name=name, **kwargs)
    elif b3d and isinstance(obj, b3d.Builder):
        if name is None:
            name = f"part-{len(execution_context.bp_objects)}"
        # TODO need to grab the actual object out
        # reference to obj is mutable..r
        cq_obj = B123dBuildPart(execution_context, obj, name=name, **kwargs)
    else:
        if name is None:
            name = f"obj-{len(execution_context.generic_objects)}"
        cq_obj = DisplayObject(execution_context, obj, name=name, **kwargs)

    execution_context.add_display_object(cq_obj)


def setup(*, projection: Literal["orthographic", "perspective"] = None):
    execution_context.config = (lambda **kwargs: {**kwargs})(projection=projection)


def exec_file(file_path):
    with ImportManager():
        with PathManager(file_path):
            with open(file_path, "r") as f:
                ast = compile(f.read(), file_path, "exec")
            module = ModuleType("__cq_viewer_exec__")
            exec(ast, module.__dict__, module.__dict__)
            return module.__dict__


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


def get_root_builder(builder):
    while builder.builder_parent:
        builder = builder.builder_parent
    return builder


def tb_file_names_and_linenos(tb):
    stack = traceback.extract_tb(tb)
    stack.reverse()
    return [f"{frame.filename}:{frame.lineno} {frame.line}" for frame in stack]


def monkeypatch_b123d_builder_init_factory():
    from build123d.build_common import Builder

    og_init = Builder.__init__

    def monkeypatch_b123d_builder_init(self, *args, **kwargs):
        og_init(self, *args, **kwargs)
        self.builder_children = []

    return monkeypatch_b123d_builder_init


def monkeypatch_b123d_builder_exit_factory(win):
    from build123d.build_common import Builder

    og_exit = Builder.__exit__

    def monkeypatch_b123d_builder_exit(self, exception_type, exception_value, tb):
        wx.SafeYield(win)
        if self.builder_parent:
            if not hasattr(self.builder_parent, "builder_children"):
                self.builder_parent.builder_children = []
            self.builder_parent.builder_children.append(self)

        if exception_type is not None:
            self._current.reset(self._reset_tok)

            stack_str = "\n".join(tb_file_names_and_linenos(tb))
            if self.builder_parent:
                logger.debug(
                    f"Unclean exit\n{stack_str}\n{exception_type}: {exception_value}"
                )
                return

            logger.warning(
                f"Builder failed\n{stack_str}\n{exception_type.__name__}: {exception_value})"
            )
            return True
        try:
            return og_exit(self, exception_type, exception_value, traceback)
        except RuntimeError as ex:
            # Builder.__exit__ can raise RuntimeError when
            # the Builder returns a None. From the viewers perspective
            # we don't want this to be a fatal error as most likely this
            # is just an incomplete BuildSketch

            root_builder = get_root_builder(self)
            failed_builders = getattr(root_builder, FAILED_BUILDERS_KEY, [])
            failed_builders.append(self)
            setattr(root_builder, FAILED_BUILDERS_KEY, failed_builders)
            if self.builder_parent:
                return
            return True

    return monkeypatch_b123d_builder_exit


def knife_b123d(win):
    """
    Tweak build123d

    * Exception handling for builders to avoid crashing
    * wx yield in __exit__ of a builder to keep UI somewhat responsive
    * Empty BuildSketch handling to support (BuildLine visualization)

    """
    from build123d.build_common import Builder

    # NOTE: monkey patching __enter__ is not so straightforward
    # because it messes the `inspect.currentframe().f_back` hat trick
    # that build123d uses to keep track of build context
    # Builder.__init__ = monkeypatch_b123d_builder_init_factory()
    Builder.__exit__ = monkeypatch_b123d_builder_exit_factory(win)


def view():
    from build123d.build_common import Builder

    ctx = Builder._get_context()

    if ctx and ctx._python_frame == inspect.currentframe().f_back:
        show_object(ctx)
    else:
        print("Not builder ctx")
