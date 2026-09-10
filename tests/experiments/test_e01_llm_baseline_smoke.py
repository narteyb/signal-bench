# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for Experiment 01 with recorded Ollama HTTP fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import respx
from sqlalchemy import func, select

from experiments.e01_llm_baseline import run as e01_run
from experiments.lib.schema_writer import make_engine, session_factory_for
from signal_bench.schema import Result, Run, Target

FIXTURE_DIR = Path("tests/experiments/fixtures/e01")


@respx.mock
def test_e01_mac_short_smoke_with_recorded_ollama_fixture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Run E01's Mac path with recorded Ollama API fixtures and assert schema writes."""
    tags = json.loads((FIXTURE_DIR / "ollama_tags.json").read_text(encoding="utf-8"))
    chunks = json.loads((FIXTURE_DIR / "ollama_generate_short.json").read_text(encoding="utf-8"))
    stream_body = "\n".join(json.dumps(chunk) for chunk in chunks) + "\n"

    tags_route = respx.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json=tags),
    )
    generate_route = respx.post("http://localhost:11434/api/generate").mock(
        side_effect=lambda _request: httpx.Response(200, content=stream_body.encode()),
    )

    db_path = tmp_path / "e01-smoke.db"
    monkeypatch.setattr(e01_run, "ollama_version", lambda: "ollama version fixture")
    monkeypatch.setattr(e01_run, "render_outputs", lambda *_args: tmp_path / "summary.md")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "e01",
            "--db",
            str(db_path),
            "--targets",
            "mac",
            "--tiers",
            "short",
            "--skip-thermal",
        ],
    )

    e01_run.main()

    engine = make_engine(db_path)
    SessionLocal = session_factory_for(engine)
    try:
        with SessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(Target)) == 1
            run = session.scalar(select(Run))
            assert run is not None
            assert run.status == "completed"
            assert run.warmup_count == 5
            assert run.measurement_count == 20
            assert run.extra["prompt_tier"] == "short"
            assert session.scalar(select(func.count()).select_from(Result)) == 20
    finally:
        engine.dispose()

    assert tags_route.called
    assert generate_route.call_count == 25
