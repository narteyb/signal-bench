# MCU session metadata contract

New `run_p3_mcu_matrix.py` measurement runs write `runs.extra.session_contract`
before telemetry starts. The host hashes the built firmware image and records
the source commit, a hash over the staged source and PlatformIO config, and a
fresh build ID embedded in this image.
It asks the running firmware for a `META` frame and rejects a build ID or commit
mismatch. `--skip-upload` therefore cannot silently measure an older image.

The version 1 contract contains:

| Field | Capture source |
|---|---|
| `firmware_build_sha256`, `build_id`, `source_commit`, `source_tree_sha256`, `platformio_env` | Build output and Git at staging time; firmware echoes the unique per-build ID and source commit. |
| `radio.wifi_initialized`, `radio.bluetooth_initialized`, `radio.basis` | Firmware `META` response. ESP32 queries its Wi-Fi and Bluetooth controller state; the generated Nano/F401RE application has no radio initialization call, and the build audit rejects new calls until runtime reporting is added. The basis distinguishes a controller query from a source/framework audit. |
| `sleep.calls_during_inference`, `loop_pacing_ms` | Build audit of the generated `RUN` loop, emitted by that firmware. Unknown sleep/pacing calls fail staging instead of being reported as zero. This describes application calls, not physical sleep residency or CPU active fraction. |
| `regulator_mode` | Nano firmware reads the nRF52840 DC/DC enable registers at the metadata query. Other boards report that their external regulator mode is not firmware-controlled; the installed regulator part is not inferred. |
| `power_boundary.rail`, `components_inside`, `source` | The runner copies the versioned rig-path declaration automatically. `physically_verified_by_instrument=false` is mandatory because a current meter cannot identify external wiring or which components lie downstream of its shunt. |

The last field is a **declaration**, not automated physical verification. A
future rig with topology sensing can replace that provenance. Until then,
changing a cable or jumper requires updating the versioned rig configuration;
the session record must not claim that the instrument itself verified the path.
Original published runs are not retroactively assigned these fields.
