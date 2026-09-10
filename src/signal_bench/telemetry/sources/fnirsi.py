# SPDX-License-Identifier: Apache-2.0
"""FNIRSI FNB58 BLE telemetry source.

Protocol notes:
    FNIRSI does not publish an FNB58 BLE protocol. This implementation uses
    community-reported BLE facts from Parker Reed's ``fnirsi-fnb58.py`` gist:
    https://gist.github.com/parkerlreed/0ce45e907ce536a0541afb90b5b49350

    The reference uses ``bleak``, writes ``aa8100f4`` and ``aa8200a7`` to
    characteristic ``0000ffe9-0000-1000-8000-00805f9b34fb``, subscribes to
    notifications from ``0000ffe4-0000-1000-8000-00805f9b34fb``, and decodes
    voltage/current as little-endian signed 32-bit integers at byte offset 21
    scaled by 10000. Live captures from a discovered FNB58 showed notifications are
    concatenated ``aa type len payload checksum`` frames; voltage/current/power
    live in the ``0x04`` frame with a 12-byte payload.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging as stdlib_logging
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from bleak import BleakClient
from bleak.exc import BleakError

from signal_bench.telemetry.base import TelemetrySample, TelemetrySource
from signal_bench.telemetry.exceptions import (
    SourceDataError,
    SourceDisconnectError,
    SourceStartError,
)
from signal_bench.telemetry.logging import emit_event, get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

log = get_logger(__name__)

FNB58_WRITE_CHARACTERISTIC = "0000ffe9-0000-1000-8000-00805f9b34fb"
FNB58_NOTIFY_CHARACTERISTIC = "0000ffe4-0000-1000-8000-00805f9b34fb"
FNB58_ENABLE_STREAMING_WRITES = (bytes.fromhex("aa8100f4"), bytes.fromhex("aa8200a7"))
FNB58_PACKET_VALUE_OFFSET = 21
FNB58_FRAME_HEADER = 0xAA
FNB58_MEASUREMENT_FRAME_TYPE = 0x04
FNB58_MEASUREMENT_FRAME_LENGTH = 12
FNB58_PACKET_SCALE = 10_000.0
FNB58_MALFORMED_LIMIT = 3
FNB58_UNIT_HINTS = {"voltage": "V", "current": "A", "power": "W"}
FNB58_MAX_PLAUSIBLE_VOLTAGE = 150.0
FNB58_MAX_PLAUSIBLE_CURRENT = 100.0
FNB58_MAX_PLAUSIBLE_POWER = 10_000.0


@dataclass(frozen=True, slots=True)
class FnirsiSourceConfig:
    """Configuration for an FNB58 BLE telemetry source.

    Discover the address with ``BleakScanner.discover()`` in a local script.
    """

    address: str
    name: str = "fnb58"
    sample_timeout_seconds: float = 5.0
    reconnect_attempts: int = 0
    write_characteristic: str = FNB58_WRITE_CHARACTERISTIC
    notify_characteristic: str = FNB58_NOTIFY_CHARACTERISTIC
    enable_streaming_writes: tuple[bytes, ...] = FNB58_ENABLE_STREAMING_WRITES
    internal_queue_maxsize: int = 256
    malformed_limit: int = FNB58_MALFORMED_LIMIT


class FnirsiSource(TelemetrySource):
    """Telemetry source for FNIRSI FNB58 over BLE notifications."""

    source_name = "fnb58"
    sample_rate_hz = 4.0
    partial_coverage_threshold = 0.75

    def __init__(self: Self, config: FnirsiSourceConfig) -> None:
        """Create an FNB58 source."""
        self._config = config
        self.source_name = config.name
        self._queue: asyncio.Queue[TelemetrySample] = asyncio.Queue(
            maxsize=config.internal_queue_maxsize,
        )
        self._client: BleakClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False
        self._started = False
        self._disconnected = False
        self._data_error: SourceDataError | None = None
        self._malformed_count = 0

    @property
    def name(self: Self) -> str:
        """Return the stable telemetry source name."""
        return self._config.name

    async def start(self: Self) -> None:
        """Connect to the FNB58 and subscribe to telemetry notifications."""
        if self._started:
            return
        if self._config.reconnect_attempts != 0:
            emit_event(
                log,
                stdlib_logging.WARNING,
                "source_reconnect_not_implemented",
                source=self.name,
                run_id=None,
                context={"configured_attempts": self._config.reconnect_attempts},
            )

        self._loop = asyncio.get_running_loop()
        self._stopping = False
        self._disconnected = False
        self._data_error = None
        self._malformed_count = 0
        self._queue = asyncio.Queue(maxsize=self._config.internal_queue_maxsize)
        self._client = BleakClient(
            self._config.address,
            disconnected_callback=self._handle_disconnect,
        )

        try:
            await self._client.connect()
            for payload in self._config.enable_streaming_writes:
                await self._client.write_gatt_char(self._config.write_characteristic, payload)
            await self._client.start_notify(
                self._config.notify_characteristic,
                self._handle_notification,
            )
        except BleakError as exc:
            await self._disconnect_quietly()
            msg = f"Failed to connect or subscribe to FNB58 at {self._config.address}"
            emit_event(
                log,
                stdlib_logging.ERROR,
                "source_start_failed",
                source=self.name,
                run_id=None,
                context={"error_class": type(exc).__name__, "message": str(exc)},
                exc_info=exc,
            )
            raise SourceStartError(msg) from exc
        except Exception as exc:
            await self._disconnect_quietly()
            msg = f"Unexpected FNB58 startup failure at {self._config.address}"
            emit_event(
                log,
                stdlib_logging.ERROR,
                "source_start_failed",
                source=self.name,
                run_id=None,
                context={"error_class": type(exc).__name__, "message": str(exc)},
                exc_info=exc,
            )
            raise SourceStartError(msg) from exc

        self._started = True
        emit_event(
            log,
            stdlib_logging.INFO,
            "source_started",
            source=self.name,
            run_id=None,
            context={"sample_rate_hz": self.sample_rate_hz},
        )

    async def stop(self: Self) -> None:
        """Stop notifications and disconnect from the FNB58."""
        self._stopping = True
        client = self._client
        self._started = False
        if client is None:
            return

        try:
            if client.is_connected:
                await client.stop_notify(self._config.notify_characteristic)
        except BleakError:
            emit_event(
                log,
                stdlib_logging.ERROR,
                "orchestrator_teardown_failed",
                source=self.name,
                run_id=None,
                context={"reason": "stop_notify_failed"},
                exc_info=True,
            )
        finally:
            await self._disconnect_quietly()
            self._client = None

    async def samples(self: Self) -> AsyncIterator[TelemetrySample]:
        """Yield FNB58 samples until stopped or disconnected."""
        if not self._started:
            msg = "FNB58 source must be started before samples() is consumed"
            raise SourceStartError(msg)

        while not self._stopping:
            if self._data_error is not None:
                raise self._data_error
            try:
                sample = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self._config.sample_timeout_seconds,
                )
            except TimeoutError as exc:
                if self._data_error is not None:
                    raise self._data_error from exc
                if self._disconnected or not self._is_connected:
                    msg = "FNB58 connection lost (timeout and disconnect detected)"
                    raise SourceDisconnectError(msg) from exc
                continue

            yield sample

        return

    def _handle_notification(self: Self, _sender: object, data: bytearray) -> None:
        sample = parse_fnb58_notification(
            bytes(data),
            source_name=self._config.name,
            timestamp=dt.datetime.now(dt.UTC),
        )
        if sample is None:
            if _is_well_formed_fnb58_notification(bytes(data)):
                self._malformed_count = 0
                return
            self._malformed_count += 1
            level = (
                stdlib_logging.WARNING
                if self._malformed_count >= FNB58_MALFORMED_LIMIT
                else stdlib_logging.DEBUG
            )
            emit_event(
                log,
                level,
                "source_sample_malformed",
                source=self.name,
                run_id=None,
                context={"consecutive_malformed": self._malformed_count},
            )
            if self._malformed_count >= self._config.malformed_limit:
                self._data_error = SourceDataError("FNB58 emitting malformed data")
            return

        self._malformed_count = 0
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._enqueue_sample, sample)

    def _enqueue_sample(self: Self, sample: TelemetrySample) -> None:
        try:
            self._queue.put_nowait(sample)
        except asyncio.QueueFull:
            emit_event(
                log,
                stdlib_logging.ERROR,
                "queue_overflow_dropping_sample",
                source=self.name,
                run_id=None,
                context={"queue_maxsize": self._config.internal_queue_maxsize},
            )

    def _handle_disconnect(self: Self, _client: BleakClient) -> None:
        self._disconnected = True
        if not self._stopping:
            emit_event(
                log,
                stdlib_logging.ERROR,
                "source_disconnected",
                source=self.name,
                run_id=None,
                context={"reason": "ble_disconnect_callback"},
            )

    @property
    def _is_connected(self: Self) -> bool:
        return self._client is not None and self._client.is_connected

    async def _disconnect_quietly(self: Self) -> None:
        client = self._client
        if client is None:
            return
        try:
            if client.is_connected:
                await client.disconnect()
        except BleakError:
            emit_event(
                log,
                stdlib_logging.DEBUG,
                "source_disconnect_cleanup_failed",
                source=self.name,
                run_id=None,
                context={"error_class": "BleakError"},
                exc_info=True,
            )


def parse_fnb58_notification(
    data: bytes,
    *,
    source_name: str = "fnb58",
    timestamp: dt.datetime | None = None,
) -> TelemetrySample | None:
    """Parse one FNB58 BLE notification into a grouped telemetry sample."""
    payload = _find_measurement_payload(data)
    if payload is None:
        return None

    voltage_raw, current_raw, _power_raw = struct.unpack("<iii", payload)
    voltage = voltage_raw / FNB58_PACKET_SCALE
    current = current_raw / FNB58_PACKET_SCALE
    power = voltage * current
    if not _values_are_plausible((voltage, current, power)):
        return None

    return TelemetrySample(
        timestamp=timestamp or dt.datetime.now(dt.UTC),
        source_name=source_name,
        values={"voltage": voltage, "current": current, "power": power},
        unit_hints=FNB58_UNIT_HINTS,
    )


def _find_measurement_payload(data: bytes) -> bytes | None:
    offset = 0
    while offset + 4 <= len(data):
        if data[offset] != FNB58_FRAME_HEADER:
            offset += 1
            continue

        frame_type = data[offset + 1]
        payload_len = data[offset + 2]
        payload_start = offset + 3
        payload_end = payload_start + payload_len
        checksum_end = payload_end + 1
        if checksum_end > len(data):
            return None

        payload = data[payload_start:payload_end]
        if (
            frame_type == FNB58_MEASUREMENT_FRAME_TYPE
            and payload_len == FNB58_MEASUREMENT_FRAME_LENGTH
        ):
            return payload

        offset = checksum_end

    return None


def _is_well_formed_fnb58_notification(data: bytes) -> bool:
    offset = 0
    saw_frame = False
    while offset < len(data):
        if offset + 4 > len(data) or data[offset] != FNB58_FRAME_HEADER:
            return False

        payload_len = data[offset + 2]
        checksum_end = offset + 3 + payload_len + 1
        if checksum_end > len(data):
            return False

        saw_frame = True
        offset = checksum_end

    return saw_frame


def _values_are_plausible(values: Sequence[float]) -> bool:
    voltage, current, power = values
    return (
        0.0 <= voltage <= FNB58_MAX_PLAUSIBLE_VOLTAGE
        and abs(current) <= FNB58_MAX_PLAUSIBLE_CURRENT
        and abs(power) <= FNB58_MAX_PLAUSIBLE_POWER
    )
