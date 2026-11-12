# Experiment Results

Recorded GPU experiments, CPU-side development checks and community benchmark submissions. Each result is tied to its hardware, benchmark revision and measurement method.

<details>
<summary>Individual intake records (all benchmark versions)</summary>

<!-- ndx12-community-intake:start -->
- [Pending classification / v0.1.5 / Issue #11](Community/Pending_Classification/v0.1.5/issue-11/README.md)
- [NVIDIA RTX 3060 / v0.1.5 / Issue #10](Community/NVIDIA/RTX_3060/v0.1.5/issue-10/README.md)
- [NVIDIA RTX 4060 / v0.1.5 / Issue #15](Community/NVIDIA/RTX_4060/v0.1.5/issue-15/README.md)
- [NVIDIA RTX 4090 / v0.1.5 / Issue #14](Community/NVIDIA/RTX_4090/v0.1.5/issue-14/README.md)
<!-- ndx12-community-intake:end -->

</details>

## Community Benchmark Data — v0.1.5

<!-- ndx12:overview:v0.1.5:start -->
4 submissions checked for **v0.1.5 / v21-r16**. 3 matching exports have measurements; refused submissions contribute no numeric results.

| GPU | Exported process status | GPU tick-to-ns model | Important limitation |
| --- | --- | --- | --- |
| [RTX 3060](Community/v0.1.5-submitted-data.md#rtx-3060--issue-10) | 189/189 VERIFIED | QUALIFIED, 4/4 suites | Reported COMPLETE; original GPU receipts unavailable |
| [RTX 3090 (claimed)](https://github.com/GoblinFlash/Native-DX12-Linux/issues/11) | No imported values | NOT_RECORDED | GPU_MISMATCH: archive reports RTX 3060 |
| [RTX 4060](Community/v0.1.5-submitted-data.md#rtx-4060--issue-15) | 189/189 VERIFIED | QUALIFIED, 4/4 suites | Reported COMPLETE; original GPU receipts unavailable |
| [RTX 4090](Community/v0.1.5-submitted-data.md#rtx-4090--issue-14) | 189/189 VERIFIED | QUALIFIED, 4/4 suites | Reported COMPLETE; original GPU receipts unavailable |

**[View charts and extracted benchmark measurements](Community/v0.1.5-submitted-data.md)** — 3 submission-specific charts and complete available median tables, with sources and caveats.

These are **reported export statuses**, not independently repeated GPU qualifications. Original GPU receipts are unavailable. No overall ranking or owner acceptance is implied.

**Native DX12 memory backing: SYSMEM (system-memory buffers, not VRAM)**. Vulkan memory backing: **NOT_RECORDED**.
<!-- ndx12:overview:v0.1.5:end -->


## Community Benchmark Data — v0.1.4

Four NVIDIA GPU submissions were received for benchmark **v0.1.4 / v21-r14**. Their exported CSV and JSON files have been inspected and the workload medians recalculated.

| GPU | Exported process status | GPU tick-to-ns model | Important limitation |
| --- | --- | --- | --- |
| [RTX 3060](Community/v0.1.4-submitted-data.md#rtx-3060--issue-4) | 189/189 VERIFIED | QUALIFIED, 4/4 suites |
| [RTX 3060 Ti](Community/v0.1.4-submitted-data.md#rtx-3060-ti--issue-3) | 189/189 VERIFIED | QUALIFIED, 4/4 suites | Background ONNX GPU activity |
| [RTX 3090](Community/v0.1.4-submitted-data.md#rtx-3090--issue-5) | 189/189 VERIFIED | **NOT_QUALIFIED**, 4/4 suites | Native-versus-Vulkan percentage comparisons invalid |
| [RTX 4060 Laptop](Community/v0.1.4-submitted-data.md#rtx-4060-laptop-gpu--issue-2) | 189/189 VERIFIED | QUALIFIED, 4/4 suites | Laptop-specific submission |

**[View charts and extracted benchmark measurements](Community/v0.1.4-submitted-data.md)** — four GPU-specific charts and complete median tables for all four suites, with source archives and caveats.

These are **reported export statuses**, not four independently repeated GPU qualifications. The public share archives do not include original per-process GPU receipts. No overall performance ranking is implied.

## Results by development area

1. **[NVIDIA experiments](NVIDIA/README.md)** — RTX 4090 recorded GPU execution, optimization experiments and correctness checks.
2. **[Community benchmark submissions](Community/README.md)** — per-GPU folders, review status, issue links and submitted measurements.
3. **[AMD](AMD/README.md)** — RadeonSI adapter checks performed on the CPU; no qualified AMD GPU benchmarks here.
4. **[Intel](Intel/README.md)** — early Iris Xe development and test programs; no qualified Intel GPU benchmark results here.

Results from different GPU models, drivers, clock domains or workloads must not be combined into a universal performance comparison.

[Back to the project overview](../README.md)
