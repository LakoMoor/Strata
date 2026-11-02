#!/usr/bin/env python3
"""Execute a shell command via an authenticated Jupyter terminal.

Authentication is kept outside the checkout in a mode-0600 session file.
Use only with a Jupyter server you administer.
"""
import argparse
import base64
import json
import pathlib
import re
import secrets
import time
from urllib.parse import urlparse

import requests
import websocket


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="/tmp/strata-jupyter-session.json")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("command")
    args = parser.parse_args()
    config = json.loads(pathlib.Path(args.session).read_text())
    base = config["url"].rstrip("/")
    session = requests.Session()
    session.cookies.update(config["cookies"])
    session.headers["X-XSRFToken"] = session.cookies.get("_xsrf", "")
    response = session.post(base + "/api/terminals", json={}, timeout=20)
    response.raise_for_status()
    name = response.json()["name"]
    cookie = "; ".join(f"{k}={v}" for k, v in config["cookies"].items())
    url = base.replace("http://", "ws://").replace("https://", "wss://")
    ws = websocket.create_connection(
        f"{url}/terminals/websocket/{name}", cookie=cookie,
        origin=f"{urlparse(base).scheme}://{urlparse(base).netloc}", timeout=5,
    )
    marker = "STRATA_DONE_" + secrets.token_hex(12)
    encoded = base64.b64encode(args.command.encode()).decode()
    begin = marker + "_BEGIN"
    shell = f"printf '\\n{begin}\\n'; echo {encoded} | base64 -d | bash; printf '\\n{marker}:%s\\n' $?\r"
    ws.send(json.dumps(["stdin", shell]))
    output = ""
    start = time.monotonic()
    try:
        while time.monotonic() - start < args.timeout:
            try:
                message = json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if message[0] == "stdout":
                output += message[1]
                match = re.search(r"\r?\n" + marker + r":(\d+)\r?\n", output)
                if match:
                    clean = output[:match.start()].split("\n" + begin + "\r\n", 1)[-1]
                    clean = "\n".join(line for line in clean.splitlines() if encoded not in line)
                    print(re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", clean).strip())
                    raise SystemExit(int(match[1]))
        print(output)
        raise TimeoutError("Remote command timed out")
    finally:
        ws.close()
        session.delete(base + "/api/terminals/" + name, timeout=20)


if __name__ == "__main__":
    main()
