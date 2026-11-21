# NVIDIA RTX 4090 — Measurement and execution details

This page records the bounded RTX 4090 GPU experiments and historical execution checks. The public source release does not yet provide a ready-to-run reproduction of the two performance charts. The original chart images and the recorded measurements are kept together under NVIDIA.

The shared NVIDIA RM/UVM compute test path is separate from the experimental D3D12 frontend. The affine case used DXIL/LLVMBC → NIR → NAK; FidelityFX ParallelSort used DXIL → SPIR-V → NIR → NAK. SPIR-V was a compiler intermediate, not a Vulkan runtime.

## Measured RTX 4090 compute experiments

These experiments were run on an RTX 4090. They do not measure full Direct3D 12
applications, game performance or speedups on other devices.

**D4 histogram experiment (2026-10-29):** each case contains 16,384 generated
input values in the range 0–255, stored as 32-bit integers. The GPU counts the
occurrences of each value. All three cases contain the same number of values;
their different width-by-height arrangements change the GPU work distribution.

| Input arrangement | Original (µs) | Changed (µs) | Paired median time reduction |
| --- | ---: | ---: | ---: |
| 128×128 | 3.392 | 2.624 | 22.64% |
| 32×512 | 7.936 | 4.848 | 39.01% |
| 16×1024 | 14.112 | 7.872 | 44.22% |

The change groups four repeated load/atomic operations and changes how guards
are represented. The intervals cover the complete histogram GPU dispatch, not
just the compiler or one instruction. Four paired process comparisons were made
per arrangement. All 2,880 complete output-buffer checks passed. The displayed
percentages are paired-process median reductions and are not always the ratios
of the two displayed medians. Independent saved-evidence verification agreed
with the report; production integration is a separate decision.

**Four-program chain (2026-10-29):** each input contains synthetic 32-bit values
arranged as 64×64 (4,096 values) or 127×65 (8,255 values). The GPU executes
`reduce → shared histogram → global histogram → combine`. The changed final
program reads four adjacent histogram values in one operation rather than
loading each separately. The other three programs and the work ordering are
unchanged.

| Input arrangement | Original native path (µs) | Changed native path (µs) | Whole-chain time reduction |
| --- | ---: | ---: | ---: |
| 64×64 | 4.608 | 4.336 | 5.90% |
| 127×65 | 5.632 | 5.344 | 5.11% |

These times cover the complete four-program GPU interval, including the
necessary synchronization between programs, not application startup or CPU
frontend overhead. Three process medians were recorded for each path and input
arrangement, and all 2,620 complete 64-KiB buffer comparisons matched expected
results. Vulkan and CUDA were independently measured reference implementations;
differences in synchronization and caching prevent a general backend ranking.
The author report did not claim an independent review of this new campaign.

## Recorded RTX 4090 cases

The recorded host used GeForce RTX 4090, PCI 10de:2684, Ada SM89, NVIDIA UNIX
Open Kernel Module 615.78.08, Ubuntu 26.04.1, kernel 7.0.0-42-generic, x86-64.

| Case | Recorded execution | Checked result |
| --- | --- | --- |
| Affine u32 | N=129; one dispatch; grid 2x1x1, local size 128x1x1 | Independent u32 arithmetic, complete input/output/guard buffers and padding |
| FidelityFX ParallelSort | N=515, max_groups=1; prefix40, 40 dispatches | Independent final sorting/permutation check and complete final images; no per-dispatch image qualification |

Both recorded attempts reached CLOSED with zero remaining owners, completion
signal 101 and GET=PUT=1. One FIFO entry contains the 40-dispatch sort workload;
GET/PUT is not the dispatch count. The control-image check compared 1,048,072
bytes, excluding exactly 504 bytes of RM USERD. There were no new kernel records
inside either execution window. Sixteen AppArmor "who" records outside those
windows were reported separately.

Evidence identity for these recorded cases:

- Source lock: 2174d8755fe39a40c80cca58ab01044c4ae7efdff8a1e60e455b06cd4da201ad.
- Affine shader binary: ffbc8fd32b70a4485c34a2fa9d5ee85c01af3539a645b1cffa3525a1b3c448ae.
- Affine output image: e2dd76c76f477af81812707b2ac0c661a23189677f2ef6170e17205f76ddf38a.
- Recorded summary SHA-256: 537f45f75bc7e0a433496d87174c084fc34f10a30cb9f69bae49649f95ba50e4.

These identities name the recorded version, not a later documentation revision.
The raw development evidence is retained privately and is not part of the source
distribution. This summary describes recorded observations; it is not a
publicly replayable GPU evidence bundle. No publicly reproducible benchmark,
long-term stability, other GPU/driver, arbitrary shader or general D3D12 Dispatch
is qualified for the current source release.
The runtime's formal native_execution_proven flags remain false; the experimental
observations above are reported separately.

[Results overview](README.md) · [Source build and CPU validation](../../docs/validation.md) · [Project home](../../README.md)
