import pytest
from build123d import (
    Box,
    Builder,
    BuildLine,
    BuildPart,
    BuildSketch,
    Circle,
    Cylinder,
    Line,
    Plane,
    Rectangle,
    extrude,
    make_face,
)

from cq_viewer.interface import (
    B123dBuildPart,
    ExecutionContext,
    knife_b123d,
    monkeypatch_b123d_builder_exit_factory,
)


@pytest.fixture
def knife_build123d(monkeypatch):
    builder_exit = monkeypatch_b123d_builder_exit_factory(None, Builder.__exit__)
    # build_line_exit = monkeypatch_b123d_builder_exit_factory(None, BuildLine.__exit__)
    monkeypatch.setattr(Builder, "__exit__", builder_exit)
    # monkeypatch.setattr(BuildLine, "__exit__", build_line_exit)


def test_b123d_unfinished_line_builder():
    with pytest.raises(RuntimeError):
        with BuildPart():
            with BuildSketch():
                with BuildLine():
                    Line((0, 0), (1, 1))


def test_b123d_unfinished_line_builder_knifed(knife_build123d):
    with BuildPart():
        with BuildSketch():
            with BuildLine():
                Line((0, 0), (1, 1))


def test_b123d_sketching_detection(knife_build123d):
    context = ExecutionContext()
    with BuildPart() as part:
        assert not B123dBuildPart(context, part, "test").sketch
        with BuildSketch():
            Circle(radius=5)
        assert B123dBuildPart(context, part, "test").sketch
        extrude(amount=5)
        assert not B123dBuildPart(context, part, "test").sketch

    with BuildPart() as part:
        assert not B123dBuildPart(context, part, "test").sketch
        with BuildSketch():
            with BuildLine():
                Line((0, 0), (1, 1))

    assert part.builder_parent is None
    assert B123dBuildPart(context, part, "test").sketch

    with BuildPart() as part:
        with BuildSketch():
            with BuildLine():
                Line((0, 0), (1, 1))
                Line((1, 1), (5, 1))
                Line((5, 1), (2, 4))
            make_face()
        extrude(amount=3)

    assert not B123dBuildPart(context, part, "test").sketch


def test_b123d_part_parent_behaviour():
    with BuildPart() as part:
        Box(1, 1, 1)

    with BuildPart() as part2:
        Cylinder(5, 10)

    assert part.builder_parent is None
    assert part2.builder_parent is None


def test_b123d_collect_pending(knife_build123d):
    from cq_viewer.util import collect_b3d_builder_pending as collect

    with BuildPart() as part1:
        with BuildSketch():
            with BuildLine():
                Line((0, 0), (1, 1))

    result = collect(part1)
    assert len(result) == 1
    assert len(result[0][0]) == 0
    assert len(result[0][1]) == 1
    assert len(result[0][2]) == 1

    with BuildPart() as part2:
        with BuildSketch():
            Rectangle(5, 5)
            with BuildLine():
                Line((0, 0), (1, 1))

    result = collect(part2)
    assert len(result) == 2
    assert len(result[0][0]) == 1
    assert len(result[0][1]) == 0
    assert len(result[0][2]) == 1
    assert len(result[1][0]) == 0
    assert len(result[1][1]) == 1
    assert len(result[1][2]) == 1

    with BuildPart() as part3:
        with BuildSketch(Plane.XZ) as sketch3:
            Rectangle(5, 5)

    result = collect(part3)
    assert len(result) == 1
    assert len(result[0][0]) == 1
    assert len(result[0][1]) == 0
    assert len(result[0][2]) == 1
