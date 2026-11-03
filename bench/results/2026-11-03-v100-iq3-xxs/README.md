# Tesla V100 16 GB: Flash-Next IQ3_XXS

Flash-Next IQ3_XXS replaces Coder IQ1_M on the V100. IQ3_XXS was chosen over IQ3_S to favor speed and RAM headroom on this V100 while switching from the pruned Coder to the original Flash-Next model. This is a selection rationale, not a measured coding-quality improvement.

Source: `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF`, revision `ed59f92082b1e93c0e96d60a8b11aab089b52f09`.

- First shard: 47,039,860,096 bytes, SHA-256 `219ea929900dfa9ef091f3aa473fdba6874b65fcb36526d7d851ac9e95856d15`.
- Table shard: 28,800,138,432 bytes, SHA-256 `316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113`; reused by a hard link to the previously verified file.
- Removed only the two authorized old Coder weight files: 32,685,469,696-byte NInfer artifact and 29,608,446,496-byte first GGUF shard. Other models were preserved.
- Engine remains the signed CUDA 12 release 0.1.55; Terminal 0.2.9; only GPU 0 (V100), no P4.
- Dashboard and OpenAI API continue on `0.0.0.0:8000`, without an API key at the owner's explicit request. The backend is private on `127.0.0.1:18080`.
- Configured and tested context 262,144, INT8 KV, 32,768 resident KV, MTP depth 4, minimum draft probability 0.5. PLE is mapped instead of explicitly locked into RAM, to leave room for the larger expert arena.

The first two short synthetic coding requests reported **55.2 and 69.3 decode tokens/s** (155 and 256 generated tokens). Other clients were using the server, so these are per-request engine timings, not an isolated throughput comparison. The generated binary search passed seven simple functional cases; this is not a coding-quality benchmark.

Long-context retrieval passed **6/6**: three 32K positions, 131,067 random-word tokens, **196,001 input tokens with a 65,536-token output budget**, and 131,046 tokens of public C++/documentation. A short request also accepted the 65,536-token output budget. Answers ended naturally; a full 65,536-token answer was **not** generated.

The `get_weather(city="Paris")` tool-call check passed. The six-turn agent-style session completed without failures and reused 69.6% of prompt tokens. Follow-up TTFT was 4.1–11.2 s while other clients were using the server; this is not an isolated latency comparison. The two-/four-client checks completed two rounds each with no errors. Median aggregate throughput for the tested client groups was 41.2 / 48.3 tokens/s, including prefill and queueing. The backend decodes one request at a time; these are queued clients, not four resident decode lanes.

Observed prefill rates in the long-context checks were about 1,240–1,600 tokens/s. Effective settings: 32 CPU workers, `STRATA_SM70_TABLE=1`, INT8 KV with 32K resident, an 8 GiB conversation cache and MTP cap 4. The engine reports a verification window of 6 because its default suffix lookup can extend a window by two tokens.

About **20.3 GiB disk space** remained after preparation. The API was independently checked from the owner's computer using the LAN address and no key. OpenCode's existing `strata/coder` alias now resolves to the Flash IQ3_XXS model ID, preserving the provider alias while changing the model.

## Reproduce the installed model

The first shard was downloaded with `hf download` from the fixed revision above. Its SHA-256 was checked before preparation. `tools/iq_pack.py --gguf <first-shard> --out /workspace/strata-v100/data/packs/iq3_xxs` created the native pack. No `experts.bin` copy was produced. The existing MTP runtime and Cyrillic draft vocabulary were reused.

[Run config](run-config.json) contains the effective backend configuration, with no API key. [Selected settings](selected-settings.json), [OpenCode profile](client/opencode.json), [context checks](context.json), [coding responses](coding.json), [code check](code-check.json), [tool call](tool-call.json), [ready state](ready.json), [agent/client checks](agent.json) and [final state](final-state.json) retain the evidence.

The gateway reads `/workspace/strata-v100/dashboard-state/engine.json`; the new model is at `/workspace/strata-v100/data/models/flash/IQ3_XXS`. The old table filename was removed only after confirming the new filename was a hard link to the same inode. The table remains intact. Metadata from the removed NInfer Coder folder was archived on the server.

[Dashboard and Compose instructions](../../../deploy/v100-dashboard/README.md). Docker Compose configuration was validated; a container build/run was not performed because no Docker daemon is available. The deployed service uses the existing native background supervisor.
