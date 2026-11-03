#!/usr/bin/env python3
"""Restore the pinned IQ4_NL n-gram shard from an unchanged NInfer v3 table.

Only the GGUF's 192-byte header is downloaded. The existing NInfer file is read
only. A new file is published only if its SHA-256 matches Strata's upstream pin.
This helper is specific to this model and encoding; it never requantizes weights.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import time
import urllib.request

SIZE = 28800138432
SHA256 = "316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113"
URL = ("https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF/resolve/"
       "5348543e0147355ac9cbcb031184a3546350988e/IQ1_M/"
       "Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00002-of-00002.gguf")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    src, dst = Path(a.source), Path(a.output)
    tmp = dst.with_name(dst.name + ".restoring")
    if dst.exists() or tmp.exists():
        ap.error("output or temporary output already exists")
    with src.open("rb") as source:
        prefix = source.read(32)
        if prefix[:8] != b"NINFER\0\x03":
            raise ValueError("expected NInfer v3")
        header_n = struct.unpack_from("<Q", prefix, 8)[0]
        if not 0 < header_n < 16 * 1024 * 1024:
            raise ValueError("invalid NInfer header length")
        metadata = json.loads(source.read(header_n))
        table = next(x for x in metadata["objects"] if x["id"] == metadata["bindings"]["ngram/table"]["object"])
        if (table["shape"] != [320001536, 160] or table["format"] != "gguf_iq4_nl"
                or table["layout"] != "gguf_blocks_v1" or table["bytes"] != SIZE - 192):
            raise ValueError("the source table has a different encoding or shape")
        # v3 payload begins immediately after its 32-byte prefix and JSON header.
        offset = 32 + header_n + table["offset"]
        if offset + table["bytes"] > src.stat().st_size:
            raise ValueError("truncated source")
        req = urllib.request.Request(URL, headers={"Range": "bytes=0-191"})
        with urllib.request.urlopen(req, timeout=60) as response:
            if response.status != 206 or response.headers.get("Content-Range") != f"bytes 0-191/{SIZE}":
                raise ValueError("the server did not honor the exact header range")
            header = response.read(193)
        if len(header) != 192 or header[:4] != b"GGUF":
            raise ValueError("invalid GGUF header")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if os.statvfs(dst.parent).f_bavail * os.statvfs(dst.parent).f_frsize < SIZE + (1 << 30):
            raise ValueError("not enough disk space for the restored shard plus 1 GiB")
        started = time.monotonic()
        digest = hashlib.sha256(header)
        source.seek(offset)
        with tmp.open("xb") as target:
            target.write(header)
            remaining = table["bytes"]
            checkpoint = 0
            while remaining:
                chunk = source.read(min(16 << 20, remaining))
                if not chunk:
                    raise ValueError("source ended early")
                target.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
                copied = table["bytes"] - remaining
                if copied // (4 << 30) > checkpoint:
                    checkpoint = copied // (4 << 30)
                    print(f"restored {copied / 1e9:.1f} GB", flush=True)
            target.flush()
            os.fsync(target.fileno())
        actual = digest.hexdigest()
        if actual != SHA256:
            raise ValueError(f"SHA-256 mismatch: {actual}; temporary file retained for diagnosis")
        if tmp.stat().st_size != SIZE:
            raise ValueError("wrong output size")
        os.rename(tmp, dst)
        print(json.dumps({"bytes": SIZE, "sha256": actual, "seconds": time.monotonic() - started,
                          "network_bytes": 192, "source_modified": False}), flush=True)


if __name__ == "__main__":
    main()
