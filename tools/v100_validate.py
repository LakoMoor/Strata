#!/usr/bin/env python3
"""Validate real long-context recall and an accepted 64K output budget.

Synthetic filler, greedy decoding, thinking off. Counts the rendered prompt using
the server before generating; records actual completion usage separately.
This is a small recall check, not an overall coding-quality benchmark.
"""
import argparse
import json
from pathlib import Path
import random
import time
import urllib.request


def request(base, path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as response:
        return json.load(response)


def prompt(words, depth, token, seed, corpus=None):
    rng = random.Random(seed)
    vocab = ("river stone market lantern copper winter garden signal harbor needle orbit velvet canyon ember ledger quartz "
             "meadow anchor violet thunder cedar marble piston ribbon cobalt falcon glacier hollow ivory juniper kernel "
             "lattice mirror nectar oasis pepper quarry raven saddle tundra umber vessel willow xenon yellow zephyr").split()
    body = corpus[:words] if corpus is not None else " ".join(rng.choice(vocab) for _ in range(words))
    at = int(len(body) * depth / 100)
    body = body[:at] + f"\nThe unique deployment token is {token}.\n" + body[at:]
    return ("Remember the unique deployment token stated once in this test document.\n<DOCUMENT>\n" +
            body + "\n</DOCUMENT>\nWhat is the deployment token? Reply only with that token.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:18080")
    ap.add_argument("--out", required=True)
    ap.add_argument("--corpus-root", help="also check 128K of public Strata C++ and documentation")
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        ap.error("choose a new output file")
    out.parent.mkdir(parents=True, exist_ok=True)
    base = a.url.rstrip("/")
    health = request(base, "/health")
    model = health["model"]
    cases = [(32768, 10, None), (32768, 50, None), (32768, 90, None), (131072, 50, None), (196000, 50, None)]
    if a.corpus_root:
        root = Path(a.corpus_root)
        files = sorted((root / "src").rglob("*.cpp")) + sorted((root / "docs").glob("*.md"))
        corpus = "\n\n".join(p.read_text(errors="replace") for p in files)
        if len(corpus) < 1000000:
            raise ValueError("the public source corpus is too short")
        cases.append((131072, 50, corpus))
    results = {"health": health, "thinking": False, "temperature": 0,
               "cases": [], "full_65536_token_generation_exercised": False}
    for index, (target, depth, corpus) in enumerate(cases):
        token = f"copper-falcon-{random.Random(901 + index).randrange(100000, 1000000)}"
        words = max(100, int(target * (3.2 if corpus is not None else 0.8)))
        for _ in range(6):
            text = prompt(words, depth, token, 73 + index, corpus)
            count = request(base, "/v1/messages/count_tokens", {
                "model": model, "messages": [{"role": "user", "content": text}],
                "thinking": {"type": "disabled"}})["input_tokens"]
            if abs(count - target) < 32:
                break
            words = max(100, int(words * target / count))
        t0 = time.monotonic()
        output_cap = 65536 if target == 196000 else 64
        if count + output_cap > health["max_context"]:
            raise ValueError("the counted prompt plus output budget exceeds the real window")
        try:
            response = request(base, "/v1/chat/completions", {
                "model": model, "messages": [{"role": "user", "content": text}],
                "max_tokens": output_cap, "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False}})
            answer = response["choices"][0]["message"].get("content") or ""
            row = {"target": target, "depth_percent": depth, "counted_input": count,
                   "corpus": "source_code" if corpus is not None else "random_words",
                   "requested_max_tokens": output_cap,
                   "usage": response.get("usage"), "timings": response.get("timings"),
                   "expected": token, "answer": answer, "found": token in answer,
                   "seconds": time.monotonic() - t0}
        except Exception as error:
            row = {"target": target, "depth_percent": depth, "error": str(error), "found": False}
        results["cases"].append(row)
        out.write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(row), flush=True)
    response = request(base, "/v1/chat/completions", {
        "model": model, "messages": [{"role": "user", "content": "Reply exactly READY."}],
        "max_tokens": 65536, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False}})
    results["output_budget"] = {"requested_max_tokens": 65536, "http_accepted": True,
                                "usage": response.get("usage"), "choices": response["choices"]}
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results["output_budget"]), flush=True)
    return int(not all(row["found"] for row in results["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
