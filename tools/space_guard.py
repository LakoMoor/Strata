#!/usr/bin/env python3
"""Run an owned preparation command, stopping its process group if disk is low."""
import argparse
import os
import shutil
import signal
import subprocess
import time


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", required=True)
    ap.add_argument("--min-free-gib", type=float, default=6)
    ap.add_argument("command", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    command = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not command:
        ap.error("a command is required after --")
    floor = a.min_free_gib * 2**30
    if shutil.disk_usage(a.path).free < floor:
        raise SystemExit("Space guard: insufficient initial free space")
    proc = subprocess.Popen(command, start_new_session=True)
    try:
        while proc.poll() is None:
            if shutil.disk_usage(a.path).free < floor:
                print("Space guard: stopping owned preparation to preserve disk headroom", flush=True)
                return 73
            time.sleep(0.1)
        return proc.returncode
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
