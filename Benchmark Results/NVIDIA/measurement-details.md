# NVIDIA RTX 4090 — measurement scope and limitations

This page records the conditions and verification scope for two historical compute optimizations and two GPU execution checks. It is not a recipe for an unpublished optimization, and the currently distributed source package does not directly reproduce these exact campaigns.

## GPU compute experiments

**Hardware:** GeForce RTX 4090 (Ada). Results below are historical measurements from bounded native NVIDIA execution, not full application or game timings.

| Workload | Inputs | Measurement interval | Recorded validation |
| --- | --- | --- | --- |
| D4 histogram, 29 October 2026 | 16,384 generated 32-bit values in three work distributions | Full histogram GPU dispatch | Four paired process comparisons per arrangement; 2,880 complete buffer comparisons passed |
| Four-program compute chain, 29 October 2026 | Synthetic 32-bit inputs of 4,096 or 8,255 values | Full dependent GPU sequence including synchronization | Three process medians per path and arrangement; 2,620 complete 64-KiB buffer comparisons matched expected results |

See the [result tables and original charts](README.md). The listed percentage changes are historical paired-process reductions and need not equal a ratio of the displayed medians. The experiments used different execution strategies, and the code changes are not independently proven to produce the same gains on other devices or workloads.

Vulkan and CUDA reference observations were measured separately. They are **not a controlled proof of a cross-API speedup**: synchronization, memory placement and measurement windows may differ. The first historical histogram result was checked against saved evidence independently; the author report for the later four-program campaign did not establish the same independent review.

## Recorded execution checks

The separate recorded GPU cases used a **GeForce RTX 4090, Ada SM89, NVIDIA Open Kernel Module 615.78.08, Ubuntu 26.04.1 (x86-64)**.

| Case | Execution scope | Verification |
| --- | --- | --- |
| Affine u32 | 129 values, one dispatch | Numerical output, buffer contents, guard regions and padding |
| FidelityFX ParallelSort | 515 values, 40 dispatches | Final sorted keys, permutation and full final output images |

Both recorded cases completed, including signal-based completion and resource-release checks, with no new kernel records during the measured windows. The observations do not qualify other GPUs, arbitrary shaders or the current public runtime as a general-purpose D3D12 implementation.

**Compiler and API distinction:** The affine case used a native DXIL/LLVMBC → NIR → NAK path. ParallelSort used a DXIL → SPIR-V → NIR → NAK compilation route. SPIR-V was an intermediate representation; it does not imply that the native execution used Vulkan. The shared experimental RM/UVM compute test path is separate from the full D3D12 graphics frontend.

## Evidence boundary

The retained, pinned source and capture identities apply to the recorded historical runs; private original captures are not public evidence downloads. No complete public one-command reproduction or independent hardware qualification of a newer source revision is asserted here. Release-specific source, licenses and build limitations are documented separately in [source and validation](../../docs/validation.md).

[Results overview](README.md) · [Project home](../../README.md)
