# SPDX-License-Identifier: Apache-2.0
"""Tests for Hailo X-corpus accuracy proxy helpers."""

from __future__ import annotations

import argparse
import datetime as dt

import numpy as np

from scripts.run_p4_hailo_first_light import RemoteInferenceResult, _accuracy_proxy


def test_anomaly_proxy_groups_frame_scores_by_source(tmp_path) -> None:
    input_path = tmp_path / "ad_frames.npz"
    np.savez_compressed(
        input_path,
        inputs=np.zeros((4, 1), dtype=np.float32),
        labels=np.array([0, 0, 1, 1], dtype=np.int64),
        sources=np.array(["normal.wav", "normal.wav", "anomaly.wav", "anomaly.wav"]),
    )
    results = [
        RemoteInferenceResult(
            iter_id=index,
            duration_us=100,
            timestamp=dt.datetime.now(dt.UTC),
            output={"values": [value]},
            error=None,
        )
        for index, value in enumerate([0.0, 0.2, 2.0, 3.0])
    ]

    proxy = _accuracy_proxy(
        results,
        argparse.Namespace(input_data=input_path, task_family="anomaly_detection"),
    )

    assert proxy is not None
    assert proxy["metric"] == "clip_auroc"
    assert proxy["groups"] == 2
    assert proxy["samples"] == 4
    assert proxy["value"] == 1.0
