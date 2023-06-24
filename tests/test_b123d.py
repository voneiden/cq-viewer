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
    builder_exit = monkeypatch_b123d_builder_exit_factory(None)
    monkeypatch.setattr(Builder, "__exit__", builder_exit)


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
