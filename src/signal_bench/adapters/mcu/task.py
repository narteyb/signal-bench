# SPDX-License-Identifier: Apache-2.0
"""Task specification shared by MCU adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """Concrete task payload passed to adapter measurement calls.

    T2.8 will produce task-specific instances for keyword spotting, image
    classification, and anomaly detection. T1.2 only defines the stable shape
    that MCU and future adapters can consume.
    """

    task_id: str
    model_path: Path
    input_data_path: Path
    expected_output_shape: tuple[Any, ...] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
