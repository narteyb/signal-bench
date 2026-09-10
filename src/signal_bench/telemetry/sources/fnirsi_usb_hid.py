# SPDX-License-Identifier: Apache-2.0
"""FNIRSI FNB58 USB-HID telemetry source."""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import logging as stdlib_logging
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self, cast

from signal_bench.telemetry.base import TelemetrySample, TelemetrySource
from signal_bench.telemetry.exceptions import SourceDataError, SourceStartError
from signal_bench.telemetry.logging import emit_event, get_logger
from signal_bench.telemetry.sources.fnirsi import (
    FNB58_MAX_PLAUSIBLE_CURRENT,
    FNB58_MAX_PLAUSIBLE_POWER,
    FNB58_MAX_PLAUSIBLE_VOLTAGE,
    FNB58_UNIT_HINTS,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable, Sequence

log = get_logger(__name__)

FNB58_HID_PACKET_SIZE = 64
FNB58_HID_REPORT_ID = 0
FNB58_HID_PACKET_HEADER = 0xAA
FNB58_HID_DATA_PACKET_TYPE = 0x04
FNB58_HID_SAMPLE_COUNT = 4
FNB58_HID_SAMPLE_SIZE = 15
FNB58_HID_PAYLOAD_OFFSET = 2
FNB58_HID_PACKET_INTERVAL_S = 0.04
FNB58_HID_SAMPLE_INTERVAL_S = 0.01
FNB58_HID_REFRESH_S = 1.0
FNB58_HID_READ_TIMEOUT_MS = 5_000
FNB58_HID_COMMANDS = (
    b"\xaa\x81" + (b"\x00" * 61) + b"\x8e",
    b"\xaa\x82" + (b"\x00" * 61) + b"\x96",
    b"\xaa\x82" + (b"\x00" * 61) + b"\x96",
)
FNB58_HID_KEEPALIVE = b"\xaa\x83" + (b"\x00" * 61) + b"\x9e"
FNB58_HID_DEVICE_IDS = (
    (0x2E3C, 0x5558),
    (0x0716, 0x5031),
    (0x0716, 0x5030),
)


@dataclass(frozen=True, slots=True)
class FnirsiHidDeviceId:
    """USB VID/PID pair for a compatible FNIRSI meter."""

    vendor_id: int
    product_id: int


@dataclass(frozen=True, slots=True)
class FnirsiHidSample:
    """One decoded FNB58 USB-HID sub-sample."""

    sample_index: int
    voltage: float
    current: float
    power: float
    dp_voltage: float
    dn_voltage: float
    temperature_c: float
    timestamp: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class FnirsiHidSourceConfig:
    """Configuration for an FNB58 USB-HID telemetry source."""

    name: str = "fnb58"
    device_ids: tuple[FnirsiHidDeviceId, ...] = tuple(
        FnirsiHidDeviceId(vendor_id, product_id) for vendor_id, product_id in FNB58_HID_DEVICE_IDS
    )
    read_timeout_ms: int = FNB58_HID_READ_TIMEOUT_MS
    internal_queue_maxsize: int = 2_048
    prepend_report_id: bool = True


class FnirsiHidSource(TelemetrySource):
    """Telemetry source for FNIRSI FNB58 over USB-HID."""

    source_name = "fnb58"
    sample_rate_hz = 100.0

    def __init__(
        self: Self,
        config: FnirsiHidSourceConfig | None = None,
        *,
        hid_module: object | None = None,
        device_factory: Callable[[], Any] | None = None,
    ) -> None:
        """Create a USB-HID source."""
        self._config = config or FnirsiHidSourceConfig()
        self.source_name = self._config.name
        self._hid_module = hid_module
        self._device_factory = device_factory
        self._device: Any | None = None
        self._queue: asyncio.Queue[TelemetrySample] = asyncio.Queue(
            maxsize=self._config.internal_queue_maxsize,
        )
        self._reader_task: asyncio.Task[None] | None = None
        self._stopping = True
        self._started = False
        self._data_error: SourceDataError | None = None

    @property
    def name(self: Self) -> str:
        """Return the stable telemetry source name."""
        return self._config.name

    def is_available(self: Self) -> bool:
        """Return whether hidapi imports and a compatible USB device enumerates."""
        try:
            hid_module = self._load_hid_module()
            return bool(find_fnb58_hid_device_info(hid_module, self._config.device_ids))
        except Exception:  # noqa: BLE001 - hidapi can raise backend-specific errors.
            return False

    async def start(self: Self) -> None:
        """Open the FNB58 HID interface and start streaming samples."""
        if self._started:
            return
        self._queue = asyncio.Queue(maxsize=self._config.internal_queue_maxsize)
        self._data_error = None
        self._stopping = False
        try:
            device = self._open_device()
            self._device = device
            for command in FNB58_HID_COMMANDS:
                await asyncio.to_thread(self._write_command, command)
        except Exception as exc:
            self._close_device()
            msg = "Failed to open FNB58 USB-HID interface"
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
        self._reader_task = asyncio.create_task(self._read_loop())
        emit_event(
            log,
            stdlib_logging.INFO,
            "source_started",
            source=self.name,
            run_id=None,
            context={"sample_rate_hz": self.sample_rate_hz, "transport": "usb_hid"},
        )

    async def stop(self: Self) -> None:
        """Stop reading and close the HID device."""
        self._stopping = True
        self._started = False
        task = self._reader_task
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            self._reader_task = None
        self._close_device()

    async def samples(self: Self) -> AsyncIterator[TelemetrySample]:
        """Yield decoded USB-HID samples until stopped."""
        if not self._started:
            msg = "FNB58 USB-HID source must be started before samples() is consumed"
            raise SourceStartError(msg)

        while not self._stopping:
            if self._data_error is not None:
                raise self._data_error
            try:
                sample = await asyncio.wait_for(self._queue.get(), timeout=5.0)
            except TimeoutError as exc:
                if self._data_error is not None:
                    raise self._data_error from exc
                continue
            yield sample

    async def _read_loop(self: Self) -> None:
        next_keepalive = asyncio.get_running_loop().time() + FNB58_HID_REFRESH_S
        while not self._stopping:
            try:
                packet = await asyncio.to_thread(self._read_packet)
                samples = parse_fnb58_hid_packet(packet, source_name=self.name)
                if samples:
                    for sample in samples:
                        self._enqueue_sample(sample)
                if asyncio.get_running_loop().time() >= next_keepalive:
                    next_keepalive = asyncio.get_running_loop().time() + FNB58_HID_REFRESH_S
                    await asyncio.to_thread(self._write_command, FNB58_HID_KEEPALIVE)
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError, SourceStartError, ValueError) as exc:
                self._data_error = SourceDataError("FNB58 USB-HID read failed")
                emit_event(
                    log,
                    stdlib_logging.ERROR,
                    "source_sample_malformed",
                    source=self.name,
                    run_id=None,
                    context={"error_class": type(exc).__name__, "message": str(exc)},
                    exc_info=exc,
                )
                return

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

    def _open_device(self: Self) -> object:
        hid_module = self._load_hid_module()
        device_info = find_fnb58_hid_device_info(hid_module, self._config.device_ids)
        if device_info is None:
            searched = ", ".join(
                f"0x{device.vendor_id:04x}:0x{device.product_id:04x}"
                for device in self._config.device_ids
            )
            msg = f"FNB58 USB-HID device not found; searched {searched}"
            raise SourceStartError(msg)

        hid = cast("Any", hid_module)
        device = self._device_factory() if self._device_factory is not None else hid.device()
        path = device_info.get("path")
        if path is not None:
            device.open_path(path)
        else:
            device.open(device_info["vendor_id"], device_info["product_id"])
        if hasattr(device, "set_nonblocking"):
            device.set_nonblocking(False)
        return device

    def _read_packet(self: Self) -> bytes:
        device = self._require_device()
        data = device.read(FNB58_HID_PACKET_SIZE, self._config.read_timeout_ms)
        return bytes(data)

    def _write_command(self: Self, command: bytes) -> None:
        device = self._require_device()
        payload = (
            bytes([FNB58_HID_REPORT_ID]) + command if self._config.prepend_report_id else command
        )
        written = device.write(payload)
        if written <= 0:
            msg = "FNB58 USB-HID command write returned no bytes"
            raise SourceStartError(msg)

    def _close_device(self: Self) -> None:
        device = self._device
        self._device = None
        if device is None:
            return
        close = getattr(device, "close", None)
        if close is not None:
            close()

    def _require_device(self: Self) -> Any:
        if self._device is None:
            msg = "FNB58 USB-HID device is not open"
            raise SourceStartError(msg)
        return self._device

    def _load_hid_module(self: Self) -> object:
        if self._hid_module is not None:
            return self._hid_module
        return importlib.import_module("hid")


def find_fnb58_hid_device_info(
    hid_module: object,
    device_ids: Iterable[FnirsiHidDeviceId] | None = None,
) -> dict[str, Any] | None:
    """Find a compatible FNB58 HID device returned by ``hid.enumerate()``."""
    candidates = tuple(device_ids or FnirsiHidSourceConfig().device_ids)
    enumerate_devices = cast("Any", hid_module).enumerate
    for device in enumerate_devices():
        vendor_id = int(device.get("vendor_id", -1))
        product_id = int(device.get("product_id", -1))
        if any(
            vendor_id == candidate.vendor_id and product_id == candidate.product_id
            for candidate in candidates
        ):
            return dict(device)
    return None


def parse_fnb58_hid_packet(
    data: bytes | Sequence[int],
    *,
    source_name: str = "fnb58",
    timestamp: dt.datetime | None = None,
) -> list[TelemetrySample]:
    """Decode one 64-byte FNB58 USB-HID packet into four grouped samples."""
    packet = bytes(data)
    if len(packet) != FNB58_HID_PACKET_SIZE:
        return []
    if packet[0] != FNB58_HID_PACKET_HEADER or packet[1] != FNB58_HID_DATA_PACKET_TYPE:
        return []

    base_timestamp = timestamp or dt.datetime.now(dt.UTC)
    decoded = []
    for sample in decode_fnb58_hid_samples(packet):
        offset_s = (sample.sample_index - (FNB58_HID_SAMPLE_COUNT - 1)) * (
            FNB58_HID_SAMPLE_INTERVAL_S
        )
        sample_timestamp = base_timestamp + dt.timedelta(
            seconds=offset_s,
        )
        decoded.append(
            TelemetrySample(
                timestamp=sample_timestamp,
                source_name=source_name,
                values={
                    "voltage": sample.voltage,
                    "current": sample.current,
                    "power": sample.power,
                },
                unit_hints=FNB58_UNIT_HINTS,
            ),
        )
    return decoded


def decode_fnb58_hid_samples(data: bytes | Sequence[int]) -> list[FnirsiHidSample]:
    """Decode raw FNB58 USB-HID measurement fields."""
    packet = bytes(data)
    if len(packet) != FNB58_HID_PACKET_SIZE:
        return []
    samples = []
    for sample_index in range(FNB58_HID_SAMPLE_COUNT):
        offset = FNB58_HID_PAYLOAD_OFFSET + (sample_index * FNB58_HID_SAMPLE_SIZE)
        voltage = int.from_bytes(packet[offset : offset + 4], "little", signed=False) / 100_000.0
        current = (
            int.from_bytes(packet[offset + 4 : offset + 8], "little", signed=False) / 100_000.0
        )
        dp_voltage = int.from_bytes(packet[offset + 8 : offset + 10], "little") / 1_000.0
        dn_voltage = int.from_bytes(packet[offset + 10 : offset + 12], "little") / 1_000.0
        temperature_c = int.from_bytes(packet[offset + 13 : offset + 15], "little") / 10.0
        power = voltage * current
        if not _values_are_plausible((voltage, current, power)):
            return []
        samples.append(
            FnirsiHidSample(
                sample_index=sample_index,
                voltage=voltage,
                current=current,
                power=power,
                dp_voltage=dp_voltage,
                dn_voltage=dn_voltage,
                temperature_c=temperature_c,
            ),
        )
    return samples


def _values_are_plausible(values: Sequence[float]) -> bool:
    voltage, current, power = values
    return (
        0.0 <= voltage <= FNB58_MAX_PLAUSIBLE_VOLTAGE
        and abs(current) <= FNB58_MAX_PLAUSIBLE_CURRENT
        and abs(power) <= FNB58_MAX_PLAUSIBLE_POWER
    )
