# SPDX-License-Identifier: Apache-2.0
"""Phase 1 runtime adapters."""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import platform
import re
import resource
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

import requests

from signal_bench.phase1.runtime import (
    GenerationRequest,
    GenerationResult,
    HardwareRequired,
    RuntimeAdapter,
    RuntimeMetadata,
)

WARM_STEADY_STATE_PROTOCOL = (
    "warm_steady_state_v1: construct runtime adapter, load resident model, run one "
    "unmeasured warmup completion, then start telemetry and measure prompt generation. "
    "TTFT is measured from request dispatch to first generated token on the warm model; "
    "one-time model load and warmup are excluded."
)


@dataclass(frozen=True, slots=True)
class OllamaAdapterConfig:
    """Configuration for the host M1 Ollama runtime adapter."""

    model: str = "qwen2.5:7b"
    base_url: str = "http://localhost:11434"
    timeout_s: float = 900.0
    warmup_prompt: str = "Warmup. Answer with OK."
    warmup_tokens: int = 2
    warmup: bool = True


class OllamaRuntimeAdapter(RuntimeAdapter):
    """Real host SLM backend using Ollama's local streaming API."""

    def __init__(self: Self, config: OllamaAdapterConfig | None = None) -> None:
        self._config = config or OllamaAdapterConfig()
        self._model_info = self._require_model()
        if self._config.warmup:
            self._warmup()

    def metadata(self: Self) -> RuntimeMetadata:
        """Return resolved Ollama model/runtime metadata."""
        details = self._model_info.get("details") or {}
        return RuntimeMetadata(
            runtime_name="ollama",
            runtime_version=_command_text(["ollama", "--version"]),
            target_name="m1-max-64gb",
            backend="m1-metal",
            model_name=str(self._model_info.get("name") or self._config.model),
            model_revision=str(self._model_info.get("digest") or "unknown"),
            quantization=details.get("quantization_level"),
            model_bytes=int(self._model_info["size"]) if self._model_info.get("size") else None,
            extra={
                "parameter_size": details.get("parameter_size"),
                "family": details.get("family"),
                "host_platform": platform.platform(),
                "machine": platform.machine(),
                "measurement_protocol": WARM_STEADY_STATE_PROTOCOL,
                "warmup_excluded": True,
            },
        )

    def generate(self: Self, request: GenerationRequest) -> GenerationResult:
        """Generate one completion through Ollama."""
        payload: dict[str, Any] = {
            "model": self._config.model,
            "prompt": request.prompt,
            "stream": True,
            "options": {
                "num_predict": request.decode.max_tokens,
                "num_ctx": request.decode.num_ctx,
                "seed": request.decode.seed,
                "temperature": request.decode.temperature,
                "top_p": request.decode.top_p,
            },
        }
        started_at = dt.datetime.now(dt.UTC)
        start_s = time.perf_counter()
        first_token_ms: float | None = None
        chunks: list[str] = []
        final: dict[str, Any] = {}
        response = requests.post(
            f"{self._config.base_url}/api/generate",
            json=payload,
            stream=True,
            timeout=self._config.timeout_s,
        )
        response.raise_for_status()
        with response:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                item = json.loads(line)
                token = str(item.get("response") or "")
                if token and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - start_s) * 1000.0
                chunks.append(token)
                if item.get("done"):
                    final = item
        finished_at = dt.datetime.now(dt.UTC)
        duration_ms = (time.perf_counter() - start_s) * 1000.0
        text = "".join(chunks)
        tokens_out = int(final.get("eval_count") or max(1, len(text.split())))
        tokens_in = int(final.get("prompt_eval_count") or max(1, len(request.prompt.split())))
        return GenerationResult(
            prompt_id=request.prompt_id,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            first_token_ms=first_token_ms or duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            text=text,
            peak_memory_mb=_ollama_peak_rss_mb() or _peak_rss_mb(),
            extra={
                "ollama_total_duration_ns": final.get("total_duration"),
                "ollama_load_duration_ns": final.get("load_duration"),
                "ollama_prompt_eval_count": final.get("prompt_eval_count"),
                "ollama_eval_count": final.get("eval_count"),
                "ollama_eval_duration_ns": final.get("eval_duration"),
            },
        )

    def close(self: Self) -> None:
        """Ollama is a local service; no per-run resource is held."""

    def _warmup(self: Self) -> None:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "prompt": self._config.warmup_prompt,
            "stream": False,
            "options": {
                "num_predict": self._config.warmup_tokens,
                "temperature": 0.0,
                "top_p": 1.0,
                "seed": 42,
            },
        }
        response = requests.post(
            f"{self._config.base_url}/api/generate",
            json=payload,
            timeout=self._config.timeout_s,
        )
        response.raise_for_status()

    def _require_model(self: Self) -> dict[str, Any]:
        response = requests.get(f"{self._config.base_url}/api/tags", timeout=10.0)
        response.raise_for_status()
        for item in response.json().get("models", []):
            if item.get("name") == self._config.model or item.get("model") == self._config.model:
                return dict(item)
        msg = f"Ollama model {self._config.model!r} is not installed"
        raise RuntimeError(msg)


@dataclass(frozen=True, slots=True)
class LlamaCppAdapterConfig:
    """Configuration for the host M1 llama.cpp server adapter."""

    model: str = "qwen2.5:7b"
    model_path: Path | None = None
    server_command: str = "llama-server"
    tokenize_command: str = "llama-tokenize"
    timeout_s: float = 900.0
    host: str = "127.0.0.1"
    port: int | None = None
    ctx_size: int = 4096
    parallel: int = 1
    warmup_prompt: str = "Warmup. Answer with OK."
    warmup_tokens: int = 2
    warmup: bool = True


@dataclass(frozen=True, slots=True)
class OllamaBlobInfo:
    """Resolved local Ollama GGUF blob identity."""

    manifest_path: Path
    model_path: Path
    manifest_digest: str
    blob_digest: str
    size: int


class LlamaCppRuntimeAdapter(RuntimeAdapter):
    """Real host SLM backend using a resident llama.cpp server on the local GGUF blob."""

    def __init__(self: Self, config: LlamaCppAdapterConfig | None = None) -> None:
        self._config = config or LlamaCppAdapterConfig()
        self._blob = self._resolve_blob()
        self._version = _llama_cpp_version(self._config.server_command)
        self._port = self._config.port or _find_free_port(self._config.host)
        self._base_url = f"http://{self._config.host}:{self._port}"
        self._server: subprocess.Popen[bytes] | None = None
        if self._config.warmup:
            self._start_server()
            self._warmup()

    def metadata(self: Self) -> RuntimeMetadata:
        """Return resolved llama.cpp model/runtime metadata."""
        return RuntimeMetadata(
            runtime_name="llama.cpp",
            runtime_version=self._version,
            target_name="m1-max-64gb",
            backend="m1-metal-server",
            model_name=self._config.model,
            model_revision=self._blob.manifest_digest,
            quantization="Q4_K_M",
            model_bytes=self._blob.size,
            extra={
                "model_path": str(self._blob.model_path),
                "gguf_blob_digest": self._blob.blob_digest,
                "manifest_path": str(self._blob.manifest_path),
                "execution_note": (
                    "llama-server resident model; startup and warmup are excluded from measured "
                    "generation windows."
                ),
                "server_base_url": self._base_url,
                "measurement_protocol": WARM_STEADY_STATE_PROTOCOL,
                "warmup_excluded": True,
                "host_platform": platform.platform(),
                "machine": platform.machine(),
            },
        )

    def generate(self: Self, request: GenerationRequest) -> GenerationResult:
        """Generate one completion through resident llama.cpp server."""
        self._ensure_server()
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "n_predict": request.decode.max_tokens,
            "temperature": request.decode.temperature,
            "top_p": request.decode.top_p,
            "seed": request.decode.seed,
            "stream": True,
        }
        started_at = dt.datetime.now(dt.UTC)
        start_s = time.perf_counter()
        first_token_ms: float | None = None
        chunks: list[str] = []
        final: dict[str, Any] = {}
        response = requests.post(
            f"{self._base_url}/completion",
            json=payload,
            stream=True,
            timeout=self._config.timeout_s,
        )
        response.raise_for_status()
        with response:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                item = _parse_sse_json(line)
                if item is None:
                    continue
                token = str(item.get("content") or "")
                if token and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - start_s) * 1000.0
                chunks.append(token)
                final = item
                if item.get("stop"):
                    break
        finished_at = dt.datetime.now(dt.UTC)
        duration_ms = (time.perf_counter() - start_s) * 1000.0
        text = "".join(chunks)
        tokens_out = int(final.get("tokens_predicted") or self._count_tokens(text, add_bos=False))
        tokens_in = int(
            final.get("tokens_evaluated") or self._count_tokens(request.prompt, add_bos=False),
        )
        peak_memory_mb = _process_rss_mb(self._server.pid) if self._server is not None else None
        return GenerationResult(
            prompt_id=request.prompt_id,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            first_token_ms=first_token_ms or duration_ms,
            tokens_in=max(tokens_in, 1),
            tokens_out=max(tokens_out, 1),
            text=text,
            peak_memory_mb=peak_memory_mb or _peak_rss_mb(),
            extra={
                "llama_cpp_server_command": self._config.server_command,
                "llama_cpp_server_pid": self._server.pid if self._server is not None else None,
                "llama_cpp_tokens_predicted": final.get("tokens_predicted"),
                "llama_cpp_tokens_evaluated": final.get("tokens_evaluated"),
                "llama_cpp_timings": final.get("timings"),
            },
        )

    def close(self: Self) -> None:
        """Stop the resident llama.cpp server."""
        server = self._server
        if server is None:
            return
        server.terminate()
        try:
            server.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10.0)
        self._server = None

    def _resolve_blob(self: Self) -> OllamaBlobInfo:
        if self._config.model_path is not None:
            model_path = self._config.model_path.expanduser()
            return OllamaBlobInfo(
                manifest_path=model_path,
                model_path=model_path,
                manifest_digest=_sha256(model_path),
                blob_digest=_sha256(model_path),
                size=model_path.stat().st_size,
            )
        return resolve_ollama_model_blob(self._config.model)

    def _start_server(self: Self) -> None:
        if self._server is not None and self._server.poll() is None:
            return
        command = [
            self._config.server_command,
            "-m",
            str(self._blob.model_path),
            "--host",
            self._config.host,
            "--port",
            str(self._port),
            "--ctx-size",
            str(self._config.ctx_size),
            "--parallel",
            str(self._config.parallel),
            "--no-webui",
            "--log-disable",
        ]
        self._server = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._wait_until_healthy()

    def _ensure_server(self: Self) -> None:
        if self._server is None or self._server.poll() is not None:
            self._start_server()

    def _wait_until_healthy(self: Self) -> None:
        deadline = time.perf_counter() + self._config.timeout_s
        last_error: Exception | None = None
        while time.perf_counter() < deadline:
            if self._server is not None and self._server.poll() is not None:
                msg = f"llama-server exited early with code {self._server.returncode}"
                raise RuntimeError(msg)
            try:
                response = requests.get(f"{self._base_url}/health", timeout=1.0)
                if response.status_code == 200:
                    return
            except requests.RequestException as exc:
                last_error = exc
            time.sleep(0.25)
        msg = f"llama-server did not become healthy at {self._base_url}"
        raise RuntimeError(msg) from last_error

    def _warmup(self: Self) -> None:
        payload: dict[str, Any] = {
            "prompt": self._config.warmup_prompt,
            "n_predict": self._config.warmup_tokens,
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 42,
            "stream": False,
        }
        response = requests.post(
            f"{self._base_url}/completion",
            json=payload,
            timeout=self._config.timeout_s,
        )
        response.raise_for_status()

    def _count_tokens(self: Self, text: str, *, add_bos: bool) -> int:
        command = [
            self._config.tokenize_command,
            "-m",
            str(self._blob.model_path),
            "--prompt",
            text,
            "--ids",
            "--log-disable",
        ]
        if not add_bos:
            command.append("--no-bos")
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60.0,
        )
        if completed.returncode != 0:
            return len(text.split())
        try:
            ids = ast.literal_eval(completed.stdout.strip())
        except (SyntaxError, ValueError):
            return len(text.split())
        return len(ids) if isinstance(ids, list) else len(text.split())


@dataclass(frozen=True, slots=True)
class DeviceRuntimeConfig:
    """Configuration for a device-bound Phase 1 backend seam."""

    target_name: str
    backend: str
    model_name: str
    required_device: str
    required_runtime: str


class DeviceBoundRuntimeAdapter(RuntimeAdapter):
    """Adapter skeleton for backends that require hardware before execution."""

    def __init__(self: Self, config: DeviceRuntimeConfig) -> None:
        self._config = config

    def metadata(self: Self) -> RuntimeMetadata:
        """Return declared device-bound runtime metadata."""
        return RuntimeMetadata(
            runtime_name=self._config.required_runtime,
            runtime_version="hardware-required",
            target_name=self._config.target_name,
            backend=self._config.backend,
            model_name=self._config.model_name,
            model_revision="hardware-required",
            quantization=None,
            extra={
                "hardware_seam": self._config.required_device,
                "interlock_required": True,
            },
        )

    def generate(self: Self, request: GenerationRequest) -> GenerationResult:
        """Stop at the hardware seam."""
        _ = request
        msg = (
            f"{self._config.backend} execution requires interlock for "
            f"{self._config.required_device}"
        )
        raise HardwareRequired(msg)

    def close(self: Self) -> None:
        """No host-side resources are held."""


def pi_llama_cpp_adapter(model_name: str) -> DeviceBoundRuntimeAdapter:
    """Return the Raspberry Pi CPU runtime seam."""
    return DeviceBoundRuntimeAdapter(
        DeviceRuntimeConfig(
            target_name="pi5-8gb",
            backend="pi5-cpu-llama.cpp",
            model_name=model_name,
            required_device="Raspberry Pi 5 reachable over SSH with llama.cpp build",
            required_runtime="llama.cpp",
        ),
    )


def jetson_tensorrt_llm_adapter(model_name: str) -> DeviceBoundRuntimeAdapter:
    """Return the Jetson GPU runtime seam."""
    return DeviceBoundRuntimeAdapter(
        DeviceRuntimeConfig(
            target_name="jetson-orin-nano-super",
            backend="jetson-cuda-tensorrt-llm",
            model_name=model_name,
            required_device="Jetson Orin Nano Super reachable over SSH with JetPack/CUDA",
            required_runtime="TensorRT-LLM",
        ),
    )


def hailo_hef_adapter(model_name: str) -> DeviceBoundRuntimeAdapter:
    """Return the Hailo NPU runtime seam."""
    return DeviceBoundRuntimeAdapter(
        DeviceRuntimeConfig(
            target_name="pi5-hailo10h",
            backend="hailo10h-hef",
            model_name=model_name,
            required_device="Raspberry Pi 5 with Hailo-10H and a compiled HEF artifact",
            required_runtime="HailoRT",
        ),
    )


def host_runtime_adapter(runtime: str, model_name: str) -> RuntimeAdapter:
    """Build a host runtime adapter by public runtime name."""
    normalized = runtime.casefold()
    if normalized == "ollama":
        return OllamaRuntimeAdapter(OllamaAdapterConfig(model=model_name))
    if normalized in {"llama.cpp", "llama-cpp", "llamacpp"}:
        return LlamaCppRuntimeAdapter(LlamaCppAdapterConfig(model=model_name))
    msg = f"unsupported Phase 1 host runtime: {runtime}"
    raise ValueError(msg)


def resolve_ollama_model_blob(model_name: str) -> OllamaBlobInfo:
    """Resolve an Ollama model name to its local GGUF model blob."""
    if ":" in model_name:
        name, tag = model_name.split(":", 1)
    else:
        name, tag = model_name, "latest"
    namespace = "library"
    if "/" in name:
        namespace, name = name.split("/", 1)
    manifest_path = (
        Path.home()
        / ".ollama"
        / "models"
        / "manifests"
        / "registry.ollama.ai"
        / namespace
        / name
        / tag
    )
    if not manifest_path.exists():
        msg = f"Ollama model manifest not found for {model_name!r}: {manifest_path}"
        raise RuntimeError(msg)
    manifest = json.loads(manifest_path.read_text())
    model_layer = next(
        (
            layer
            for layer in manifest.get("layers", [])
            if layer.get("mediaType") == "application/vnd.ollama.image.model"
        ),
        None,
    )
    if model_layer is None:
        msg = f"Ollama model manifest has no model layer: {manifest_path}"
        raise RuntimeError(msg)
    blob_digest = str(model_layer["digest"]).replace("sha256:", "sha256-")
    model_path = Path.home() / ".ollama" / "models" / "blobs" / blob_digest
    if not model_path.exists():
        msg = f"Ollama model blob not found for {model_name!r}: {model_path}"
        raise RuntimeError(msg)
    return OllamaBlobInfo(
        manifest_path=manifest_path,
        model_path=model_path,
        manifest_digest=_sha256(manifest_path),
        blob_digest=str(model_layer["digest"]),
        size=int(model_layer.get("size") or model_path.stat().st_size),
    )


def _command_text(command: list[str], *, timeout_s: float = 10.0) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {exc}"
    return (completed.stdout or completed.stderr).strip() or "unknown"


def _llama_cpp_version(command: str) -> str:
    version = _command_text([command, "--version"], timeout_s=30.0)
    if not version.startswith("unavailable:"):
        return version
    brew_version = _command_text(["brew", "list", "--versions", "llama.cpp"], timeout_s=30.0)
    if brew_version.startswith("unavailable:"):
        return version
    return brew_version


def _peak_rss_mb() -> float:
    rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() == "Darwin":
        return rss / (1024.0 * 1024.0)
    return rss / 1024.0


def _children_peak_rss_mb() -> float:
    rss = float(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    if platform.system() == "Darwin":
        return rss / (1024.0 * 1024.0)
    return rss / 1024.0


def _ollama_peak_rss_mb() -> float | None:
    try:
        completed = subprocess.run(
            ["/bin/ps", "-axo", "rss=,command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    rss_values: list[float] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(maxsplit=1)
        if len(parts) != 2:
            continue
        rss_kib, command = parts
        if "Ollama.app" not in command and "ollama serve" not in command:
            continue
        try:
            rss_values.append(float(rss_kib) / 1024.0)
        except ValueError:
            continue
    return max(rss_values) if rss_values else None


def _process_rss_mb(pid: int) -> float | None:
    try:
        completed = subprocess.run(
            ["/bin/ps", "-o", "rss=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        return float(completed.stdout.strip()) / 1024.0
    except ValueError:
        return None


def _find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _parse_sse_json(line: str) -> dict[str, Any] | None:
    if line.startswith("data: "):
        line = line.removeprefix("data: ").strip()
    if not line or line == "[DONE]":
        return None
    decoded = json.loads(line)
    return decoded if isinstance(decoded, dict) else None


def _extract_llama_cli_answer(raw_output: str, prompt: str) -> str:
    clean = _clean_llama_output(raw_output)
    marker = f"> {prompt}"
    tail = clean.rsplit(marker, 1)[1] if marker in clean else clean
    lines: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        if stripped.startswith("[ Prompt:") or stripped == "Exiting...":
            break
        if stripped.startswith(">"):
            if lines:
                break
            continue
        if _is_llama_banner_line(stripped):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _clean_llama_output(raw_output: str) -> str:
    without_backspaces = re.sub(r".\x08", "", raw_output)
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", without_backspaces)


def _is_llama_banner_line(line: str) -> bool:
    prefixes = (
        "Loading model",
        "build",
        "model",
        "modalities",
        "available commands",
        "/exit",
        "/regen",
        "/clear",
        "/read",
        "/glob",
    )
    return line.startswith(prefixes) or set(line) <= {"▄", "█", "▀", " "}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
