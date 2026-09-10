# SPDX-License-Identifier: Apache-2.0
"""Discover launch-tier serial, I2C, and FNB58 BLE devices."""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from serial.tools import list_ports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ble-timeout-s", type=float, default=8.0)
    parser.add_argument("--skip-ble", action="store_true")
    parser.add_argument("--skip-i2c", action="store_true")
    args = parser.parse_args()

    print("Serial ports:")
    for port in sorted(list_ports.comports(), key=lambda item: item.device):
        vid_pid = "n/a"
        if port.vid is not None and port.pid is not None:
            vid_pid = f"{int(port.vid):04X}:{int(port.pid):04X}"
        serial = f" SER={port.serial_number}" if port.serial_number else ""
        print(f"- {port.device}: {port.description} VID:PID={vid_pid}{serial}")

    if not args.skip_i2c:
        print("\nI2C scan:")
        try:
            addresses = _scan_i2c()
        except Exception as exc:
            print(f"- unavailable: {exc}")
        else:
            print(f"- {[hex(address) for address in addresses]}")

    if not args.skip_ble:
        print("\nFNB58 BLE candidates:")
        try:
            devices = asyncio.run(_scan_ble(args.ble_timeout_s))
        except Exception as exc:
            print(f"- unavailable: {exc}")
        else:
            candidates = [
                device
                for device in devices
                if "FNB" in device["name"].upper() or "FNIRSI" in device["name"].upper()
            ]
            if not candidates:
                print("- none found")
            for device in candidates:
                print(f"- {device['address']}: {device['name']} RSSI={device['rssi']}")
    return 0


def _scan_i2c() -> list[int]:
    import board
    import busio

    i2c = busio.I2C(board.SCL, board.SDA)
    while not i2c.try_lock():
        pass
    try:
        return list(i2c.scan())
    finally:
        i2c.unlock()


async def _scan_ble(timeout_s: float) -> list[dict[str, Any]]:
    from bleak import BleakScanner

    discovered = await BleakScanner.discover(timeout=timeout_s, return_adv=True)
    devices: list[dict[str, Any]] = []
    for address, (device, adv) in discovered.items():
        devices.append(
            {
                "address": address,
                "name": device.name or adv.local_name or "",
                "rssi": adv.rssi,
            },
        )
    return sorted(devices, key=lambda item: (item["name"], item["address"]))


if __name__ == "__main__":
    raise SystemExit(main())
