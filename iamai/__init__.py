"""IamAI — a small library that a long-running writer keeps editing."""

from .thoughts import Thought, append_thought, load_thoughts, search, stats
from .garden import Garden

__all__ = [
    "Thought",
    "append_thought",
    "load_thoughts",
    "search",
    "stats",
    "Garden",
]

__version__ = "0.1.0"
