# SPDX-License-Identifier: Apache-2.0
"""Protocol configuration loaders."""

from __future__ import annotations

from importlib import resources
from typing import Any

import yaml


def load_n3_floors() -> dict[str, Any]:
    """Load Phase 5 N3 accuracy floor configuration."""
    text = resources.files(__package__).joinpath("n3.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        msg = "protocols/n3.yaml must contain a mapping"
        raise TypeError(msg)
    floors = data.get("n3_accuracy_floors")
    if not isinstance(floors, dict):
        msg = "protocols/n3.yaml missing n3_accuracy_floors"
        raise TypeError(msg)
    return floors
