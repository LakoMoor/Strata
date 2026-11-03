# Strata Inference Studio · V100

Current model: **Qwen3.8-Flash-Next IQ3_XXS**, ISTA-DASLab original model. The earlier Coder IQ1_M weights were removed at the owner's request to make room. See [IQ3 deployment results](../../bench/results/2026-11-03-v100-iq3-xxs/README.md).

Opt-in dashboard for the measured V100 installation. The stock Strata UI, engine and launch defaults are unchanged.

- Dashboard: `http://192.168.10.64:8000/`
- OpenAI API: `http://192.168.10.64:8000/v1`
- Public listener: `0.0.0.0:8000`; private engine server: `127.0.0.1:18080`.
- **No API key**, explicitly requested by the owner. Every client that can reach port 8000 can generate text, save settings, and load, stop or restart the engine. Cross-origin browser mutations are rejected; this is not authentication.
- Native engine: CUDA 12 / sm70, GPU 0 (V100). GPU 1 (P4) is excluded.
- Selected context: 262,144 tokens; default output budget: 65,536. Input and output must fit the same context.

## Dashboard

The overview polls native `/metrics` every two seconds, draws actual generation samples, shows hardware usage and the latest requests. Empty charts contain no invented measurements. The playground sends streaming OpenAI requests and renders output as text, including separate reasoning.

Settings include context, resident KV, MTP depth and threshold, temperature, output budget and thinking defaults. Changes are checked as a whole, atomically saved with a backup and applied by **«Применить и перезапустить»**. Explicit request parameters override sampling and output defaults. GPU selection, paths and shell commands cannot be edited through the dashboard.

Start, stop, restart, load and unload operate on the backend owned by this gateway. Active requests, including those queued through the gateway, prevent restart/stop/unload. A control operation rejects new generation requests with HTTP 503; clients can retry afterwards. An unloaded model can load again automatically on a generation request, following Strata's native behavior. The dashboard remains available while the model loads or the backend is stopped.

SSE responses are forwarded incrementally without waiting for completion. Request bodies use Content-Length, up to 32 MiB; chunked upload bodies are not supported. There is no WebSocket proxy. Responses, Anthropic messages and other `/v1/*` HTTP inference routes pass through unchanged. Native configuration mutations are blocked at the gateway in favor of the validated dashboard controls.

## Existing server: native launch

Files are installed at `/workspace/strata-v100/dashboard`. State and logs live at `/workspace/strata-v100/dashboard-state`, outside the checkout. Models remain in place; no weights are copied or downloaded.

First installation, before starting the dashboard:

```sh
python3 /workspace/strata-v100/dashboard/prepare.py \
  --launch-config /path/to/existing-strata-run-config.json \
  --output /workspace/strata-v100/dashboard-state/engine.json
# Stop the previously running Strata backend before starting the gateway.
nohup sh /workspace/strata-v100/dashboard/run.sh \
  > /workspace/strata-v100/logs/dashboard.log 2>&1 < /dev/null &
```

`prepare.py --launch-config ...` takes an explicitly selected, trusted launch config, removes its API key and network trust/hooks, pins the installed CUDA 12 engine, and refuses to overwrite existing dashboard state. Do not run the old `strata launch` preset while the dashboard owns the GPU.

Stop the gateway (and its engine) before switching deployment methods:

```sh
kill -TERM "$(cat /workspace/strata-v100/dashboard-state/dashboard.pid)"
```

The native background process survives terminal closure; it is not a host boot service. Compose provides restart behavior on a Docker host.

## Docker Compose

The remote Jupyter environment has no Docker executable or daemon. Compose is prepared for a **Linux NVIDIA Docker host** with NVIDIA Container Toolkit; it was not started inside the Jupyter container. The Dockerfile uses the **already installed signed Terminal 0.1.55 and CUDA 12 engine**, mounting them read-only instead of rebuilding CUDA or fetching another model.

Required host paths (same contents as the existing installation):

```text
/workspace/strata-v100/runtime/terminal/0.1.55
/workspace/strata-v100/data
/workspace/strata-v100/dashboard-state/engine.json
/root/.local/share/strata/components/engine/0.1.55-linux-x86_64-cuda-cuda12
```

The host paths may be overridden with `STRATA_ROOT` and `STRATA_ENGINE_DIR`; paths inside the container remain fixed so the existing config, model and tokenizer references resolve. If moving to a different machine, transfer those directories first and run `prepare.py` against the transferred launch config (or adjust the private `engine.json` paths explicitly). This recipe deliberately does not provision missing weights.

Before Compose, stop the native gateway and ensure port 8000 and GPU 0 are free:

```sh
cd /workspace/strata-v100/dashboard
docker compose config --quiet
docker compose up -d --build
docker compose logs -f --tail=50
```

Only 8000 is published. Model data, Terminal and engine libraries are read-only bind mounts; state/logs are writable. `create_host_path: false` prevents silently creating empty model directories. Only GPU 0 is requested. The first model load can take minutes. The health check verifies the management service and flags backend errors; an intentionally stopped/unloaded backend remains a valid managed state.

Native operation and Compose are alternatives. Do not run both. Existing disk space is tight (about 7 GiB at setup); check available space on the Docker host before building the small Ubuntu/system-library image. No Docker image build was run in this task because neither environment has a running Docker daemon.

## API example, no key

```sh
curl http://192.168.10.64:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.8-flash-next-iq3_xxs","messages":[{"role":"user","content":"Reply OK"}],"max_tokens":16,"stream":true,"chat_template_kwargs":{"enable_thinking":false}}'
```

Some OpenAI SDKs require a nonempty client-side `api_key` argument; any placeholder works. The server does not validate it. OpenCode's Strata provider no longer needs the private key-file reference.

The LAN URL was tested from the owner's computer. `lakomoor.com:8000` still requires working public port forwarding; binding all interfaces does not create a router/NAT rule.

## Checks

```sh
python3 -m unittest discover -s deploy/v100-dashboard/tests -v
python3 -m py_compile deploy/v100-dashboard/server.py deploy/v100-dashboard/prepare.py
node --check deploy/v100-dashboard/web/app.js
docker compose -f deploy/v100-dashboard/compose.yaml config --quiet
```

The HTTP integration checks verify incremental SSE delivery, no-key forwarding, atomic rejection of invalid settings, prevention of stop/restart during active requests, and cross-origin control rejection. GPU functionality is checked separately on the actual server. The initial gateway checks and limits are in `verification.json`; current IQ3_XXS model checks are linked at the top of this page.
