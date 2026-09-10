# Launch-Tier MCU Firmware

This directory contains the committed PlatformIO projects used for launch-tier
MCU reproduction. Each project is already staged with the model bytes and
selected input tensors used by the Post 1 MCU matrix, so a clean clone can build
and flash without Dan's local variant workspace.

Project names use `<target>-<task>`:

- `f401re-kws`, `f401re-ic`, `f401re-ad`
- `nano33-kws`, `nano33-ic`, `nano33-ad`
- `esp32s3-kws`, `esp32s3-ic`, `esp32s3-ad`

Build example:

```bash
pio run -d src/signal_bench/firmware/launch-tier/nano33-kws -e nano33ble
```

Flash example:

```bash
pio run -d src/signal_bench/firmware/launch-tier/nano33-kws -e nano33ble -t upload --upload-port <discovered-port>
```

The project files intentionally do not hard-code upload or monitor ports. Use
the port discovered on the reproducing host.
