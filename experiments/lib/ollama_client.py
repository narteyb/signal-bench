# SPDX-License-Identifier: Apache-2.0
"""Thin Ollama HTTP client used by Experiment 01."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from experiments.lib.measurement import InferenceMeasurement


@dataclass(frozen=True, slots=True)
class OllamaModelInfo:
    """Resolved Ollama model metadata."""

    name: str
    digest: str
    size: int
    quantization: str | None
    parameter_size: str | None


class OllamaClient:
    """Small wrapper around the Ollama generate API."""

    def __init__(self, base_url: str = "http://localhost:11434", timeout_s: float = 900.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def require_model(self, model: str) -> OllamaModelInfo:
        """Return metadata for an installed model or raise with a clear message."""
        response = httpx.get(f"{self._base_url}/api/tags", timeout=10.0)
        response.raise_for_status()
        for item in response.json().get("models", []):
            if item.get("name") == model or item.get("model") == model:
                details = item.get("details") or {}
                return OllamaModelInfo(
                    name=str(item["name"]),
                    digest=str(item["digest"]),
                    size=int(item["size"]),
                    quantization=details.get("quantization_level"),
                    parameter_size=details.get("parameter_size"),
                )
        raise RuntimeError(f"Ollama model {model!r} is not installed. Run: ollama pull {model}")

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int,
        seed: int,
        temperature: float,
        top_p: float,
    ) -> InferenceMeasurement:
        """Generate one completion and measure wall time plus time to first token."""
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "num_predict": max_tokens,
                "num_ctx": 4096,
                "seed": seed,
                "temperature": temperature,
                "top_p": top_p,
            },
        }
        started_at = datetime.now(tz=UTC)
        start_s = time.perf_counter()
        first_token_ms: float | None = None
        chunks: list[str] = []
        final: dict[str, Any] = {}

        with httpx.stream(
            "POST",
            f"{self._base_url}/api/generate",
            json=payload,
            timeout=self._timeout_s,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                item = json.loads(line)
                token = str(item.get("response") or "")
                if token and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - start_s) * 1000.0
                chunks.append(token)
                if item.get("done"):
                    final = item

        duration_ms = (time.perf_counter() - start_s) * 1000.0
        tokens_out = int(final.get("eval_count") or max(1, len("".join(chunks).split())))
        tokens_in = int(final.get("prompt_eval_count") or max(1, len(prompt.split())))
        throughput = tokens_out / (duration_ms / 1000.0) if duration_ms > 0 else 0.0
        return InferenceMeasurement(
            started_at=started_at,
            duration_ms=duration_ms,
            first_token_ms=first_token_ms or duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            throughput_value=throughput,
            completion="".join(chunks),
            extra={
                "ollama_total_duration_ns": final.get("total_duration"),
                "ollama_load_duration_ns": final.get("load_duration"),
                "ollama_prompt_eval_count": final.get("prompt_eval_count"),
                "ollama_eval_count": final.get("eval_count"),
                "ollama_eval_duration_ns": final.get("eval_duration"),
            },
        )


def ollama_version() -> str:
    """Return the installed Ollama CLI version."""
    result = subprocess.run(
        ["ollama", "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    return (result.stdout or result.stderr).strip()
