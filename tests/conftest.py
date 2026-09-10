# SPDX-License-Identifier: Apache-2.0
from collections.abc import Iterator
from sqlite3 import Connection

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from signal_bench.schema import Base
from tests.fixtures.mock_serial import MockSerialChannel

KNOWN_NON_TEST_FILES = {
    "experiments/README.md": "Experiment workspace documentation.",
    "experiments/__init__.py": "Package marker only.",
    "experiments/configs/llm-baseline-nemoclaw.yaml": "Experiment task fixture data.",
    "experiments/results/.gitkeep": "Empty directory marker.",
    "experiments/results/2026-05-03-llm-baseline-mac-modal.md": "Committed E01 findings artifact.",
    "src/signal_bench/__init__.py": "Version literal covered by CLI/version checks.",
    "src/signal_bench/adapters/__init__.py": (
        "Adapter contract re-export surface; compile-checked in T1.1."
    ),
    "src/signal_bench/adapters/base.py": (
        "Abstract adapter contract only; behavior tests land with T1.2/T1.5."
    ),
    "src/signal_bench/adapters/exceptions.py": (
        "Typed adapter exception hierarchy; compile-checked in T1.1."
    ),
    "src/signal_bench/adapters/mcu/__init__.py": "MCU adapter re-export surface.",
    "src/signal_bench/adapters/mcu/config.py": (
        "MCU adapter configuration contract; tests land with T1.5."
    ),
    "src/signal_bench/adapters/mcu/frames.py": (
        "MCU serial protocol frame contract; tests land with T1.5."
    ),
    "src/signal_bench/adapters/mcu/task.py": (
        "MCU task specification contract; tests land with T1.5."
    ),
    "src/signal_bench/firmware/__init__.py": "Firmware marker only; no Python behavior.",
    "src/signal_bench/firmware/esp32-s3-wake-word/.gitignore": "Firmware project metadata.",
    "src/signal_bench/firmware/esp32-s3-wake-word/README.md": "Firmware build documentation.",
    "src/signal_bench/firmware/esp32-s3-wake-word/main/CMakeLists.txt": "Firmware build metadata.",
    "src/signal_bench/firmware/esp32-s3-wake-word/main/idf_component.yml": (
        "Firmware build metadata."
    ),
    "src/signal_bench/firmware/esp32-s3-wake-word/main/main.c": (
        "ESP32-S3 firmware entry point; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/esp32-s3-wake-word/main/protocol.c": (
        "ESP32-S3 firmware protocol implementation; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/esp32-s3-wake-word/main/protocol.h": (
        "ESP32-S3 firmware protocol interface; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/esp32-s3-wake-word/main/task_stub.c": (
        "ESP32-S3 firmware canned task implementation; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/esp32-s3-wake-word/main/task_stub.h": (
        "ESP32-S3 firmware canned task interface; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/esp32-s3-wake-word/platformio.ini": "Firmware build metadata.",
    "src/signal_bench/firmware/esp32-s3-wake-word/sdkconfig.defaults": "Firmware build metadata.",
    "src/signal_bench/firmware/nano33-ble-sense-rev2/.gitignore": "Firmware project metadata.",
    "src/signal_bench/firmware/nano33-ble-sense-rev2/README.md": ("Firmware build documentation."),
    "src/signal_bench/firmware/nano33-ble-sense-rev2/platformio.ini": ("Firmware build metadata."),
    "src/signal_bench/firmware/nano33-ble-sense-rev2/src/main.cpp": (
        "Nano 33 firmware entry point; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/nano33-ble-sense-rev2/src/protocol.cpp": (
        "Nano 33 firmware protocol implementation; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/nano33-ble-sense-rev2/src/protocol.h": (
        "Nano 33 firmware protocol interface; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/nano33-ble-sense-rev2/src/task_stub.cpp": (
        "Nano 33 firmware canned task implementation; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/nano33-ble-sense-rev2/src/task_stub.h": (
        "Nano 33 firmware canned task interface; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/nucleo-f401re/.gitignore": "Firmware project metadata.",
    "src/signal_bench/firmware/nucleo-f401re/README.md": ("Firmware build documentation."),
    "src/signal_bench/firmware/nucleo-f401re/platformio.ini": ("Firmware build metadata."),
    "src/signal_bench/firmware/nucleo-f401re/src/main.cpp": (
        "NUCLEO-F401RE firmware entry point; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/nucleo-f401re/src/protocol.cpp": (
        "NUCLEO-F401RE firmware protocol implementation; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/nucleo-f401re/src/protocol.h": (
        "NUCLEO-F401RE firmware protocol interface; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/nucleo-f401re/src/task_stub.cpp": (
        "NUCLEO-F401RE firmware canned task implementation; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/nucleo-f401re/src/task_stub.h": (
        "NUCLEO-F401RE firmware canned task interface; compile-verified outside pytest."
    ),
    "src/signal_bench/migrations/env.py": "Alembic environment wiring covered by migration tests.",
    "src/signal_bench/migrations/script.py.mako": "Alembic template file.",
    "src/signal_bench/telemetry/__init__.py": "Public re-export package marker.",
    "src/signal_bench/telemetry/exceptions.py": (
        "Telemetry exception hierarchy; behavior tests land with T7.6."
    ),
    "src/signal_bench/telemetry/sources/__init__.py": (
        "Telemetry source implementation package marker."
    ),
    "src/signal_bench/tasks/__init__.py": "Task registry re-export package marker.",
    "src/signal_bench/tasks/README.md": "Task definition authoring documentation.",
    "src/signal_bench/synth/__init__.py": "Synthesis package re-export marker.",
    "src/signal_bench_cli/__init__.py": "Package marker only.",
    "src/signal_bench_cli/__main__.py": "CLI entry point covered by subprocess E2E tests.",
    "src/signal_bench_cli/commands/__init__.py": "Package marker only.",
    "tests/fixtures/__init__.py": "Fixture package marker only.",
    "tests/fixtures/mock_serial.py": "Shared mock serial test infrastructure.",
    "tests/fixtures/test_helpers.py": "Shared test helper classes and factories.",
    "tests/adapters/__init__.py": "Adapter test package marker only.",
    "tests/adapters/mcu/__init__.py": "MCU adapter test package marker only.",
    "tests/adapters/mcu/conftest.py": "Local fixture bridge for isolated MCU adapter test runs.",
    "tests/adapters/mcu/pytest.ini": (
        "Disables repo-wide coverage gate for isolated MCU adapter tests."
    ),
}

KNOWN_NON_TEST_PREFIXES = {
    "src/signal_bench/firmware/esp32-s3-telemetry-load/": (
        "ESP32-S3 deterministic load firmware; compile-verified outside pytest."
    ),
    "src/signal_bench/firmware/launch-tier/": (
        "Launch-tier board firmware and generated model/input blobs; "
        "compile-verified by PlatformIO, not pytest."
    ),
    "src/signal_bench/protocols/n3.yaml": (
        "Canonical protocol fixture consumed by MCU protocol tests and run scripts."
    ),
}


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """Let narrow verification runs skip the repo-wide coverage threshold."""
    narrow_synth_run = len(config.args) == 1 and (
        config.args[0].startswith("tests/unit/synth")
        or config.args[0].startswith("tests/integration/synth")
        or config.args[0] == "tests/integration/test_synth_report.py"
    )
    if config.option.markexpr == "smoke" or narrow_synth_run:
        config.option.cov_fail_under = 0
        cov_plugin = config.pluginmanager.getplugin("_cov")
        if cov_plugin is not None:
            cov_plugin.options.cov_fail_under = 0


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Connection, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    maker = sessionmaker(bind=engine)
    with maker() as session:
        yield session


@pytest.fixture
def mock_serial_channel(monkeypatch: pytest.MonkeyPatch) -> MockSerialChannel:
    """Patch pyserial-asyncio to use a programmable in-memory serial channel."""
    channel = MockSerialChannel()
    monkeypatch.setattr("serial_asyncio.open_serial_connection", channel.open)
    return channel
