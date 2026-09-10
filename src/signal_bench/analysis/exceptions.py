# SPDX-License-Identifier: Apache-2.0
"""Exceptions and warnings for analysis helpers."""

from __future__ import annotations


class AnalysisError(Exception):
    """Base class for analysis helper failures."""


class InferenceNotFound(AnalysisError):  # noqa: N818 - public name is fixed by AD-06.
    """Raised when a run does not contain the requested inference sequence."""


class SourceNotInRun(AnalysisError):  # noqa: N818 - public name is fixed by AD-06.
    """Raised when a run has no telemetry samples for the requested source."""


class PartialRunWarning(UserWarning):
    """Warning emitted when partial-run-aware analysis sees an uncovered window."""
