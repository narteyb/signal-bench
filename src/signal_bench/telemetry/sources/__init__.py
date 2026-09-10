# SPDX-License-Identifier: Apache-2.0
"""Telemetry source implementations."""

from signal_bench.telemetry.sources.bme280 import Bme280Config, Bme280Source
from signal_bench.telemetry.sources.bme280_mock import MockBME280Config, MockBME280Source
from signal_bench.telemetry.sources.fnirsi import FnirsiSource, FnirsiSourceConfig
from signal_bench.telemetry.sources.fnirsi_usb_hid import FnirsiHidSource, FnirsiHidSourceConfig
from signal_bench.telemetry.sources.ina219 import Ina219Config, Ina219Source
from signal_bench.telemetry.sources.ina219_mock import MockINA219Config, MockINA219Source
from signal_bench.telemetry.sources.jetson_ina3221 import JetsonIna3221Config, JetsonIna3221Source
from signal_bench.telemetry.sources.jetson_thermal import JetsonThermalConfig, JetsonThermalSource
from signal_bench.telemetry.sources.nvml import NvmlConfig, NvmlSource
from signal_bench.telemetry.sources.powermetrics import PowermetricsConfig, PowermetricsSource

__all__ = [
    "Bme280Config",
    "Bme280Source",
    "FnirsiHidSource",
    "FnirsiHidSourceConfig",
    "FnirsiSource",
    "FnirsiSourceConfig",
    "Ina219Config",
    "Ina219Source",
    "JetsonIna3221Config",
    "JetsonIna3221Source",
    "JetsonThermalConfig",
    "JetsonThermalSource",
    "MockBME280Config",
    "MockBME280Source",
    "MockINA219Config",
    "MockINA219Source",
    "NvmlConfig",
    "NvmlSource",
    "PowermetricsConfig",
    "PowermetricsSource",
]
