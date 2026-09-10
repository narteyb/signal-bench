# SPDX-License-Identifier: Apache-2.0
"""Fetch pinned support artifacts that are stored outside the Git repository."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import hf_hub_download

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPPORT_ARTIFACT_REPO_ID = "narteybrown/signal-bench-support-artifacts-v1"
SUPPORT_ARTIFACT_REVISION = "b864b5b17e599f9b6582a4e677bbd19b38535c0b"


class ArtifactError(RuntimeError):
    """Base class for support artifact retrieval failures."""


class ArtifactUnavailableError(ArtifactError):
    """Raised when a requested path is not in the support artifact manifest."""


class ArtifactHashError(ArtifactError):
    """Raised when a local or downloaded artifact does not match its hash."""


@dataclass(frozen=True, slots=True)
class SupportArtifact:
    """A file stored in the pinned Hugging Face support artifact dataset."""

    path: str
    sha256: str
    size: int
    description: str
    remote_path: str | None = None

    @property
    def local_path(self) -> Path:
        """Return the checkout-relative local destination path."""
        return REPO_ROOT / self.path

    @property
    def hub_path(self) -> str:
        """Return the path stored in the Hugging Face dataset."""
        return self.remote_path or self.path


SUPPORT_ARTIFACTS: dict[str, SupportArtifact] = {
    item.path: item
    for item in (
        SupportArtifact(
            path="data/eval/kws/mlperftiny-kws-test.npz",
            sha256="549424c4cd238eda1b5761cb4ff653e618ddfd70cf3d479303a8d8bfa03ee2c6",
            size=1_357_098,
            description="KWS full-eval preprocessed archive",
        ),
        SupportArtifact(
            path="data/eval/kws/mlperftiny-kws-test.metadata.json",
            sha256="e7704952d25abb2ed9904904f04789ecbbe3fae4bfcd92d0f4bb8228b27def01",
            size=730,
            description="KWS full-eval metadata",
        ),
        SupportArtifact(
            path="data/eval/ad/mlperftiny-ad-test.npz",
            sha256="9a00b2ffc119f5f3c645307568eadc36d7804fd56d7e05229ad7bf33c25eda61",
            size=3_683_219,
            description="AD full-eval preprocessed archive",
        ),
        SupportArtifact(
            path="data/eval/ad/mlperftiny-ad-test.metadata.json",
            sha256="c2fbd9dd01d202b54cd3e9569b49d5d23f5c8052dcbcbd0cff45b11eb7173091",
            size=564,
            description="AD full-eval metadata",
        ),
        SupportArtifact(
            path="data/mcu_subsets/kws/subset_v1.npz",
            sha256="056a81e6c6675a42f57d85f71aa2e929364b027a37f4df0b2d5fd620c4931114",
            size=183_229,
            description="KWS deterministic MCU subset",
        ),
    )
}


def known_artifacts() -> tuple[SupportArtifact, ...]:
    """Return all support artifacts known to this checkout."""
    return tuple(SUPPORT_ARTIFACTS.values())


def ensure_artifact(path: str | Path) -> Path:
    """Return a local artifact path, downloading and verifying it if missing."""
    artifact = _artifact_for_path(path)
    destination = artifact.local_path
    if destination.exists():
        _verify_hash(destination, artifact)
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    downloaded = _download_from_hub(artifact)
    _verify_hash(downloaded, artifact)
    shutil.copy2(downloaded, destination)
    _verify_hash(destination, artifact)
    return destination


def ensure_all_artifacts() -> list[Path]:
    """Download every known support artifact and return their local paths."""
    return [ensure_artifact(artifact.path) for artifact in known_artifacts()]


def _artifact_for_path(path: str | Path) -> SupportArtifact:
    given = Path(path)
    try:
        relative = given.resolve().relative_to(REPO_ROOT)
    except ValueError:
        relative = given
    key = relative.as_posix()
    try:
        return SUPPORT_ARTIFACTS[key]
    except KeyError as exc:
        message = f"no support artifact is registered for {key}"
        raise ArtifactUnavailableError(message) from exc


def _download_from_hub(artifact: SupportArtifact) -> Path:
    return Path(
        hf_hub_download(
            repo_id=SUPPORT_ARTIFACT_REPO_ID,
            filename=artifact.hub_path,
            revision=SUPPORT_ARTIFACT_REVISION,
            repo_type="dataset",
        )
    )


def _verify_hash(path: Path, artifact: SupportArtifact) -> None:
    actual = _sha256(path)
    if actual != artifact.sha256:
        message = f"{path} SHA-256 mismatch: expected {artifact.sha256}, got {actual}"
        raise ArtifactHashError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
