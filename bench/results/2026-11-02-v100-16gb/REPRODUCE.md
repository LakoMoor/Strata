# Reproduce this machine's setup

Run the commands below on the GPU server. The model files and engine must already
be installed. Installation used the signed Terminal release, followed by the
CUDA 12 engine selected for Volta. The fork does not redistribute model weights.

## Start and stop

The installed executable is `/workspace/strata-v100/bin/strata`.

```sh
/workspace/strata-v100/bin/strata launch --preset v100-coder-256k --no-tui
/workspace/strata-v100/bin/strata launch --status
/workspace/strata-v100/bin/strata launch --stop --preset v100-coder-256k
```

The equivalent explicit launch on this server reads the existing key without
printing it:

```sh
STRATA_API_KEY="$(cat /workspace/strata-v100/api-key)" \
/workspace/strata-v100/bin/strata launch \
  --family coder --model IQ1_M --context 262144 --kv int8 \
  --vision off --parallel 1 --gpu 0 \
  --data-dir /workspace/strata-v100/data \
  --set mtp-draft-vocab=/workspace/strata-v100/data/draft_vocab_cyrillic.bin \
  --set STRATA_SM70_TABLE=1 --access lan --api-key-env STRATA_API_KEY \
  --port 8000 --yes --no-tui \
  --save-preset v100-coder-256k
```

API addresses on the server:

- Chat Completions and Responses: `http://127.0.0.1:8000/v1`.
- Anthropic Messages: `http://127.0.0.1:8000`.

The service listens on `0.0.0.0:8000` with bearer authentication. Local clients
can continue using `127.0.0.1:8000`. The key is stored in
`/workspace/strata-v100/api-key` (mode 0600), and OpenCode reads that file with
`{file:/workspace/strata-v100/api-key}`. The key is not included in this fork.
Port 8080 was occupied by another program and
was not changed. On 3 November 2026 Strata moved from 18080 to 8000 at the
user’s request; the previous NInfer router was stopped to free that port.
The recorded benchmark requests retain their original endpoint.

## OpenCode v2

A `strata` provider was added to the server's OpenCode v2 configuration. Its model
selector is `strata/coder`, with `#fast` (thinking disabled) and `#think` variants.
A backup of the previous configuration is stored on the server.

From the project you want to work on:

```sh
opencode --standalone run --model 'strata/coder#fast' 'Your coding task'
```

The complete project configuration is [client/opencode.json](client/opencode.json).
It can be merged into a project's `opencode.json`: 262,144 total tokens, 196,608
input tokens and up to 65,536 output tokens. Input includes system instructions,
tools and conversation. Automatic compaction leaves another 16,384-token buffer.

The profile follows the [OpenCode v2 model format](https://opencode.ai/v2/docs/models/)
and [compaction settings](https://opencode.ai/v2/docs/compaction/). The shipped
`strata connect opencode` template targets an older OpenCode version; its HTTP
prompt/tool check passed, but its v1 configuration was not written over v2.

## Rerun the comparisons

Stop the production preset first to free its GPU memory. The commands below start
and stop only their own test servers. Output folders must be new.

```sh
python3 /workspace/strata-v100/v100_sweep.py \
  --config /workspace/strata-v100/baseline.json \
  --candidate-config /workspace/strata-v100/stable-candidate.json \
  --strata /workspace/strata-v100/bin/strata \
  --arms baseline,candidate --rounds 2 --port 18091 \
  --max-new 512 --long-words 12000 \
  --out /workspace/strata-v100/results/repeat-paired
```

Restore the production preset before the long-context checks:

```sh
/workspace/strata-v100/bin/strata launch --preset v100-coder-256k --no-tui
python3 /workspace/strata-v100/v100_validate.py \
  --url http://127.0.0.1:8000 \
  --api-key-file /workspace/strata-v100/api-key \
  --corpus-root /workspace/strata-v100/source \
  --out /workspace/strata-v100/results/repeat-validation.json
```

The validator requests the true rendered token count before each recall request.
A successful 65,536-token output budget does not mean a full 65,536-token answer
was generated; the recall answer is deliberately short.

## Avoid duplicate model preparation

Both GGUF shards match Strata's pinned SHA-256. The second shard was reconstructed
from an existing unchanged IQ4_NL NInfer table with
`tools/restore_ngram_gguf.py`, downloading only its 192-byte pinned GGUF header.
The helper publishes the result only after its whole-file hash matches upstream.
The original NInfer file is opened read-only.

MTP was downloaded as a ready runtime from the pinned revision in
[model-provenance.json](model-provenance.json), checked, and placed in
`data/mtp/rt`. No raw MTP tensors or intermediate MTP GGUF were needed. Main-model
preparation used `iq_pack.py` without `--experts-bin`: 1,475,120,640 bytes of dense
weights plus small metadata/tokenizer files. `tools/space_guard.py` bounded the
preparation and launch, preserving at least 6 GiB of disk headroom.

To repeat the multi-turn cache and queued-client checks against a loaded server:

```sh
python3 /workspace/strata-v100/v100_agent_check.py \
  --url http://127.0.0.1:8000 \
  --api-key-file /workspace/strata-v100/api-key \
  --source-root /workspace/strata-v100/source \
  --out /workspace/strata-v100/results/repeat-agent-checks.json
```

This uses the repository's existing quick-check suite over HTTP. It does not
launch coding agents or execute their tools.
