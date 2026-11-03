#!/usr/bin/env python3
"""Compare opt-in V100 settings using an installed Strata and synthetic code prompts.

This is a local tuning experiment, not the standard Strata benchmark. Each arm
owns a separate server process group. No running server is stopped or modified.
Results include errors, full synthetic answers, hashes and engine timings.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import socket
import statistics
import subprocess
import time
import urllib.error
import urllib.request


ARMS = {
    "baseline": ({}, {}),
    "candidate": ({}, {}),
    "volta": ({"STRATA_SM70_TABLE": "1"}, {}),
    "fused": ({"STRATA_SM70_TABLE": "1", "STRATA_FUSE_DECODE": "1"}, {}),
    "wmma": ({"STRATA_SM70_TABLE": "1", "STRATA_FUSE_DECODE": "1", "STRATA_PF_WMMA": "1"}, {}),
    "spec2": ({}, {"--spec": "2"}),
    "spec3": ({}, {"--spec": "3"}),
    "spec4": ({}, {"--spec": "4"}),
    "spec6": ({}, {"--spec": "6"}),
    "workers8": ({}, {"--pool-workers": "8"}),
    "workers16": ({}, {"--pool-workers": "16"}),
    "workers24": ({}, {"--pool-workers": "24"}),
    "workers32": ({}, {"--pool-workers": "32"}),
    "workers48": ({}, {"--pool-workers": "48"}),
    "pcie0": ({}, {"--pcie-frac": "0"}),
    "pcie30": ({}, {"--pcie-frac": "0.30"}),
    "pcie60": ({}, {"--pcie-frac": "0.60"}),
    "ple_ram": ({}, {"--ple-io": "ram"}),
    "ple_mmap": ({}, {"--ple-io": "mmap"}),
    "p4_6": ({"STRATA_PF_WMMA": "0", "STRATA_PF_WMMA2": "0"}, {"--trim-stage-weights": True}),
    "p4_12": ({"STRATA_PF_WMMA": "0", "STRATA_PF_WMMA2": "0"}, {"--trim-stage-weights": True}),
}
CONFIG_OVERRIDES = {
    name: {"gpu": [1, 0], "gpu_roles": {"1": "helper", "0": "main"},
           "gpu_order": "as_given", "gpus_asked": True, "layer_split": split}
    for name, split in (("p4_6", "6"), ("p4_12", "12"))
}


def set_args(args, overrides):
    args = list(args)
    for flag, value in overrides.items():
        while flag in args:
            i = args.index(flag)
            del args[i:i + (1 if value is True else 2)]
        args.append(flag)
        if value is not True:
            args.append(value)
    return args


def call(base, path, body=None, timeout=1800):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def prompts(words):
    rng = random.Random(472)
    vocab = "cache request token queue index lock worker result timeout retry buffer stream client server".split()
    filler = " ".join(rng.choice(vocab) for _ in range(words))
    return [
        ("code", "Write a complete Python module implementing a thread-safe bounded LRU cache with TTL, type hints, "
         "a monotonic clock, and unittest cases for expiration, eviction and updates. Include all code. No explanations."),
        ("code_context", "Review this synthetic project log:\n" + filler + "\n\nWrite a complete asyncio worker pool "
         "module with bounded queues, retries, timeouts, graceful shutdown and error propagation. Include unit tests. "
         "Return Python code only."),
    ]


def stop(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(45)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--strata", required=True)
    parser.add_argument("--candidate-config", help="a second complete config for the candidate arm")
    parser.add_argument("--arms", default="baseline,volta,fused,wmma")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--max-new", type=int, default=384)
    parser.add_argument("--long-words", type=int, default=3500)
    parser.add_argument("--out", required=True)
    a = parser.parse_args()
    names = a.arms.split(",")
    for name in names:
        if name not in ARMS:
            parser.error(f"unknown arm {name}; choices: {','.join(ARMS)}")
    base_cfg = json.loads(Path(a.config).read_text())
    candidate = json.loads(Path(a.candidate_config).read_text()) if a.candidate_config else None
    if "candidate" in names and candidate is None:
        parser.error("the candidate arm requires --candidate-config")
    if any(cfg.get("api_key") or cfg.get("api_key_env") for cfg in (base_cfg, candidate or {})):
        parser.error("use a local benchmark config without authentication")
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "requests.jsonl").exists():
        parser.error("choose a fresh output folder; previous evidence is never overwritten")
    metadata = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "config_sha256": hashlib.sha256(Path(a.config).read_bytes()).hexdigest(),
                "candidate_config_sha256": hashlib.sha256(Path(a.candidate_config).read_bytes()).hexdigest() if candidate else None,
                "strata_version": subprocess.check_output([a.strata, "--version"], text=True).strip(),
                "arms": {name: {"env": ARMS[name][0], "args": ARMS[name][1],
                                "config": CONFIG_OVERRIDES.get(name, {})} for name in names},
                "rounds": a.rounds, "max_new": a.max_new, "long_words": a.long_words,
                "temperature": 0, "seed": 42, "thinking": False,
                "limits": "synthetic coding prompts; adaptive caches; no code execution or quality score"}
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    base = f"http://127.0.0.1:{a.port}"
    results = []
    with (out / "requests.jsonl").open("a") as evidence:
        for rnd in range(a.rounds):
            for name in (names if rnd % 2 == 0 else names[::-1]):
                with socket.socket() as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(("127.0.0.1", a.port))
                cfg = copy.deepcopy(candidate if name == "candidate" else base_cfg)
                cfg.update(CONFIG_OVERRIDES.get(name, {}))
                env, overrides = ARMS[name]
                cfg.update(host="127.0.0.1", port=a.port)
                cfg["env"] = {**cfg.get("env", {}), **env}
                cfg["args"] = set_args(cfg.get("args", []), overrides)
                cfg["log"] = str(out / f"{rnd}-{name}-engine.log")
                config = out / f"{rnd}-{name}.json"
                config.write_text(json.dumps(cfg, indent=2) + "\n")
                with (out / f"{rnd}-{name}-server.log").open("w") as log:
                    proc = subprocess.Popen([a.strata, "serve", "--config", str(config)],
                                            stdout=log, stderr=log, start_new_session=True)
                    try:
                        deadline = time.monotonic() + 1200
                        while True:
                            if proc.poll() is not None:
                                raise RuntimeError(f"server exited {proc.returncode}; see server log")
                            try:
                                health = call(base, "/health", timeout=5)
                                if health.get("status") not in ("ok", "ready"):
                                    raise RuntimeError(f"not ready: {health}")
                                call(base, "/v1/chat/completions", {"model": "strata", "messages": [
                                    {"role": "user", "content": "Reply with OK."}], "max_tokens": 8,
                                    "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}, timeout=300)
                                break
                            except (OSError, ValueError, RuntimeError):
                                if time.monotonic() >= deadline:
                                    raise TimeoutError("server did not become ready")
                                time.sleep(2)
                        print(f"round={rnd} arm={name} ready", flush=True)
                        for tag, prompt in prompts(a.long_words):
                            t0 = time.monotonic()
                            response = call(base, "/v1/chat/completions", {
                                "model": "strata", "messages": [{"role": "user", "content":
                                    f"[experiment {tag}]\n" + prompt}],
                                "temperature": 0, "seed": 42, "max_tokens": a.max_new,
                                "chat_template_kwargs": {"enable_thinking": False}})
                            elapsed = time.monotonic() - t0
                            text = response["choices"][0]["message"].get("content") or ""
                            row = {"round": rnd, "arm": name, "request": tag,
                                   "elapsed_s": elapsed, "usage": response.get("usage"),
                                   "timings": response.get("timings", {}),
                                   "finish_reason": response["choices"][0].get("finish_reason"),
                                   "sha256": hashlib.sha256(text.encode()).hexdigest(), "text": text}
                            if not text.strip():
                                raise RuntimeError("empty answer")
                            results.append(row)
                            evidence.write(json.dumps(row) + "\n")
                            evidence.flush()
                            print(json.dumps({k: v for k, v in row.items() if k != "text"}), flush=True)
                    except Exception as error:
                        row = {"round": rnd, "arm": name, "error": str(error)}
                        results.append(row)
                        evidence.write(json.dumps(row) + "\n")
                        evidence.flush()
                        print(json.dumps(row), flush=True)
                    finally:
                        stop(proc)
                time.sleep(2)
    summary = {}
    for name in names:
        summary[name] = {}
        for tag, _ in prompts(a.long_words):
            rows = [r for r in results if r["arm"] == name and r.get("request") == tag]
            metrics = {}
            for key in ("prompt_per_second", "predicted_per_second"):
                values = [r["timings"][key] for r in rows if r["timings"].get(key)]
                metrics[key] = {"median": statistics.median(values), "min": min(values), "max": max(values)} if values else None
            summary[name][tag] = {"runs": len(rows), **metrics}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    return int(any("error" in row for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
