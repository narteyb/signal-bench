# SPDX-License-Identifier: Apache-2.0
"""ASCII frame parsing for MCU USB-serial adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, ClassVar, Self

RUN_FIELD_COUNT = 2
RESULT_FIELD_COUNT = 3
ERR_FIELD_COUNT = 2


@dataclass(frozen=True, slots=True)
class Frame:
    """Base type for newline-delimited MCU protocol frames."""

    tag: ClassVar[str]

    @classmethod
    def parse_payload(cls: type[Self], _payload: str) -> Self:
        """Parse the tag-specific payload into a typed frame instance."""
        msg = f"{cls.__name__} does not implement parse_payload"
        raise NotImplementedError(msg)

    def serialize(self: Self) -> str:
        """Serialize the frame to one newline-terminated ASCII line."""
        msg = f"{type(self).__name__} does not implement serialize"
        raise NotImplementedError(msg)


@dataclass(frozen=True, slots=True)
class RunFrame(Frame):
    """Host-emitted command requesting task execution."""

    tag: ClassVar[str] = "RUN"

    task_id: str
    iterations: int

    @classmethod
    def parse_payload(cls: type[RunFrame], payload: str) -> RunFrame:
        """Parse `RUN <task_id> <iterations>`."""
        fields = payload.split(maxsplit=1)
        if len(fields) != RUN_FIELD_COUNT:
            msg = "RUN frame requires task_id and iterations"
            raise ValueError(msg)
        return cls(task_id=fields[0], iterations=_parse_int(fields[1], "iterations"))

    def serialize(self: Self) -> str:
        """Serialize this run request."""
        return f"{self.tag} {self.task_id} {self.iterations}\n"


@dataclass(frozen=True, slots=True)
class ResultFrame(Frame):
    """Device-emitted per-inference result."""

    tag: ClassVar[str] = "RESULT"

    iter_id: int
    output: Any
    duration_us: int

    @classmethod
    def parse_payload(cls: type[ResultFrame], payload: str) -> ResultFrame:
        """Parse `RESULT <iter_id> <duration_us> <json_output>`."""
        fields = payload.split(maxsplit=2)
        if len(fields) != RESULT_FIELD_COUNT:
            msg = "RESULT frame requires iter_id, duration_us, and output"
            raise ValueError(msg)
        return cls(
            iter_id=_parse_int(fields[0], "iter_id"),
            duration_us=_parse_int(fields[1], "duration_us"),
            output=json.loads(fields[2]),
        )

    def serialize(self: Self) -> str:
        """Serialize this result frame."""
        output = json.dumps(self.output, separators=(",", ":"))
        return f"{self.tag} {self.iter_id} {self.duration_us} {output}\n"


@dataclass(frozen=True, slots=True)
class DoneFrame(Frame):
    """Device-emitted terminal frame for a measurement run."""

    tag: ClassVar[str] = "DONE"

    total_iterations: int | None = None

    @classmethod
    def parse_payload(cls: type[DoneFrame], payload: str) -> DoneFrame:
        """Parse `DONE` or `DONE <total_iterations>`."""
        fields = payload.split()
        if len(fields) > 1:
            msg = "DONE frame accepts at most total_iterations"
            raise ValueError(msg)
        total = _parse_int(fields[0], "total_iterations") if fields else None
        return cls(total_iterations=total)

    def serialize(self: Self) -> str:
        """Serialize this terminal frame."""
        if self.total_iterations is None:
            return f"{self.tag}\n"
        return f"{self.tag} {self.total_iterations}\n"


@dataclass(frozen=True, slots=True)
class ErrFrame(Frame):
    """Device-emitted per-inference error frame."""

    tag: ClassVar[str] = "ERR"

    code: str
    message: str

    @classmethod
    def parse_payload(cls: type[ErrFrame], payload: str) -> ErrFrame:
        """Parse `ERR <code> <message>`."""
        fields = payload.split(maxsplit=1)
        if len(fields) != ERR_FIELD_COUNT:
            msg = "ERR frame requires code and message"
            raise ValueError(msg)
        return cls(code=fields[0], message=fields[1])

    def serialize(self: Self) -> str:
        """Serialize this error frame."""
        return f"{self.tag} {self.code} {self.message}\n"


@dataclass(frozen=True, slots=True)
class MetadataFrame(Frame):
    """Device-reported build and runtime state, queried before measurement."""

    tag: ClassVar[str] = "META"
    values: dict[str, Any]

    @classmethod
    def parse_payload(cls: type[MetadataFrame], payload: str) -> MetadataFrame:
        """Parse the JSON object carried by a firmware META response."""
        values = json.loads(payload)
        if not isinstance(values, dict):
            msg = "META payload must be a JSON object"
            raise TypeError(msg)
        return cls(values=values)

    def serialize(self: Self) -> str:
        """Serialize this metadata frame."""
        return f"{self.tag} {json.dumps(self.values, separators=(',', ':'))}\n"


class FrameParser:
    """Parse newline-delimited MCU protocol frames into dataclasses."""

    _frame_types: ClassVar[dict[str, type[Frame]]] = {
        RunFrame.tag: RunFrame,
        ResultFrame.tag: ResultFrame,
        DoneFrame.tag: DoneFrame,
        ErrFrame.tag: ErrFrame,
        MetadataFrame.tag: MetadataFrame,
    }

    def parse(self: Self, line: str) -> Frame:
        """Parse one ASCII frame line.

        Args:
        ----
            line: One newline-delimited protocol frame.

        Returns:
        -------
            A typed frame object corresponding to the first token.

        Raises:
        ------
            ValueError: The frame tag is unknown or fields are malformed.

        """
        stripped = line.strip()
        if not stripped:
            msg = "empty MCU frame"
            raise ValueError(msg)

        tag, _, payload = stripped.partition(" ")
        frame_type = self._frame_types.get(tag)
        if frame_type is None:
            msg = f"unknown MCU frame tag: {tag}"
            raise ValueError(msg)
        return frame_type.parse_payload(payload)


def _parse_int(raw: str, field_name: str) -> int:
    try:
        return int(raw)
    except ValueError as error:
        msg = f"{field_name} must be an integer"
        raise ValueError(msg) from error
