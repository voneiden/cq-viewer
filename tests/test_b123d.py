import pytest
from build123d import Builder, BuildLine, BuildPart, BuildSketch, Line

from cq_viewer.interface import knife_b123d


@pytest.fixture
def knife_build123d(monkeypatch):
    monkeypatch.setattr(Builder, "__exit__", lambda: None)
    knife_b123d(None)


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
