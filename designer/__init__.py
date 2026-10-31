"""Idea -> CubeSat design: parser + parts table + budget engine + build plan."""
from .configurator import Design, design
from .pipeline import Result, from_spec, run

__all__ = ["run", "from_spec", "Result", "design", "Design"]
