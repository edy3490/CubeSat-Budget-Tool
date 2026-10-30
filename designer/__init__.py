"""Idea -> CubeSat design: parser + parts table + budget engine + build plan."""
from .configurator import Design, design
from .pipeline import Result, run

__all__ = ["run", "Result", "design", "Design"]
