#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTML_URL="file://${SCRIPT_DIR}/index.html"
OG_PATH="${SCRIPT_DIR}/tinyml-reality-check-og.png"
THUMB_PATH="${SCRIPT_DIR}/preview-thumbnail.png"

npx playwright screenshot --viewport-size=1200,630 --wait-for-timeout=1500 "${HTML_URL}" "${OG_PATH}"

python3 - "${OG_PATH}" "${THUMB_PATH}" <<'PY'
import sys
from PIL import Image

source, target = sys.argv[1], sys.argv[2]
with Image.open(source) as image:
    thumbnail = image.resize((300, 158), Image.Resampling.LANCZOS)
    thumbnail.save(target)
PY
