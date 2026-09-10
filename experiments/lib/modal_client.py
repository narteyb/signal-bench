# SPDX-License-Identifier: Apache-2.0
"""Modal A10G client for Experiment 01."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from experiments.lib.measurement import InferenceMeasurement

try:
    import modal
except ImportError:  # pragma: no cover - exercised only when experiment extra is absent.
    modal = None  # type: ignore[assignment]

APP_NAME = "signal-bench-e01-llm"

if modal is not None:
    image = (
        modal.Image.debian_slim(python_version="3.12")
        .apt_install("curl", "pciutils", "zstd")
        .pip_install("requests")
        .run_commands("curl -fsSL https://ollama.com/install.sh | sh")
    )
    app = modal.App(APP_NAME)

    @app.function(gpu="A10G", image=image, timeout=900, scaledown_window=60)
    def run_modal_protocol(  # type: ignore[misc]
        model: str,
        prompt: str,
        max_tokens: int,
        seed: int,
        temperature: float,
        top_p: float,
        warmup_count: int,
        measurement_count: int,
    ) -> dict[str, Any]:
        """Run one prompt tier on Modal and return measurement dicts."""
        import json
        import os
        import subprocess
        import time
        from datetime import UTC, datetime

        import requests

        def start_ollama() -> subprocess.Popen[str]:
            env = os.environ.copy()
            env["OLLAMA_HOST"] = "0.0.0.0:11434"
            proc = subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                env=env,
            )
            for _ in range(120):
                try:
                    requests.get("http://127.0.0.1:11434/api/tags", timeout=1.0).raise_for_status()
                    return proc
                except requests.RequestException:
                    time.sleep(0.5)
            proc.terminate()
            raise RuntimeError("Ollama server did not become ready inside Modal container")

        def shell_json(command: list[str]) -> dict[str, Any] | None:
            result = subprocess.run(
                command, check=False, capture_output=True, text=True, timeout=5.0
            )
            if result.returncode != 0:
                return None
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return None

        def gpu_snapshot() -> dict[str, Any]:
            data = shell_json(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                ],
            )
            if data is not None:
                return data
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            first = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
            parts = [part.strip() for part in first.split(",")]
            return {
                "gpu_util_pct": float(parts[0]) if len(parts) >= 1 and parts[0] else None,
                "gpu_mem_mb": int(parts[1]) if len(parts) >= 2 and parts[1] else None,
            }

        def model_info() -> dict[str, Any]:
            response = requests.get("http://127.0.0.1:11434/api/tags", timeout=10.0)
            response.raise_for_status()
            for item in response.json().get("models", []):
                if item.get("name") == model or item.get("model") == model:
                    return item
            raise RuntimeError(f"Modal Ollama model {model!r} not available after pull")

        def generate_one() -> dict[str, Any]:
            payload = {
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
            started_at = datetime.now(tz=UTC).isoformat()
            start_s = time.perf_counter()
            first_token_ms = None
            completion_parts: list[str] = []
            final: dict[str, Any] = {}
            with requests.post(
                "http://127.0.0.1:11434/api/generate",
                json=payload,
                stream=True,
                timeout=900.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    item = json.loads(line)
                    token = str(item.get("response") or "")
                    if token and first_token_ms is None:
                        first_token_ms = (time.perf_counter() - start_s) * 1000.0
                    completion_parts.append(token)
                    if item.get("done"):
                        final = item

            duration_ms = (time.perf_counter() - start_s) * 1000.0
            tokens_out = int(
                final.get("eval_count") or max(1, len("".join(completion_parts).split()))
            )
            tokens_in = int(final.get("prompt_eval_count") or max(1, len(prompt.split())))
            gpu = gpu_snapshot()
            return {
                "started_at": started_at,
                "duration_ms": duration_ms,
                "first_token_ms": first_token_ms or duration_ms,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "throughput_value": tokens_out / (duration_ms / 1000.0),
                "completion": "".join(completion_parts),
                "extra": {
                    "gpu_util_pct": gpu.get("gpu_util_pct"),
                    "gpu_mem_mb": gpu.get("gpu_mem_mb"),
                    "billing_seconds": duration_ms / 1000.0,
                    "ollama_total_duration_ns": final.get("total_duration"),
                    "ollama_load_duration_ns": final.get("load_duration"),
                    "ollama_prompt_eval_count": final.get("prompt_eval_count"),
                    "ollama_eval_count": final.get("eval_count"),
                    "ollama_eval_duration_ns": final.get("eval_duration"),
                },
            }

        proc = start_ollama()
        try:
            subprocess.run(["ollama", "pull", model], check=True, timeout=600.0)
            info = model_info()
            os_result = subprocess.run(["uname", "-a"], check=False, capture_output=True, text=True)
            for _ in range(warmup_count):
                generate_one()
            measurements = [generate_one() for _ in range(measurement_count)]
            return {
                "model_info": info,
                "os_version": os_result.stdout.strip(),
                "measurements": measurements,
            }
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                proc.kill()

else:
    app = None


class ModalClient:
    """Thin Modal SDK wrapper that keeps database writes on the local host."""

    def run_protocol(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int,
        seed: int,
        temperature: float,
        top_p: float,
        warmup_count: int,
        measurement_count: int,
    ) -> tuple[dict[str, Any], str, list[InferenceMeasurement]]:
        """Run one prompt tier on Modal A10G."""
        if modal is None or app is None:
            raise RuntimeError("Modal SDK is missing. Install with: uv sync --extra experiments")

        with modal.enable_output(), app.run():
            payload = run_modal_protocol.remote(
                model,
                prompt,
                max_tokens,
                seed,
                temperature,
                top_p,
                warmup_count,
                measurement_count,
            )

        measurements = [
            InferenceMeasurement(
                started_at=datetime_from_iso(item["started_at"]),
                duration_ms=float(item["duration_ms"]),
                first_token_ms=float(item["first_token_ms"]),
                tokens_in=int(item["tokens_in"]),
                tokens_out=int(item["tokens_out"]),
                throughput_value=float(item["throughput_value"]),
                completion=str(item["completion"]),
                extra=dict(item["extra"]),
            )
            for item in payload["measurements"]
        ]
        return dict(payload["model_info"]), str(payload["os_version"]), measurements


def datetime_from_iso(value: str) -> datetime:
    """Parse an ISO datetime produced by the Modal worker."""
    return datetime.fromisoformat(value)
