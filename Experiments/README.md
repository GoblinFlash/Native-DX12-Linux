# Experiments — Native DX12 Linux

Experimental research into native GPU compute and rendering on Linux, without a Vulkan/VKD3D translation runtime in the NVIDIA execution path.

These pages summarize **what was investigated, what was observed, and what remains unverified**. They are development reports, not claims of full Direct3D 12 support, game compatibility, a production renderer, or general superiority over another graphics API.

## <img src="charts/cube-matrix.svg" width="40" align="center" alt=""> Research areas

| Area | Research objective | Evidence boundary |
| --- | --- | --- |
| [Cube Matrix](Cube-Matrix.md) | Evaluate compact representations of scene lighting and native GPU reconstruction | Bounded NVIDIA RTX experiments; a smaller representation did not consistently reduce whole-frame time |
| [Neural Grid](Neural-Grid.md) | Explore learned representations and indirect-light workloads | Bounded RTX experiments, including Sponza; no general rendering-quality or performance claim |
| [FWHT / retained sessions](FWHT.md) | Exercise dependent compute workloads, resource reuse and correct synchronization | Separate RTX pilot observations; integrated full-benchmark GPU qualification was not established at the recorded checkpoint |
| [GPU memory placement](GPU-Instruction-Memory-Placement-RTX5070.md) | Examine a known GPU memory-management trade-off | RTX 5070 pilot: lower measured GPU interval, higher host elapsed time |
| [Campaign 019](Campaign-019-RTX4060Ti.md) | Check clock-controlled histogram measurements | RTX 4060 Ti measurements with documented limits on cross-API comparison |

## Results and reproducibility

Public, release-identified benchmark records, community submissions and their limitations are maintained separately in [Benchmark Results](../Benchmark%20Results/README.md). For the currently downloadable software, consult [Benchmark documentation](../NDX12_GPU_Benchmark/README.md) and its corresponding release notes and source package.

A completed GPU test applies only to the tested binary, device, driver, workload and measurement interval. CPU checks, compiler results, hardware runs and independent review are different evidence categories. A pilot run does not qualify a later package revision.

Experimental code and internal verification artifacts are not necessarily part of a public release. Source availability for **distributed GPL-covered binaries** is governed by the relevant licenses and source-distribution obligations; this page does not narrow those obligations.

**Project owner:** Andrew Kapica — GoblinFlash. Development uses AI-assisted tools under owner supervision.
