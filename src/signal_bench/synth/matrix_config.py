# SPDX-License-Identifier: Apache-2.0
"""Matrix configuration schema and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from signal_bench.tasks import list_tasks

DEFAULT_KNOWN_TARGETS = frozenset(
    {
        "f401re",
        "nano33",
        "esp32s3",
        "pi5",
        "jetson",
        "m1max",
        "modal",
        "mock",
    },
)


class MatrixConfigError(ValueError):
    """Raised when a matrix config file fails schema validation."""


class MatrixDefaults(BaseModel):
    """Default per-cell execution expectations."""

    model_config = ConfigDict(extra="forbid")

    iterations: int = Field(gt=0)
    warmup_iterations: int = Field(ge=0)
    required_runs: int = Field(default=1, gt=0)
    latency_budget_ms: float | None = Field(default=None, gt=0)
    accuracy_threshold: float | None = None
    energy_budget_uwh: float | None = Field(default=None, gt=0)

    @field_validator("accuracy_threshold")
    @classmethod
    def _accuracy_in_unit_interval(cls, value: float | None) -> float | None:
        if value is not None and not 0 <= value <= 1:
            msg = "accuracy_threshold must be in [0, 1]"
            raise ValueError(msg)
        return value


class MatrixCell(BaseModel):
    """One task x target cell in the planned matrix."""

    model_config = ConfigDict(extra="forbid")

    task: str
    target: str
    iterations: int | None = Field(default=None, gt=0)
    warmup_iterations: int | None = Field(default=None, ge=0)
    required_runs: int | None = Field(default=None, gt=0)
    latency_budget_ms: float | None = Field(default=None, gt=0)
    accuracy_threshold: float | None = None
    energy_budget_uwh: float | None = Field(default=None, gt=0)
    notes: str | None = None

    @field_validator("accuracy_threshold")
    @classmethod
    def _accuracy_in_unit_interval(cls, value: float | None) -> float | None:
        if value is not None and not 0 <= value <= 1:
            msg = "accuracy_threshold must be in [0, 1]"
            raise ValueError(msg)
        return value


class MatrixExclusion(BaseModel):
    """One deliberately excluded matrix cell."""

    model_config = ConfigDict(extra="forbid")

    task: str
    target: str
    reason: str


class MatrixConfig(BaseModel):
    """Validated Post matrix configuration."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int
    name: str
    version: str
    description: str
    created: str
    tasks: list[str]
    targets: list[str]
    defaults: MatrixDefaults
    cells: list[MatrixCell]
    exclusions: list[MatrixExclusion] = Field(default_factory=list)
    phase_5_overrides: dict[str, dict[str, dict[str, Any]]] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _supported_schema_version(cls, value: int) -> int:
        if value != 1:
            msg = f"unsupported matrix schema_version: {value}"
            raise ValueError(msg)
        return value

    @field_validator("tasks", "targets")
    @classmethod
    def _non_empty_unique_strings(cls, value: list[str]) -> list[str]:
        if not value:
            msg = "must be non-empty"
            raise ValueError(msg)
        if len(value) != len(set(value)):
            msg = "must not contain duplicates"
            raise ValueError(msg)
        if any(not item.strip() for item in value):
            msg = "must contain non-empty strings"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _cross_reference(self: Self) -> Self:
        task_set, target_set = self._validate_declared_names()
        cell_pairs = self._validate_cells(task_set, target_set)
        self._validate_exclusions(task_set, target_set, cell_pairs)
        self._validate_overrides(task_set, target_set)
        return self

    def _validate_declared_names(self: Self) -> tuple[set[str], set[str]]:
        registered_tasks = set(list_tasks())
        unknown_tasks = sorted(set(self.tasks) - registered_tasks)
        if unknown_tasks:
            msg = f"unknown tasks: {', '.join(unknown_tasks)}"
            raise ValueError(msg)

        unknown_targets = sorted(set(self.targets) - DEFAULT_KNOWN_TARGETS)
        if unknown_targets:
            msg = f"unknown targets: {', '.join(unknown_targets)}"
            raise ValueError(msg)
        return set(self.tasks), set(self.targets)

    def _validate_cells(
        self: Self,
        task_set: set[str],
        target_set: set[str],
    ) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        for cell in self.cells:
            if cell.task not in task_set:
                msg = f"cell references task outside tasks list: {cell.task}"
                raise ValueError(msg)
            if cell.target not in target_set:
                msg = f"cell references target outside targets list: {cell.target}"
                raise ValueError(msg)
            pair = (cell.task, cell.target)
            if pair in pairs:
                msg = f"duplicate cell: {cell.task}/{cell.target}"
                raise ValueError(msg)
            pairs.add(pair)
        return pairs

    def _validate_exclusions(
        self: Self,
        task_set: set[str],
        target_set: set[str],
        pairs: set[tuple[str, str]],
    ) -> None:
        exclusion_pairs: set[tuple[str, str]] = set()
        for exclusion in self.exclusions:
            pair = (exclusion.task, exclusion.target)
            if exclusion.task not in task_set:
                msg = f"exclusion references task outside tasks list: {exclusion.task}"
                raise ValueError(msg)
            if exclusion.target not in target_set:
                msg = f"exclusion references target outside targets list: {exclusion.target}"
                raise ValueError(msg)
            if pair in exclusion_pairs:
                msg = f"duplicate exclusion: {exclusion.task}/{exclusion.target}"
                raise ValueError(msg)
            if pair in pairs:
                msg = (
                    "cell cannot be both included and excluded: "
                    f"{exclusion.task}/{exclusion.target}"
                )
                raise ValueError(msg)
            exclusion_pairs.add(pair)

    def _validate_overrides(self: Self, task_set: set[str], target_set: set[str]) -> None:
        for task, target_overrides in self.phase_5_overrides.items():
            if task not in task_set:
                msg = f"override references task outside tasks list: {task}"
                raise ValueError(msg)
            for target in target_overrides:
                if target not in target_set:
                    msg = f"override references target outside targets list: {target}"
                    raise ValueError(msg)


def load_matrix_config(path: str | Path) -> MatrixConfig:
    """Load and validate a matrix config YAML file."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    try:
        return MatrixConfig.model_validate(raw)
    except ValidationError as exc:
        msg = f"Invalid matrix config at {config_path}: {exc}"
        raise MatrixConfigError(msg) from exc
