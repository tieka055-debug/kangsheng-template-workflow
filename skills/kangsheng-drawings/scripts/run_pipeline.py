#!/usr/bin/env python3
"""Run layout, build and deterministic checks as one fail-closed command."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(command):
    print("+", " ".join(map(str, command)), flush=True)
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    job = args.job.resolve()
    config = (args.config or job.with_name("candidate_config.json")).resolve()
    run([sys.executable, here / "auto_layout.py", job, "--output", config])
    run([sys.executable, here / "build_candidate.py", config])
    layout = config.parent / "layout.json"
    run([sys.executable, here / "check_layout.py", layout,
         "--output", config.parent / "layout_check.json"])
    print("LOCAL_CANDIDATE_READY", config.parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
