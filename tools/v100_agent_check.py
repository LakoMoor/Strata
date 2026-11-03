#!/usr/bin/env python3
"""Exercise a loaded server's multi-turn cache and queued HTTP clients.

Uses Strata's existing quick-check suite. It does not launch agents or execute
model-requested tools. The tool definitions and documents are test inputs only.
"""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--api-key-file", help="read the API key without putting it in command arguments")
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        ap.error("choose a new output file")
    sys.path.insert(0, str(Path(a.source_root) / "tools"))
    from strata_bench import Suite
    key = Path(a.api_key_file).read_text().strip() if a.api_key_file else os.environ.get("STRATA_KEY", "")
    suite = Suite(a.url.rstrip("/"), key, 262144, 1, False, quick=True,
                  log=lambda *args, **kwargs: print(*args, **kwargs, flush=True))
    suite.run_agent()
    suite.runs = 2
    for clients in (2, 4):
        suite.run_clients(clients)
        suite.out[f"clients{clients}"] = suite.out.pop("clients")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(suite.out, indent=2) + "\n")
    failed = bool(suite.out["failures"]) or any(suite.out[f"clients{n}"]["errors"] for n in (2, 4))
    print("PASS" if not failed else "FAIL", flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
