# SPDX-License-Identifier: Apache-2.0
import asyncio
import datetime as dt
import struct
from typing import ClassVar

import pytest
from bleak.exc import BleakError

import signal_bench.telemetry.sources.fnirsi as fnirsi_module
from signal_bench.telemetry.base import TelemetrySample
from signal_bench.telemetry.exceptions import (
    SourceDataError,
    SourceDisconnectError,
    SourceStartError,
)
from signal_bench.telemetry.sources.fnirsi import (
    FNB58_PACKET_VALUE_OFFSET,
    FnirsiSource,
    FnirsiSourceConfig,
    parse_fnb58_notification,
)


def _sample_values(sample: TelemetrySample) -> dict[str, float]:
    return object.__getattribute__(sample, "values")


class _FakeBleakClient:
    """Small fake of the BleakClient methods used by FnirsiSource."""

    instances: ClassVar[list["_FakeBleakClient"]] = []
    connect_error: ClassVar[Exception | None] = None
    start_notify_error: ClassVar[Exception | None] = None
    stop_notify_error: ClassVar[Exception | None] = None
    disconnect_error: ClassVar[Exception | None] = None

    def __init__(self, address: str, disconnected_callback) -> None:
        self.address = address
        self.disconnected_callback = disconnected_callback
        self.is_connected = False
        self.writes: list[tuple[str, bytes]] = []
        self.notify_characteristic: str | None = None
        self.notification_callback = None
        self.stop_notify_calls = 0
        self.disconnect_calls = 0
        type(self).instances.append(self)

    async def connect(self) -> None:
        if type(self).connect_error is not None:
            raise type(self).connect_error
        self.is_connected = True

    async def write_gatt_char(self, characteristic: str, payload: bytes) -> None:
        self.writes.append((characteristic, payload))

    async def start_notify(self, characteristic: str, callback) -> None:
        if type(self).start_notify_error is not None:
            raise type(self).start_notify_error
        self.notify_characteristic = characteristic
        self.notification_callback = callback

    async def stop_notify(self, _characteristic: str) -> None:
        self.stop_notify_calls += 1
        if type(self).stop_notify_error is not None:
            raise type(self).stop_notify_error

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        if type(self).disconnect_error is not None:
            raise type(self).disconnect_error
        self.is_connected = False


@pytest.fixture
def fake_bleak(monkeypatch: pytest.MonkeyPatch) -> type[_FakeBleakClient]:
    _FakeBleakClient.instances = []
    _FakeBleakClient.connect_error = None
    _FakeBleakClient.start_notify_error = None
    _FakeBleakClient.stop_notify_error = None
    _FakeBleakClient.disconnect_error = None
    monkeypatch.setattr(fnirsi_module, "BleakClient", _FakeBleakClient)
    return _FakeBleakClient


def _packet(
    *,
    voltage_raw: int = 50_200,
    current_raw: int = 1_230,
    power_raw: int = 6_174,
) -> bytearray:
    payload = struct.pack("<iii", voltage_raw, current_raw, power_raw)
    return bytearray(b"\xaa\x04\x0c" + payload + b"\x00")


def test_fnirsi_config_defaults() -> None:
    config = FnirsiSourceConfig(address="<mac-address>")

    assert config.name == "fnb58"
    assert config.sample_timeout_seconds == 5.0
    assert config.reconnect_attempts == 0


def test_parse_fnb58_notification_decodes_grouped_values() -> None:
    timestamp = dt.datetime(2026, 5, 9, tzinfo=dt.UTC)

    sample = parse_fnb58_notification(bytes(_packet()), timestamp=timestamp)

    assert sample is not None
    assert sample.timestamp == timestamp
    assert sample.source_name == "fnb58"
    values = _sample_values(sample)
    assert values == {
        "voltage": pytest.approx(5.02),
        "current": pytest.approx(0.123),
        "power": pytest.approx(5.02 * 0.123),
    }
    assert sample.unit_hints == {"voltage": "V", "current": "A", "power": "W"}


def test_parse_fnb58_notification_rejects_short_packet() -> None:
    assert parse_fnb58_notification(b"\x00" * FNB58_PACKET_VALUE_OFFSET) is None


def test_parse_fnb58_notification_rejects_status_frame_without_measurement() -> None:
    packet = bytes.fromhex(
        "aa0606ad0531050000a9" "aa0704440000006b" "aa081101931100004102000065000000f701000000",
    )

    assert parse_fnb58_notification(packet) is None


def test_parse_fnb58_notification_rejects_implausible_values() -> None:
    assert parse_fnb58_notification(bytes(_packet(voltage_raw=2_000_000))) is None


def test_parse_fnb58_notification_derives_power_from_voltage_current() -> None:
    sample = parse_fnb58_notification(
        bytes(_packet(voltage_raw=50_000, current_raw=2_000, power_raw=1)),
    )

    assert sample is not None
    assert _sample_values(sample)["power"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_fnirsi_source_requires_start_before_samples() -> None:
    source = FnirsiSource(FnirsiSourceConfig(address="<mac-address>"))
    iterator = source.samples()

    assert source.name == "fnb58"
    with pytest.raises(SourceStartError):
        await anext(iterator)


@pytest.mark.asyncio
async def test_fnirsi_stop_is_idempotent_before_start() -> None:
    source = FnirsiSource(FnirsiSourceConfig(address="<mac-address>"))

    await source.stop()
    await source.stop()


def test_fnirsi_repeated_malformed_notifications_set_data_error() -> None:
    source = FnirsiSource(FnirsiSourceConfig(address="<mac-address>"))

    source._handle_notification(object(), bytearray(b"\x00"))
    source._handle_notification(object(), bytearray(b"\x00"))
    source._handle_notification(object(), bytearray(b"\x00"))

    assert isinstance(source._data_error, SourceDataError)


def test_fnirsi_ignores_well_formed_status_frames() -> None:
    source = FnirsiSource(FnirsiSourceConfig(address="<mac-address>"))
    packet = bytearray.fromhex(
        "aa0606ad0531050000a9" "aa0704440000006b" "aa081101931100004102000065000000f701000000",
    )

    source._handle_notification(object(), packet)
    source._handle_notification(object(), packet)
    source._handle_notification(object(), packet)

    assert source._data_error is None
    assert source._malformed_count == 0
    assert source._queue.empty()


def test_fnirsi_internal_queue_drops_when_full() -> None:
    source = FnirsiSource(
        FnirsiSourceConfig(address="<mac-address>", internal_queue_maxsize=1),
    )
    sample = TelemetrySample(
        timestamp=dt.datetime.now(dt.UTC),
        source_name="fnb58",
        values={"voltage": 5.0, "current": 0.1, "power": 0.5},
    )

    source._enqueue_sample(sample)
    source._enqueue_sample(sample)

    assert source._queue.qsize() == 1


@pytest.mark.asyncio
async def test_fnirsi_start_subscribes_and_stop_disconnects(fake_bleak) -> None:
    source = FnirsiSource(FnirsiSourceConfig(address="<mac-address>"))

    await source.start()
    await source.start()
    client = fake_bleak.instances[0]
    await source.stop()

    assert source.name == "fnb58"
    assert client.is_connected is False
    assert client.writes == [
        (fnirsi_module.FNB58_WRITE_CHARACTERISTIC, payload)
        for payload in fnirsi_module.FNB58_ENABLE_STREAMING_WRITES
    ]
    assert client.notify_characteristic == fnirsi_module.FNB58_NOTIFY_CHARACTERISTIC
    assert client.stop_notify_calls == 1
    assert client.disconnect_calls == 1


@pytest.mark.asyncio
async def test_fnirsi_start_maps_connect_bleak_error(fake_bleak) -> None:
    fake_bleak.connect_error = BleakError("connect failed")
    source = FnirsiSource(FnirsiSourceConfig(address="<mac-address>"))

    with pytest.raises(SourceStartError):
        await source.start()


@pytest.mark.asyncio
async def test_fnirsi_start_maps_notify_bleak_error(fake_bleak) -> None:
    fake_bleak.start_notify_error = BleakError("notify failed")
    source = FnirsiSource(FnirsiSourceConfig(address="<mac-address>"))

    with pytest.raises(SourceStartError):
        await source.start()

    assert fake_bleak.instances[0].disconnect_calls == 1


@pytest.mark.asyncio
async def test_fnirsi_start_maps_unexpected_error(fake_bleak) -> None:
    fake_bleak.start_notify_error = RuntimeError("unexpected")
    source = FnirsiSource(FnirsiSourceConfig(address="<mac-address>"))

    with pytest.raises(SourceStartError):
        await source.start()


@pytest.mark.asyncio
async def test_fnirsi_samples_yield_notification_samples(fake_bleak) -> None:
    source = FnirsiSource(FnirsiSourceConfig(address="<mac-address>"))
    await source.start()
    client = fake_bleak.instances[0]

    client.notification_callback(object(), _packet())
    sample = await anext(source.samples())
    await source.stop()

    assert _sample_values(sample) == {
        "voltage": pytest.approx(5.02),
        "current": pytest.approx(0.123),
        "power": pytest.approx(5.02 * 0.123),
    }


@pytest.mark.asyncio
async def test_fnirsi_timeout_while_disconnected_raises_disconnect(fake_bleak) -> None:
    source = FnirsiSource(
        FnirsiSourceConfig(address="<mac-address>", sample_timeout_seconds=0.01),
    )
    await source.start()
    fake_bleak.instances[0].is_connected = False

    with pytest.raises(SourceDisconnectError):
        await anext(source.samples())

    await source.stop()


@pytest.mark.asyncio
async def test_fnirsi_disconnect_callback_causes_disconnect_on_timeout(fake_bleak) -> None:
    source = FnirsiSource(
        FnirsiSourceConfig(address="<mac-address>", sample_timeout_seconds=0.01),
    )
    await source.start()
    client = fake_bleak.instances[0]
    client.disconnected_callback(client)

    with pytest.raises(SourceDisconnectError):
        await anext(source.samples())

    await source.stop()


@pytest.mark.asyncio
async def test_fnirsi_timeout_while_connected_continues_until_stopped(fake_bleak) -> None:
    source = FnirsiSource(
        FnirsiSourceConfig(address="<mac-address>", sample_timeout_seconds=0.01),
    )
    await source.start()
    assert fake_bleak.instances

    task = asyncio.create_task(anext(source.samples()))
    await asyncio.sleep(0.03)
    assert not task.done()
    await source.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_fnirsi_stop_tolerates_stop_notify_and_disconnect_errors(fake_bleak) -> None:
    fake_bleak.stop_notify_error = BleakError("stop failed")
    fake_bleak.disconnect_error = BleakError("disconnect failed")
    source = FnirsiSource(FnirsiSourceConfig(address="<mac-address>"))

    await source.start()
    await source.stop()

    assert source._client is None
