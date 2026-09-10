# SPDX-License-Identifier: Apache-2.0
"""Serializable matrix export data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RunData:
    """Exported data for one benchmark run."""

    run_id: str
    started_at: str
    status: str
    duration_s: float | None
    iterations: int
    warmup_iterations: int
    model_hash: str | None
    quantization: str | None
    telemetry_partial: bool
    telemetry_partial_sources: list[str]
    latency_stats: dict[str, Any] | None
    energy_stats: dict[str, Any] | None
    warnings: list[str] = field(default_factory=list)
    partial_reasons: list[str] = field(default_factory=list)
    partial_inference_warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a YAML-safe mapping."""
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "status": self.status,
            "duration_s": self.duration_s,
            "iterations": self.iterations,
            "warmup_iterations": self.warmup_iterations,
            "model_hash": self.model_hash,
            "quantization": self.quantization,
            "telemetry_partial": self.telemetry_partial,
            "telemetry_partial_sources": self.telemetry_partial_sources,
            "partial_reasons": self.partial_reasons,
            "partial_inference_warnings": self.partial_inference_warnings,
            "latency_stats": self.latency_stats,
            "energy_stats": self.energy_stats,
            "warnings": self.warnings,
        }


@dataclass(frozen=True, slots=True)
class CellData:
    """Exported data for one task x target cell."""

    task: str
    target: str
    status: str
    runs: list[RunData] = field(default_factory=list)
    required_runs: int = 0
    eligible_run_count: int = 0
    missing_run_count: int = 0
    extra_run_count: int = 0
    ineligible_run_count: int = 0
    coverage_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a YAML-safe mapping."""
        return {
            "task": self.task,
            "target": self.target,
            "status": self.status,
            "required_runs": self.required_runs,
            "eligible_run_count": self.eligible_run_count,
            "missing_run_count": self.missing_run_count,
            "extra_run_count": self.extra_run_count,
            "ineligible_run_count": self.ineligible_run_count,
            "coverage_warnings": self.coverage_warnings,
            "runs": [run.to_dict() for run in self.runs],
        }


@dataclass(frozen=True, slots=True)
class MatrixData:
    """Complete matrix export payload."""

    schema_version: int
    matrix_name: str
    generated_at: str
    generated_from_runs: int
    cells: list[CellData]

    def to_dict(self) -> dict[str, Any]:
        """Return a YAML-safe mapping."""
        return {
            "schema_version": self.schema_version,
            "matrix_name": self.matrix_name,
            "generated_at": self.generated_at,
            "generated_from_runs": self.generated_from_runs,
            "cells": [cell.to_dict() for cell in self.cells],
        }
