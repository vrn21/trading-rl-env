"""tasks/__init__.py"""

from . import take_profit  # noqa: F401 — registers @env.scenario
from . import quant_tasks  # noqa: F401 — registers @env.scenario

__all__ = ["take_profit", "quant_tasks"]
