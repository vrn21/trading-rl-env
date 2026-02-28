"""tasks/__init__.py"""

from . import basic_tasks  # noqa: F401 — registers @env.scenario
from . import quant_tasks  # noqa: F401 — registers @env.scenario

__all__ = ["basic_tasks", "quant_tasks"]
