# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING, Any

import pytest

from signal_bench.telemetry.exceptions import SourceStartError
from signal_bench.telemetry.sources.fnirsi_usb_hid import (
    FNB58_HID_COMMANDS,
    FNB58_HID_DEVICE_IDS,
    FNB58_HID_KEEPALIVE,
    FNB58_HID_PACKET_SIZE,
    FNB58_HID_SAMPLE_COUNT,
    FNB58_HID_SAMPLE_SIZE,
    FnirsiHidDeviceId,
    FnirsiHidSource,
    FnirsiHidSourceConfig,
    decode_fnb58_hid_samples,
    find_fnb58_hid_device_info,
    parse_fnb58_hid_packet,
)

if TYPE_CHECKING:
    from signal_bench.telemetry.base import TelemetrySample


def _sample_values(sample: TelemetrySample) -> dict[str, float]:
    return object.__getattribute__(sample, "values")


def _sample_payload(
    *,
    voltage_raw: int,
    current_raw: int,
    dp_mv: int = 1_200,
    dn_mv: int = 1_100,
    temperature_decic: int = 384,
) -> bytes:
    return (
        voltage_raw.to_bytes(4, "little")
        + current_raw.to_bytes(4, "little")
        + dp_mv.to_bytes(2, "little")
        + dn_mv.to_bytes(2, "little")
        + b"\x01"
        + temperature_decic.to_bytes(2, "little")
    )


def _packet(samples: list[tuple[int, int]] | None = None) -> bytes:
    pairs = samples or [(500_000, 10_000), (501_000, 11_000), (502_000, 12_000), (503_000, 13_000)]
    payload = b"".join(
        _sample_payload(voltage_raw=voltage_raw, current_raw=current_raw)
        for voltage_raw, current_raw in pairs
    )
    assert len(payload) == FNB58_HID_SAMPLE_COUNT * FNB58_HID_SAMPLE_SIZE
    return b"\xaa\x04" + payload + b"\x00\x00"


class _FakeHidModule:
    def __init__(self, devices: list[dict[str, Any]]) -> None:
        self.devices = devices

    def enumerate(self) -> list[dict[str, Any]]:
        return self.devices


class _FakeHidDevice:
    def __init__(self, packets: list[bytes] | None = None) -> None:
        self.packets = packets or []
        self.opened_path: bytes | None = None
        self.writes: list[bytes] = []
        self.closed = False

    def open_path(self, path: bytes) -> None:
        self.opened_path = path

    def set_nonblocking(self, value: bool) -> None:  # noqa: FBT001 - mirrors hidapi.
        self.nonblocking = value

    def write(self, payload: bytes) -> int:
        self.writes.append(payload)
        return len(payload)

    def read(self, size: int, timeout_ms: int) -> list[int]:
        assert size == FNB58_HID_PACKET_SIZE
        assert timeout_ms == 5_000
        if not self.packets:
            return list(_packet())
        return list(self.packets.pop(0))

    def close(self) -> None:
        self.closed = True


def test_find_fnb58_hid_device_accepts_known_vid_pid() -> None:
    hid_module = _FakeHidModule(
        [
            {"vendor_id": 0x1234, "product_id": 0x5678, "path": b"wrong"},
            {
                "vendor_id": FNB58_HID_DEVICE_IDS[0][0],
                "product_id": FNB58_HID_DEVICE_IDS[0][1],
                "path": b"ok",
            },
        ],
    )

    device = find_fnb58_hid_device_info(hid_module)

    assert device is not None
    assert device["path"] == b"ok"


def test_find_fnb58_hid_device_accepts_configured_vid_pid() -> None:
    hid_module = _FakeHidModule([{"vendor_id": 0x0716, "product_id": 0x5031, "path": b"ok"}])

    device = find_fnb58_hid_device_info(
        hid_module,
        [FnirsiHidDeviceId(vendor_id=0x0716, product_id=0x5031)],
    )

    assert device is not None
    assert device["path"] == b"ok"


def test_decode_fnb58_hid_samples_decodes_all_four_subsamples() -> None:
    samples = decode_fnb58_hid_samples(_packet())

    assert len(samples) == 4
    assert samples[0].sample_index == 0
    assert samples[0].voltage == pytest.approx(5.0)
    assert samples[0].current == pytest.approx(0.1)
    assert samples[0].power == pytest.approx(0.5)
    assert samples[0].dp_voltage == pytest.approx(1.2)
    assert samples[0].dn_voltage == pytest.approx(1.1)
    assert samples[0].temperature_c == pytest.approx(38.4)
    assert samples[3].voltage == pytest.approx(5.03)
    assert samples[3].current == pytest.approx(0.13)


def test_parse_fnb58_hid_packet_returns_grouped_telemetry_samples() -> None:
    timestamp = dt.datetime(2026, 5, 23, 12, 0, tzinfo=dt.UTC)

    samples = parse_fnb58_hid_packet(_packet(), timestamp=timestamp)

    assert len(samples) == 4
    assert samples[0].source_name == "fnb58"
    assert _sample_values(samples[0]) == {
        "voltage": pytest.approx(5.0),
        "current": pytest.approx(0.1),
        "power": pytest.approx(0.5),
    }
    assert samples[0].timestamp == timestamp - dt.timedelta(seconds=0.03)
    assert samples[3].timestamp == timestamp
    assert samples[0].unit_hints == {"voltage": "V", "current": "A", "power": "W"}


def test_parse_fnb58_hid_packet_rejects_non_data_packet() -> None:
    assert parse_fnb58_hid_packet(bytes([0xAA, 0x03]) + (b"\x00" * 62)) == []


def test_parse_fnb58_hid_packet_rejects_implausible_sample() -> None:
    packet = _packet(
        [(20_000_000, 10_000), (501_000, 11_000), (502_000, 12_000), (503_000, 13_000)],
    )

    assert parse_fnb58_hid_packet(packet) == []


@pytest.mark.asyncio
async def test_fnirsi_hid_source_requires_start_before_samples() -> None:
    source = FnirsiHidSource()
    iterator = source.samples()

    with pytest.raises(SourceStartError):
        await anext(iterator)


@pytest.mark.asyncio
async def test_fnirsi_hid_source_opens_writes_and_yields_all_subsamples() -> None:
    hid_module = _FakeHidModule([{"vendor_id": 0x2E3C, "product_id": 0x5558, "path": b"hid-path"}])
    device = _FakeHidDevice([_packet(), _packet(), _packet()])
    source = FnirsiHidSource(
        FnirsiHidSourceConfig(internal_queue_maxsize=16),
        hid_module=hid_module,
        device_factory=lambda: device,
    )

    await source.start()
    try:
        collected = []
        async with asyncio.timeout(1.0):
            async for sample in source.samples():
                collected.append(sample)
                if len(collected) == 4:
                    break
    finally:
        await source.stop()

    assert len(collected) == 4
    assert device.opened_path == b"hid-path"
    assert device.writes[: len(FNB58_HID_COMMANDS)] == [
        b"\x00" + command for command in FNB58_HID_COMMANDS
    ]
    assert all(
        set(_sample_values(sample)) == {"voltage", "current", "power"} for sample in collected
    )
    assert device.closed is True


@pytest.mark.asyncio
async def test_fnirsi_hid_source_can_write_without_report_id_prefix() -> None:
    hid_module = _FakeHidModule([{"vendor_id": 0x2E3C, "product_id": 0x5558, "path": b"hid-path"}])
    device = _FakeHidDevice([_packet()])
    source = FnirsiHidSource(
        FnirsiHidSourceConfig(prepend_report_id=False),
        hid_module=hid_module,
        device_factory=lambda: device,
    )

    await source.start()
    await source.stop()

    assert device.writes[: len(FNB58_HID_COMMANDS)] == list(FNB58_HID_COMMANDS)
    assert FNB58_HID_KEEPALIVE not in device.writes
