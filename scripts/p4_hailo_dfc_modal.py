# SPDX-License-Identifier: Apache-2.0
"""Dedicated Modal lane for P4 Hailo DFC 5.3.0 compilation.

This app is intentionally separate from any measurement Modal function. It only
translates/optimizes/compiles X-corpus models to local HEF artifacts in the
`hailo-dfc` Modal Volume.
"""


from __future__ import annotations

import json
import subprocess
import sys
import time
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import modal

APP_NAME = "hailo-dfc-compile"
VOLUME_NAME = "hailo-dfc"
DFC_ROOT = Path("/dfc")
WHEEL = DFC_ROOT / "hailo_dataflow_compiler-5.3.0-py3-none-linux_x86_64.whl"
RUNTIME_DEPS = ("psutil",)

app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

TASKS = {
    "ic": {
        "model_rel": "inputs/ic/ic_float.tflite",
        "calib_rel": "inputs/ic/calib.npy",
        "output_rel": "outputs/ic",
    },
    "kws": {
        "model_rel": "inputs/kws/kws_float.tflite",
        "calib_rel": "inputs/kws/calib.npy",
        "output_rel": "outputs/kws",
    },
    "ad": {
        "model_rel": "inputs/ad/ad_float.tflite",
        "calib_rel": "inputs/ad/calib.npy",
        "output_rel": "outputs/ad",
    },
}

image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04", add_python="3.10")
    .apt_install(
        "build-essential",
        "python3-dev",
        "python3-venv",
        "python3-pip",
        "clang",
        "liblapack-dev",
        "libatlas-base-dev",
        "graphviz",
        "libgraphviz-dev",
        "libgl1",
        "pkg-config",
        "git",
    )
    .pip_install(
        "absl-py",
        "argcomplete",
        "contextlib2",
        "future",
        "jsonref",
        "jsonschema",
        "matplotlib==3.5.2",
        "matplotlib-inline==0.1.6",
        "networkx==2.8.8",
        "packaging",
        "pandas",
        "Pillow",
        "prompt-toolkit",
        "pwlf",
        "py",
        "pydantic==2.0.2",
        "pydantic-core==2.1.2",
        "pygraphviz",
        "PyYAML",
        "scipy==1.12.0",
        "tabulate",
        "verboselogs",
        "testresources",
        "h5py",
        "disjoint-set",
        "importlib-metadata",
        "grpcio",
        "six",
        "typing-extensions==4.12.2",
        "wheel",
        "onnx-tf",
        "pyparsing==2.4.7",
        "tqdm",
        "py-cpuinfo",
        "msgpack",
        "prettytable==3.5.0",
        "tensorflow-probability==0.20.1",
        "tensorflow==2.19.1",
        "keras==3.5.0",
        "numpy==1.26.4",
        "onnxscript~=0.5.0",
        "einops",
        "flatbuffers==24.3.25",
        "protobuf==3.20.3",
        "onnx==1.17.0",
        "onnxsim==0.4.36",
        "onnxruntime==1.18.0",
        "safetensors",
        "tflite==2.18.0",
        "tensorboard~=2.19.0",
        "tensordict==0.9.0",
        "torch==2.9.1",
        "torchvision==0.24.1",
        "gast<=0.4.0,>=0.3.2",
        "xxhash==3.5.0",
        "setuptools",
    )
)


def _ensure_dfc_installed() -> None:
    if find_spec("hailo_sdk_client") is not None:
        return
    if not WHEEL.exists():
        msg = f"DFC wheel missing in Modal Volume: {WHEEL}"
        raise FileNotFoundError(msg)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", *RUNTIME_DEPS],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", str(WHEEL)],
        check=True,
    )


def _gpu_info() -> str:
    process = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        text=True,
        capture_output=True,
        check=False,
    )
    return process.stdout.strip() or process.stderr.strip()


@app.function(image=image, gpu="A10G", timeout=1800, volumes={str(DFC_ROOT): volume})
def smoke_test() -> dict[str, Any]:
    """Verify DFC import/version and GPU visibility inside the compile lane."""
    _ensure_dfc_installed()
    import hailo_sdk_client

    return {
        "dfc_version": hailo_sdk_client.__version__,
        "gpu": _gpu_info(),
        "wheel": str(WHEEL),
        "app": APP_NAME,
    }


@app.function(image=image, gpu="A10G", timeout=21600, volumes={str(DFC_ROOT): volume})
def compile_tflite(
    task: str,
    model_rel: str,
    calib_rel: str,
    output_rel: str,
) -> dict[str, Any]:
    """Compile one float TFLite model to a Hailo-10H HEF."""
    started = time.time()
    _ensure_dfc_installed()
    import numpy as np
    from hailo_sdk_client import CalibrationDataType, ClientRunner

    model_path = DFC_ROOT / model_rel
    calib_path = DFC_ROOT / calib_rel
    output_dir = DFC_ROOT / output_rel
    output_dir.mkdir(parents=True, exist_ok=True)
    if not model_path.exists():
        raise FileNotFoundError(model_path)
    if not calib_path.exists():
        raise FileNotFoundError(calib_path)

    calib = np.load(calib_path).astype(np.float32)
    runner = ClientRunner(hw_arch="hailo10h")
    hn, _params = runner.translate_tf_model(model_path=str(model_path), net_name=f"p4_{task}")
    opt_dir = output_dir / "opt"
    opt_dir.mkdir(parents=True, exist_ok=True)
    runner.optimize(calib, data_type=CalibrationDataType.np_array, work_dir=str(opt_dir))
    har_path = output_dir / f"{task}_hailo10h.har"
    runner.save_har(str(har_path), compressed=True, save_original_model=False)
    hef = runner.compile()
    hef_path = output_dir / f"{task}_hailo10h.hef"
    hef_path.write_bytes(hef)

    payload = {
        "task": task,
        "hw_arch": runner.hw_arch,
        "dfc_version": __import__("hailo_sdk_client").__version__,
        "gpu": _gpu_info(),
        "model_path": str(model_path),
        "calib_path": str(calib_path),
        "calib_shape": list(calib.shape),
        "hef_path": str(hef_path),
        "har_path": str(har_path),
        "hef_size_bytes": hef_path.stat().st_size,
        "har_size_bytes": har_path.stat().st_size,
        "elapsed_s": time.time() - started,
        "hn_prefix": hn[:200] if isinstance(hn, str) else str(type(hn)),
    }
    (output_dir / f"{task}_compile_metadata.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    volume.commit()
    return payload


@app.local_entrypoint()
def main(action: str = "smoke", task: str = "all") -> None:
    """CLI entrypoint for Modal: smoke-test DFC or compile one/all tasks."""
    if action == "smoke":
        print(json.dumps(smoke_test.remote(), indent=2, sort_keys=True))
        return
    if action != "compile":
        raise ValueError(f"Unknown action {action!r}; expected 'smoke' or 'compile'")

    tasks = list(TASKS) if task == "all" else [task]
    for item in tasks:
        if item not in TASKS:
            raise ValueError(f"Unknown task {item!r}; expected one of {sorted(TASKS)} or 'all'")
        payload = compile_tflite.remote(item, **TASKS[item])
        print(json.dumps(payload, indent=2, sort_keys=True))
