"""grading/spec.py — Grade, SubGrade, and Grader base class.

Copied from coding-template. These are reusable across any HUD environment:
- SubGrade: a single scored component with a weight
- Grade: weighted combination of SubGrades → one final score
- Grader: base class all graders inherit from (implement compute_score)
"""

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

ValidateMode = Literal["baseline_fail", "golden_pass"]


@dataclass(kw_only=True, frozen=True)
class SubGrade:
    name: str
    score: float
    weight: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True, frozen=True)
class Grade:
    """Weighted combination of SubGrades → one float score in [0.0, 1.0]."""

    subscores: dict[str, float]
    weights: dict[str, float]
    metadata: dict[str, Any] | None = None

    @property
    def score(self) -> float:
        s = sum(self.subscores[k] * self.weights[k] for k in self.subscores)
        return float(np.clip(s, 0.0, 1.0))

    @staticmethod
    def from_subscores(subscores: list[SubGrade]) -> "Grade":
        return Grade(
            subscores={sg.name: sg.score for sg in subscores},
            weights={sg.name: sg.weight for sg in subscores},
            metadata={sg.name: sg.metadata for sg in subscores if sg.metadata},
        )


class Grader:
    """Base class for all graders. Subclasses implement compute_score()."""

    name: str = "BaseGrader"

    @classmethod
    def grade(cls, weight: float, **kwargs) -> SubGrade:
        result = cls.compute_score(**kwargs)
        score, metadata = result if isinstance(result, tuple) else (result, {})
        return SubGrade(name=cls.name, score=score, weight=weight, metadata=metadata)

    @classmethod
    def compute_score(cls, **kwargs) -> float | tuple[float, dict[str, Any]]:
        raise NotImplementedError
