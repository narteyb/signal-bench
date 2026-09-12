# SPDX-License-Identifier: Apache-2.0
"""Canonicalize the names and serialization order of a converted ONNX graph."""

from __future__ import annotations

import argparse
from pathlib import Path

import onnx
from onnx import TensorProto


def main() -> None:
    """Canonicalize one ONNX model in place or to a separate path."""
    args = _parse_args()
    output_path = args.input_path if args.in_place else args.output_path
    if output_path is None:
        msg = "provide OUTPUT or use --in-place"
        raise SystemExit(msg)
    model = onnx.load(args.input_path)
    _canonicalize_graph(model.graph)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(model.SerializeToString(deterministic=True))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", type=Path)
    parser.add_argument("output_path", type=Path, nargs="?")
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args()
    if args.in_place and args.output_path is not None:
        parser.error("--in-place cannot be combined with OUTPUT")
    return args


def _canonicalize_graph(graph: onnx.GraphProto) -> None:
    if _has_subgraph(graph):
        msg = "canonicalization of nested ONNX subgraphs is not supported"
        raise ValueError(msg)

    names, initializers = _build_name_map(graph)
    _rewrite_graph(graph, names, initializers)


def _build_name_map(
    graph: onnx.GraphProto,
) -> tuple[dict[str, str], list[TensorProto]]:
    """Build stable names while retaining the model's public IO names."""
    names: dict[str, str] = {}
    public_names = {value_info.name for value_info in (*graph.input, *graph.output)}
    for value_info in graph.input:
        names[value_info.name] = value_info.name

    initializers = sorted(graph.initializer, key=_tensor_key)
    for index, initializer in enumerate(initializers):
        names[initializer.name] = f"initializer_{index}"

    for node_index, node in enumerate(graph.node):
        for output_index, output in enumerate(node.output):
            if output:
                names[output] = (
                    output if output in public_names else f"value_{node_index}_{output_index}"
                )
    return names, initializers


def _rewrite_graph(
    graph: onnx.GraphProto,
    names: dict[str, str],
    initializers: list[TensorProto],
) -> None:
    """Apply stable names and protobuf field normalization."""
    for node_index, node in enumerate(graph.node):
        node.name = f"node_{node_index}_{node.op_type}"
        if not node.domain:
            node.ClearField("domain")
        node.input[:] = [_mapped_name(name, names) for name in node.input]
        node.output[:] = [_mapped_name(name, names) for name in node.output]

    for value_info in (*graph.input, *graph.output, *graph.value_info):
        value_info.name = _mapped_name(value_info.name, names)
    for initializer in initializers:
        initializer.name = _mapped_name(initializer.name, names)

    del graph.initializer[:]
    graph.initializer.extend(initializers)
    graph.name = "signal_bench_model"


def _mapped_name(name: str, names: dict[str, str]) -> str:
    if not name:
        return name
    if name not in names:
        names[name] = f"external_{len(names)}"
    return names[name]


def _tensor_key(tensor: TensorProto) -> bytes:
    copy = TensorProto()
    copy.CopyFrom(tensor)
    copy.name = ""
    return copy.SerializeToString(deterministic=True)


def _has_subgraph(graph: onnx.GraphProto) -> bool:
    return any(
        attribute.g.ByteSize() or attribute.graphs
        for node in graph.node
        for attribute in node.attribute
    )


if __name__ == "__main__":
    main()
