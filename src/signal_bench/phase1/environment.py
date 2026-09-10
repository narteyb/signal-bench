# SPDX-License-Identifier: Apache-2.0
"""Environment manifest helpers for Phase 1 reports."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self


@dataclass(frozen=True, slots=True)
class EnvironmentManifest:
    """Host environment identity recorded with Phase 1 reports."""

    repo_root: Path
    git_sha: str
    git_dirty: bool
    platform: str
    python_version: str
    commands: dict[str, str]
    files: dict[str, str]

    def to_dict(self: Self) -> dict[str, Any]:
        """Return JSON-serializable manifest data."""
        return {
            "git_sha": self.git_sha,
            "git_dirty": self.git_dirty,
            "platform": self.platform,
            "python_version": self.python_version,
            "commands": self.commands,
            "files": self.files,
        }


def collect_environment(repo_root: Path) -> EnvironmentManifest:
    """Collect reproducibility pins without mutating the environment."""
    commands = {
        name: _command_version(command)
        for name, command in {
            "ollama": ["ollama", "--version"],
            "llama_cli": ["llama-cli", "--version"],
            "llama_cpp_brew": ["brew", "list", "--versions", "llama.cpp"],
            "ggml_brew": ["brew", "list", "--versions", "ggml"],
            "uv": ["uv", "--version"],
            "python": [sys.executable, "--version"],
            "xcode": ["xcodebuild", "-version"],
            "clang": ["clang", "--version"],
        }.items()
    }
    commands["python_executable"] = sys.executable
    files = {
        path: _sha256(repo_root / path)
        for path in ("pyproject.toml", "uv.lock")
        if (repo_root / path).exists()
    }
    return EnvironmentManifest(
        repo_root=repo_root,
        git_sha=_command_version(["git", "rev-parse", "HEAD"], cwd=repo_root),
        git_dirty=bool(_command_version(["git", "status", "--short"], cwd=repo_root).strip()),
        platform=platform.platform(),
        python_version=platform.python_version(),
        commands=commands,
        files=files,
    )


def write_environment_manifest(manifest: EnvironmentManifest, path: Path) -> None:
    """Write an environment manifest JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n")


def _command_version(command: list[str], *, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {exc}"
    return (completed.stdout or completed.stderr).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
