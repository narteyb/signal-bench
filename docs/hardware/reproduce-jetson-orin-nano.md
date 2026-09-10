# Reproduce Jetson Orin Nano Bring-Up

Board: NVIDIA Jetson Orin Nano / Orin Nano Super developer kit.

This is the bench-proven path from a failed UEFI/SD boot state to a reachable
JetPack install for signal-bench Phase 1 Jetson work. Run Mac-side commands
from any directory unless noted.

## 1. Known-Good Baseline

Validated on 2026-08-05 after reflashing the SD card:

- Image: official NVIDIA JetPack 6.2 SD card image for Jetson Orin Nano.
- L4T: `R36.4.3`.
- Kernel: `5.15.148-tegra`.
- Root filesystem: `/dev/mmcblk0p1`, expanded to `116G` on a 128 GB SD card.

The LAN address is not stable enough to hard-code in scripts. Store host,
username, and authentication details in a local credential file that is not
committed.

## 2. Failure Signature

The failed SD image showed the NVIDIA UEFI screen, then errors such as:

```text
Attempting Recovery Boot
Failed to boot image: Invalid Parameter
Failed to boot recovery: 0 partition
Start HTTP Boot over IPv4
```

With no SD card installed, the UEFI shell listed internal firmware files under
`FS0:`. Do not assume `FS0:` is the SD card unless the SD card is installed and
the shell map confirms it. In the failed state, selecting `UEFI SD Device` could
blank the display or power down the board, which was treated as a bad or
incompatible boot image rather than a recoverable UEFI setting problem.

## 3. Reflash SD Card From macOS

Download the official JetPack 6.2 Orin Nano SD card image and keep it outside
the repo:

```bash
mkdir -p "$HOME/edge-bringup/images/jetson-orin-nano"
cd "$HOME/edge-bringup/images/jetson-orin-nano"
curl -L -o jp62-orin-nano-sd-card-image.zip \
  "https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v4.3/jp62-orin-nano-sd-card-image.zip"
unzip -t jp62-orin-nano-sd-card-image.zip
```

The validated archive contained `sd-blob.img` and passed `unzip -t`.

Identify the SD card. On the validated Mac, it appeared as `/dev/disk10`, but
this changes per machine and insertion:

```bash
diskutil list
```

Unmount and write with Raspberry Pi Imager. macOS may prompt for authorization;
approve it and do not close the prompt.

```bash
diskutil unmountDisk /dev/disk10
'/Applications/Raspberry Pi Imager.app/Contents/MacOS/rpi-imager' --cli \
  "$HOME/edge-bringup/images/jetson-orin-nano/jp62-orin-nano-sd-card-image.zip" \
  /dev/disk10
```

Expected successful ending:

```text
Write successful.
```

If `dd` returns `Operation not permitted` on macOS, use Raspberry Pi Imager as
above. It handles the required authorization path.

## 4. First Boot

Insert the SD card and boot the Jetson. On the first-boot Ubuntu/OEM setup:

1. Select language, keyboard, locale, and user account.
2. At `APP Partition Size`, leave the default maximum value in place and
   continue. For the validated 128 GB card, the maximum accepted size was
   `120746 MB`.
3. Finish setup and allow the desktop to start.

Create or update the local credential file on the Mac. This file intentionally
lives outside the repository. Use a private path such as:

```bash
$HOME/.config/signal-bench/jetson.env
```

Recommended shape:

```bash
JETSON_HOST=
JETSON_USERNAME=
JETSON_PASSWORD=
JETSON_SSH_KEY=
```

Use `chmod 600 "$HOME/.config/signal-bench/jetson.env"` so only the local Mac
user can read it. Do not commit this file or any device password.

## 5. Find The Jetson Address

On the Jetson, use:

```bash
hostname -I
```

If several addresses appear, prefer the LAN address for normal SSH:

- A home/office LAN address usually looks like `10.x.x.x` or `192.168.x.x`.
- `172.17.0.1` is commonly an internal Docker bridge and should be ignored.
- `192.168.55.1` is commonly the Jetson USB bridge and is useful only for USB
  networking when that link is in use.

Put only the chosen IPv4 address in the local credentials file:

```bash
JETSON_HOST=<jetson-lan-ip>
```

Do not include CIDR suffixes such as `/24`.

## 6. SSH Validation From The Mac

Load the local credentials and test SSH:

```bash
set -a
source "$HOME/.config/signal-bench/jetson.env"
set +a

ssh "$JETSON_USERNAME@$JETSON_HOST"
```

If key-based SSH is not set up yet, password SSH is expected. For noninteractive
checks on the bench Mac, `sshpass` can use the password from the env file
without echoing it:

```bash
set -a
source "$HOME/.config/signal-bench/jetson.env"
set +a

SSHPASS="$JETSON_PASSWORD" sshpass -e ssh \
  -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=accept-new \
  "$JETSON_USERNAME@$JETSON_HOST" \
  'hostname; cat /etc/nv_tegra_release; uname -a; df -h /'
```

Expected validated outputs:

```text
<jetson-hostname>
# R36 (release), REVISION: 4.3, ...
Linux <jetson-hostname> 5.15.148-tegra ...
/dev/mmcblk0p1  116G   20G   92G  18% /
```

## 7. Handoff State

The Jetson is ready for signal-bench work when all of these are true:

- SSH from the Mac succeeds using `JETSON_USERNAME@$JETSON_HOST`.
- `/etc/nv_tegra_release` reports `R36`, `REVISION: 4.3`.
- `uname -a` reports a `tegra` kernel.
- `df -h /` shows the root filesystem expanded to the SD card size.
- The repo contains no committed Jetson password or credential file.
