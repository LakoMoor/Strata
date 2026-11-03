# Tesla V100 16 GB: Strata Coder, 262K context and 64K output budget

> The active model was later replaced with [Flash-Next IQ3_XXS](../2026-11-03-v100-iq3-xxs/README.md) at the owner's request.
> The Coder measurements below are historical; its old weights were removed to make room.

Serving endpoint updated on 3 November 2026 to `http://127.0.0.1:8000/v1`.
The dashboard and API now share `0.0.0.0:8000` **without authentication**, as explicitly
requested by the owner. The engine binds localhost:18080. See
[dashboard deployment](../../../deploy/v100-dashboard/README.md). Historical measurements retain their original
endpoint and authentication settings.

Measured on 2 November 2026. The selected profile runs **Coder IQ1_M on one V100**,
with **262,144 total tokens**, INT8 KV streaming, MTP depth 4, the default 32 CPU
workers and `STRATA_SM70_TABLE=1`. The OpenCode v2 profile reserves up to **65,536
output tokens** and sets an input limit of 196,608. Prompt and output share the
same window.

The final paired coding tests measured **76.3 and 102.9 tokens/s** of output for
the two workloads, versus 74.0 and 98.6 with the release defaults. Reading the
12,056-token prompt was essentially unchanged, about **1,660 tokens/s**. These
are greedy, thinking-disabled synthetic coding tests, not a coding-quality score.

Long-context recall passed **6/6**, including 196,001 actual input tokens and
131,046 tokens of public C++ source. A 65,536-token output budget was accepted
both with the 196K input and with a short request. The answers ended naturally;
a complete 65,536-token generation was **not** exercised.

[Start, stop and connect](REPRODUCE.md) · [Portable settings](selected-settings.json) ·
[OpenCode v2 configuration](client/opencode.json) · [Model provenance](model-provenance.json)

## Hardware and software

- Tesla V100-SXM2-16GB, sm_70. A Tesla P4, sm_61, with 7,680 MiB reported memory
  was also tested as a helper and excluded from the final profile.
- Xeon E5-2683 v4 virtual machine, 64 visible vCPUs, AVX2, no AVX-512.
- 76 GiB system RAM; 68 GiB available at initial inspection.
- NVIDIA driver 580.178.04; installed CUDA toolkit 12.9.
- Strata Terminal 0.2.9, build 0.1.55, signed CUDA 12 engine 0.1.55.
- Engine binary SHA-256 is recorded in [engine-provenance.json](engine-provenance.json).
- Fork/source snapshot: `c62d5e3a15b40ea51c96aae9e8d36928965f53ab`.
- OpenCode v2.2.2. Its model catalog accepted the v2 provider from an otherwise
  empty project: [catalog evidence](opencode-catalog-check.json).

GPU and CPU clocks were not locked. Other container processes were left running.
The previous NInfer model was unloaded before the experiments. No model weights
were changed by tuning, and no engine source was modified.

## Final paired comparison

Four fresh server starts, two rounds, order **baseline → candidate**, then
**candidate → baseline**. Both arms used the same 58-token coding prompt and
12,056-token context prompt, 512 generated tokens per request, temperature 0,
seed 42 and thinking disabled. The only configuration difference was
`STRATA_SM70_TABLE=1`.

| Measurement | Release defaults | Selected profile | Change |
| --- | ---: | ---: | ---: |
| Short coding decode, median tokens/s | 74.0 | 76.3 | +3.1% |
| Coding after 12K input, median tokens/s | 98.6 | 102.9 | +4.4% |
| 12K prompt, median tokens/s | 1,661.0 | 1,658.1 | -0.2% |

Short decode ranges were 73.0–75.0 and 75.4–77.2 tokens/s. Long-input decode
ranges were 98.2–98.9 and 102.8–102.9. Both long-input continuations matched the
baseline text exactly; the short continuations differed. The default adaptive
cache and automatic PCIe split remained enabled, so this is not an overall
bit-exactness proof. The earlier kernel screen matched 4/4 baseline outputs with
the Volta table.

[Raw final requests](final-stable/requests.jsonl) · [Summary](final-stable/summary.json) ·
[Parameters and version](final-stable/metadata.json)

## What was tried and rejected

There were 27 completed isolated model starts across the six experiment stages,
plus one interrupted initial run. Every completed start sent two speed requests.
The screening stages selected candidates; the larger paired test checked them.

### Kernel screen

Two rounds in reversed order, 384 output tokens, approximately 3.5K input for the
context workload. Each round used its own prompt tag, identical between arms.

| Arm | Short decode | Context decode | Context prompt |
| --- | ---: | ---: | ---: |
| Baseline | 67.4 | 87.7 | 1,213.8 |
| Volta table | 69.9 | 93.1 | 1,290.4 |
| Volta table + fused decode | 68.6 | 91.2 | 1,219.3 |
| Above + FP16 WMMA prompt experts | 70.4 | 88.1 | 1,259.5 |

All cells are median tokens/s. Fused decode added no consistent benefit. WMMA
changed 2/4 continuations and had a large spread, so it was not retained. The
apparent prompt gain in this short screen did not carry over to the final 12K
test. [Raw kernel evidence](kernels-v2/requests.jsonl).

### CPU worker screen

One run per value, Volta table enabled, MTP 4, fixed prompt text.

| Workers | Short decode | Context decode |
| --- | ---: | ---: |
| 8 | 52.3 | 93.0 |
| 16 | 66.6 | 98.6 |
| 24 | 73.6 | 97.7 |
| 32 | 71.5 | 97.5 |

The initial winner, 24 workers, failed the larger paired check: its 12K-context
decode ranged from 73.6 to 101.6 tokens/s, median 87.6, versus a baseline median
97.8. It was excluded; the final profile uses the default 32 workers.
[CPU evidence](cpu/requests.jsonl) · [Rejected candidate holdout](final-paired/requests.jsonl).

### MTP depth screen

One run per value, Volta table and 24 workers. Larger depth was not automatically
faster; depth 4 was retained and subsequently checked with the default pool.

| Draft depth | Short decode | Context decode |
| --- | ---: | ---: |
| 2 | 64.5 | 70.2 |
| 3 | 68.4 | 89.9 |
| 4 | 68.9 | 100.9 |
| 6 | 70.2 | 80.1 |

[Raw MTP evidence](mtp/requests.jsonl).

### P4 helper screen

One run per split, Volta table, 24 workers and MTP 4. The helper ran first; V100
was the main/last GPU. Explicit splits used trimmed stage weights.

| Placement | Short decode | Context decode | Context prompt |
| --- | ---: | ---: | ---: |
| V100 alone | 72.6 | 98.1 | 1,313.0 |
| P4 first 6 layers | 65.4 | 67.1 | 723.7 |
| P4 first 12 layers | 59.6 | 57.6 | 493.5 |

These two placements hurt both prompt and output speed. This does not establish
that every possible P4 placement is slower. [P4 evidence](p4/requests.jsonl).

## Long-context and output-budget checks

The server counted the rendered prompt before generation. The table uses actual
Chat Completions usage, not a character-based estimate. Greedy decoding, thinking
off, one unique fact hidden in the document; the fact was absent from the question.

| Corpus | Actual input tokens | Fact position | Recall | Prompt tokens/s |
| --- | ---: | ---: | --- | ---: |
| Random words | 32,773 | 10% | pass | 1,811.5 |
| Random words | 32,779 | 50% | pass | 1,723.5 |
| Random words | 32,761 | 90% | pass | 1,750.0 |
| Random words | 131,067 | 50% | pass | 1,541.9 |
| Random words | 196,001 | 50% | pass | 1,342.4 |
| Public C++ and documentation | 131,046 | 50% | pass | 1,452.0 |

The 196,001-token request also specified `max_tokens: 65536`; the sum fits the
262,144-token window. It returned the correct 12-token answer. A separate short
request with the same output budget returned `READY` and stopped naturally.
[Complete recall and budget evidence](validation.json).

This is a small retrieval check. It does not establish perfect recall of all
large projects, full-window reasoning quality, or sustained 65K-token code output.

## Agent and client checks

The installed OpenCode v2 catalog accepted `strata/coder` with `fast` and `think`
variants, context/input/output limits 262144/196608/65536, and a request-body
output cap of 65536. Only its provider was added to the global configuration; a
private local backup was kept. The optional project profile also sets compaction
buffer 16384 and preserves 24000 recent tokens.

The shipped `strata connect opencode --check` passed its prompt and tool-call
checks again on the final running profile ([evidence](connect-final.json)). It emits a v1 configuration, so its generated configuration was not used
for the installed v2 client.

A six-turn session grew to 12,909 prompt tokens. Follow-up first-token latency
was 2.085–2.525 s, median 2.316 s. The server reused 69.4% of follow-up prompt
tokens; only 2 old tokens were read again across the session. All turns completed.

| Simultaneous clients | Aggregate tokens/s, median | First token p95 | Errors |
| --- | ---: | ---: | ---: |
| 2 | 38.8 | 4.831 s | 0 |
| 4 | 41.8 | 10.243 s | 0 |

Each concurrency measurement used 128 output tokens per request and two rounds.
Aggregate throughput includes prompt time and queueing, so it is not directly
comparable with the engine-only coding decode rates. These were HTTP test clients,
not externally launched coding agents. [Full cache/queue evidence](agent-checks.json).


The production profile serves one request at a time; other clients queue. It is
not configured for multi-slot batch decoding.

## Installation and transfer evidence

Both GGUF shards match Strata's pinned SHA-256. The second was restored from an
unchanged local NInfer IQ4_NL table plus its 192-byte pinned GGUF header, in
143.3 seconds. Only the header had to be downloaded. MTP used a checked, pinned
824 MB runtime; its raw tensors and intermediate GGUF were unnecessary. Main
native-pack preparation added 1.475 GB of dense weights and small metadata,
without an extra expert copy. About 7.6 GiB of disk remained after preparation.

A standalone CUDA copy probe used 256 MiB of synthetic data and 16 copies per
measurement. Decimal GB/s; device-copy payload is counted once, not read + write.

| GPU | Pinned RAM → GPU | Device copy payload |
| --- | ---: | ---: |
| V100 | 12.334 | 409.174 |
| P4 | 6.097 | 71.541 |

Neither card reported peer access to the other. These copy rates are not LLM
throughput. [Transfer data](transfer-probe.jsonl) · [Acquisition hashes](model-provenance.json).

## Scope and failures

This is a local tuning experiment, not the standard Strata benchmark. It tests
one machine, one model and selected workloads. Screening cells have one run;
final cells have two. No HumanEval/SWE-bench score was measured.

The initial sweep stopped after its baseline because its port check mistook TCP
TIME_WAIT for an occupied listener. The check was fixed with `SO_REUSEADDR` and
the complete kernel comparison was rerun. The partial evidence remains in
[kernels/](kernels/). Regressions and rejected settings are retained above.

Validation performed: actual CUDA transfer probe compilation/execution on both
cards; Python syntax checks for the added helpers; live model requests, paired
speed tests, exact token-counted recall and output-budget checks. CUDA/HIP/SYCL
engine builds were not needed because engine code was unchanged.
