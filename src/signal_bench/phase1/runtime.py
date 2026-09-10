# SPDX-License-Identifier: Apache-2.0
"""Runtime adapter interface for Phase 1 token-generation backends."""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Self


class HardwareRequired(RuntimeError):
    """Raised at the exact seam where a backend needs physical target access."""


@dataclass(frozen=True, slots=True)
class DecodeParams:
    """Frozen decoding knobs shared across Phase 1 targets."""

    temperature: float = 0.0
    top_p: float = 1.0
    seed: int = 42
    max_tokens: int = 32
    num_ctx: int = 4096


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    """Resolved runtime and model identity for reproducibility."""

    runtime_name: str
    runtime_version: str
    target_name: str
    backend: str
    model_name: str
    model_revision: str
    quantization: str | None
    model_bytes: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """One prompt-generation request."""

    prompt_id: str
    prompt: str
    decode: DecodeParams


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """One completed generation with timing and token accounting."""

    prompt_id: str
    started_at: dt.datetime
    finished_at: dt.datetime
    duration_ms: float
    first_token_ms: float
    tokens_in: int
    tokens_out: int
    text: str
    peak_memory_mb: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def tokens_per_second(self: Self) -> float:
        """Return output-token throughput for the completed generation."""
        duration_s = self.duration_ms / 1000.0
        return self.tokens_out / duration_s if duration_s > 0 else 0.0


class RuntimeAdapter(ABC):
    """Backend-neutral token generation adapter."""

    @abstractmethod
    def metadata(self: Self) -> RuntimeMetadata:
        """Return runtime, target, model, and quantization identity."""

    @abstractmethod
    def generate(self: Self, request: GenerationRequest) -> GenerationResult:
        """Run one deterministic generation request."""

    @abstractmethod
    def close(self: Self) -> None:
        """Release runtime resources."""
