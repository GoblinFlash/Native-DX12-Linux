# FWHT — two-pass native compute experiment

<sub>12 November 2026 · development evidence · not a released benchmark result</sub>

## Experiment Concept — FWHT and Cache Arena

The proposal was to use the known Fast Walsh–Hadamard Transform (FWHT)
as a deterministic, dependent compute workload for **Cache Arena**:
a reusable Rust-managed VRAM pool and a retained native GPU session.

The central question is whether one channel, code allocation and data pool
can safely support multiple complete FWHT tasks with different inputs,
instead of creating and closing a GPU session for every task. The two
dependent dispatches provide a check of intermediate-memory visibility,
synchronization, output correctness and resource lifetime—not merely a
timing sample. The RTX 4090 A/B pilot compares fresh (A) and retained (B)
sessions; a separate RTX 5070 pilot examines data/code placement.

The transform itself is established mathematics, not a novel algorithm.
**Cache Arena is software-managed session and resource reuse**, not a claim
of improved GPU hardware-cache behavior. Host elapsed time, raw GPU ticks
and independent GPU qualifications remain distinct evidence categories.

The tested block is **128 × 128 u32 values (16,384 elements)**. Dispatch 1
writes an intermediate result; dispatch 2 consumes that result and completes
the transform. The CPU does not substitute a ready-made result between the two
dispatches. The recorded checks include complete result buffers, unchanged
input/guard regions, resource retirement and saved driver/control evidence.

## RTX 5070 — memory placement pilot

**Device:** GeForce RTX 5070, SM120, NVIDIA Open 620.70.06.
Each configuration was run in **one process**, with 14 frames; the reported
median uses 12 frames. Values are **raw, uncalibrated GPU timer ticks**, not
nanoseconds or microseconds.

| Data backing | Program backing | Median raw ticks per frame | Recorded status |
| --- | --- | ---: | --- |
| SYSMEM | Control arena | 856,480 | GPU series accepted; saved output checked |
| VRAM | Control arena | 32,096 | GPU series accepted; saved output checked |
| VRAM | Separate 1 MiB VRAM code buffer | 32,064 | VM audit refused; saved-byte recheck passed |

Full output buffers matched the CPU transform models for all three saved
captures. The third GPU process completed and retained its data, but the
on-VM audit rejected it because its tool expected 14 QMD entries instead of
the 28 launches actually recorded. A corrected auditor accepted the saved
data on the CPU; **that corrected auditor has not been rerun on the GPU VM**.

The large SYSMEM/VRAM tick separation is specific to this workload and its
memory profiles. Code placement, transfers, cache behavior and launch details
are not independently isolated. With one process per configuration, unlocked
clocks and uncalibrated ticks, this is **not** a qualified end-to-end speedup
or a general GPU comparison.

## RTX 4090 — retained-session pilot

**Device:** GeForce RTX 4090, SM89, NVIDIA Open 620.70.06.
A private native Arena ran one canary followed by an A–B–B–A comparison:
**7 completed sessions, 20 dispatches, 10 FWHT tasks** across the saved
captures. In the A arm, each task opens/closes a separate session. In B, two
tasks share one session, channel and VRAM data/code allocations. Both arms
perform the same two dependent dispatches per task and full output checks.
Control structures remain in system memory.

| Host metric for two tasks | A: fresh sessions | B: retained session | B reduction |
| --- | ---: | ---: | ---: |
| Operational wall time (median) | 1.751565 s | 1.009055 s | 42.39% |
| Full audited wall time (median) | 34.908102 s | 28.485755 s | 18.40% |

These are **host-side timings, not shader or GPU execution times**.
There are only **two observations per arm**, run sequentially in A–B–B–A
order; they do not constitute a significance test. The saved phase records
show median full-code-upload spans of **1.107244 s (A)** and **0.545722 s
(B)** across two tasks, a measured difference of **0.561522 s**. Setup,
teardown and audit phases also differ. Because the A/B treatment changes
whole-session retention, these phase timings do **not** independently
establish the cause of the total reduction. The code image upload transfers
a full 1 MiB allocation although the program contains 6,880 bytes.
A smaller-code-upload variant was **NOT_RUN**.

The saved-data checks accepted both FWHT tasks and the recorded control,
allocation and lifetime evidence. A second reviewer recalculated the timings
and checked saved bytes; this does **not** independently establish live GPU
clock behavior, review the entire Rust consumer or qualify the production API.
Raw GPU ticks were not converted into time units. There was no Vulkan
comparison in this Arena pilot.

## Tested pilot identities and evidence

The identifiers below describe the **recorded development pilots**, not the
later `v21-r20b` integration candidate.

- **RTX 5070 (SM120):** Linux kernel `7.0.0-43-generic`, NVIDIA Open
  `620.70.06`; recorded runtime-input bytes SHA-256
  `e3408950827341b7670673aa21228fed254d337c8446315b44a917fe461fa31b`;
  loaded runtime library SHA-256
  `a60ddcb47edffda54986de9aebe3b2a16c2630a186aac43798ea4fa653d21ff4`;
  retained evidence-manifest file SHA-256
  `4a4ebde4ec03ab07c9b7b355ddbbd52b2250d52fc643fc08eadbe736e445e69a`.
- **RTX 4090 (SM89):** Linux kernel `7.0.0-43-generic`, NVIDIA Open
  `620.70.06`; pinned native runtime receipt SHA-256
  `6946312ad7490c8e7d60e3fe4c93e25599fbca06dee7047704c15d54c87de043`;
  private pilot source-manifest file SHA-256
  `1be020526b306c9355118fb69b1cd5f8a266012ca72a2b5cb85f3e9eb363fa74`;
  retained A–B–B–A capture SHA-256
  `3b199b2777890622c896e526c6e1a53ab0bda85c2688e0d83955e8662b5138d6`.

The captured host records identify Linux kernels but do not establish a
separately verified distribution release. Original manifests and captures
remain private. Their fingerprints support artifact identity checks; they
are **not public evidence downloads** or proof that a later source revision
produced the same results.

## Full benchmark integration — in progress

FWHT is being integrated as **Test 4 in the full benchmark**, not as a
standalone release. The working candidate is called **v21-r20b**
(based on an r19d development tree). At the recorded checkpoint:

- Tooling tests: **381 PASS** on the CPU; FWHT-focused tests: **13 PASS**.
- The Vulkan reference produced matching full buffers on **Mesa lavapipe
  (CPU)**. This is not an NVIDIA Vulkan GPU measurement.
- The candidate's six-runtime build and twelve-suite validation chain had
  started; a final package and completed chain were **not yet verified**.
- Candidate execution on NVIDIA GPU: **NOT_RUN**.
- Final CodeRabbit review and release qualification: **NOT_RUN**.

The older r20 candidate was a local CPU-checked prototype. Its results do
not qualify the newer r20b full-test candidate, and neither is a public
benchmark release.

## Evidence boundaries and next steps

These are bounded development experiments: specific NVIDIA models,
driver 620.70.06, one FWHT shape and retained private artifacts. Their
saved outputs and timings do not prove game compatibility, general Direct3D 12
support, a cross-GPU ranking or an advantage over Vulkan.

Next steps are to finish and pin the full-benchmark candidate, run the
integrated Test 4 on identified GPUs with completion and full-output checks,
validate a matching GPU reference where applicable, complete independent code
review, and publish reproducible artifacts before drawing broader conclusions.
