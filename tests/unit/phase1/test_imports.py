# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib


def test_phase1_and_rig_source_modules_import_cleanly() -> None:
    modules = (
        "signal_bench.phase1.accuracy",
        "signal_bench.phase1.adapters",
        "signal_bench.phase1.harness",
        "signal_bench.phase1.measurement",
        "signal_bench.telemetry.sources.bme280",
        "signal_bench.telemetry.sources.fnirsi",
        "signal_bench.telemetry.sources.ina219",
    )

    for module in modules:
        assert importlib.import_module(module).__name__ == module
