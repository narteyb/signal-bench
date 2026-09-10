# SPDX-License-Identifier: Apache-2.0
"""Download pinned support artifacts from Hugging Face."""

from __future__ import annotations

import argparse

from signal_bench.artifacts import ensure_all_artifacts, ensure_artifact, known_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Artifact paths to fetch. Fetches all known support artifacts when omitted.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List known support artifacts without downloading them.",
    )
    args = parser.parse_args()

    if args.list:
        for artifact in known_artifacts():
            print(f"{artifact.path}\t{artifact.size}\t{artifact.sha256}")
        return

    paths = [ensure_artifact(path) for path in args.paths] if args.paths else ensure_all_artifacts()
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
