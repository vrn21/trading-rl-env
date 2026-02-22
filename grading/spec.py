"""grading/spec.py — Grade, SubGrade, and Grader base class.

Synced with coding-template/grading/spec.py (the canonical HUD spec).
Key differences from a naive implementation:
  - SubGrade has a `parameters` field (Grader.grade() passes kwargs there)
  - Grade.score asserts weights sum to 1.0 (so graders must use weights that sum to 1)
  - Grader.grade() passes kwargs as `parameters` to SubGrade
"""

import logging
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import numpy as np

logger = logging.getLogger(__name__)

ValidateMode = Literal["baseline_fail", "golden_pass"]


def validate_grader_name(name: str) -> str:
    if not name:
        raise ValueError("Grader name cannot be empty")
    if not name.isidentifier():
        raise ValueError("Grader name must be a valid Python identifier")
    return name


GraderName = Annotated[str, "A grader name containing only letters, underscores, and hyphens"]


@dataclass(kw_only=True, frozen=True)
class SubGrade:
    name: GraderName
    score: float
    weight: float
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        validate_grader_name(self.name)


@dataclass(kw_only=True, frozen=True)
class Grade:
    """The grade returned by a scenario."""

    subscores: dict[str, float]
    weights: dict[str, float]
    metadata: dict[str, Any] | None

    @property
    def score(self):
        assert self.subscores.keys() == self.weights.keys()
        assert np.isclose(sum(self.weights.values()), 1), \
            f"Weights must sum to 1.0, got {sum(self.weights.values())}"
        assert min(self.subscores.values()) >= 0
        assert max(self.subscores.values()) <= 1

        score = sum([self.subscores[key] * self.weights[key] for key in self.subscores.keys()])
        return np.clip(score, 0.0, 1.0)

    @staticmethod
    def from_subscores(subscores: list[SubGrade]) -> "Grade":
        # Handle duplicate names (suffix -1, -2, ...)
        name_counts: dict[str, int] = {}
        for sg in subscores:
            name_counts[sg.name] = name_counts.get(sg.name, 0) + 1

        subscores_dict = {}
        weights_dict = {}
        metadata_dict = {}
        name_usage: dict[str, int] = {}

        for sg in subscores:
            original_name = sg.name
            if name_counts[original_name] == 1:
                final_name = original_name
            else:
                name_usage[original_name] = name_usage.get(original_name, 0) + 1
                final_name = f"{original_name}-{name_usage[original_name]}"

            subscores_dict[final_name] = sg.score
            weights_dict[final_name] = sg.weight
            if sg.metadata:
                metadata_dict[final_name] = sg.metadata

        return Grade(subscores=subscores_dict, weights=weights_dict, metadata=metadata_dict)


class Grader:
    name: str = "BaseGrader"

    @classmethod
    def grade(cls, weight: float, **kwargs) -> SubGrade:
        """Grade and return a SubGrade."""
        result = cls.compute_score(**kwargs)

        if isinstance(result, tuple):
            score, metadata = result
        else:
            score = result
            metadata = {}

        # Only store JSON-safe primitives in parameters.
        # Portfolio and other objects are not hashable and would break
        # the frozen dataclass hash computation.
        _safe_types = (str, int, float, bool, type(None))
        safe_params = {k: v for k, v in kwargs.items() if isinstance(v, _safe_types)}

        return SubGrade(
            name=cls.name,
            score=score,
            weight=weight,
            parameters=safe_params,
            metadata=metadata,
        )

    @classmethod
    def compute_score(cls, **kwargs) -> float | tuple[float, dict[str, Any]]:
        """Compute a score between 0.0 and 1.0."""
        raise NotImplementedError("Subclasses must implement compute_score")

    @classmethod
    def any(cls, weight: float, subgrades: list[SubGrade]) -> SubGrade:
        """Return a SubGrade that passes if any of the subgrades pass."""
        max_score = max(sg.score for sg in subgrades)
        return SubGrade(
            name=f"{cls.name}_any",
            score=max_score,
            weight=weight,
            parameters={"subgrades": [sg.name for sg in subgrades]},
            metadata={"subgrades": [sg.name for sg in subgrades],
                      "subgrade_metadata": {sg.name: sg.metadata for sg in subgrades if sg.metadata}},
        )

    @classmethod
    def all(cls, weight: float, subgrades: list[SubGrade]) -> SubGrade:
        """Return a SubGrade that passes only if all subgrades pass."""
        min_score = min(sg.score for sg in subgrades)
        return SubGrade(
            name=f"{cls.name}_all",
            score=min_score,
            weight=weight,
            parameters={"subgrades": [sg.name for sg in subgrades]},
            metadata={"subgrades": [sg.name for sg in subgrades],
                      "subgrade_metadata": {sg.name: sg.metadata for sg in subgrades if sg.metadata}},
        )
