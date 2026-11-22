# Cube Matrix — compact GPU lighting representation

<sub>Research overview · experiments recorded 17–20 November 2026 · not a released benchmark feature</sub>

Cube Matrix investigates whether scene-lighting information can be represented more compactly and reconstructed through the experimental native D3D12 execution path on Linux. Its purpose is to measure the trade-off between storage size, reconstruction cost, lighting quality and final GPU execution time.

## What has been demonstrated

- Hardware was tested in **distinct stages**: early work on **GeForce RTX 2060 SUPER (SM75)**; most experiments on **RTX 4060 Ti (SM89)**; later reconstruction and lighting experiments on **RTX 4090 (SM89)**. The campaigns had different workloads and clock settings; they do not jointly qualify the same implementation across all three GPUs. Recorded runs used NVIDIA Open driver 620.70.06 on Linux, without Vulkan runtime translation.
- GPU reconstruction and selected lighting outputs were checked against independent CPU references, including negative controls, for the recorded test variants.
- The native compiler path was able to execute selected reconstruction workloads, including work using NVIDIA Tensor Cores.
- Reduced storage **did not consistently translate into shorter whole-frame execution**. Storage, decoder cost and lighting cost must be measured together.

### Recorded comparison chart

![Cube Matrix on RTX 4090: recorded strong versus constant load comparison](charts/cube-matrix-constant-loads.svg)

*RTX 4090 only. The original chart compares selected compiler load variants on the recorded GPU workloads; it is not a universal frame-performance comparison or evidence for other RTX models.* [Published summary CSV](data/cube-matrix-constant-loads.csv).

These statements describe the recorded experimental workloads, not an integrated general-purpose graphics engine. Neither a broader GPU-family qualification nor an equivalent Vulkan comparison is established by these tests.

## Status and limits

**Status: experimental GPU evidence for bounded workloads.** Tests on other scenes, more camera paths, dynamic scenes and subsequent runtime revisions require separate validation. Independent release review and final packaging qualification were not complete in the source report.

**Scene attribution:** Sponza model © 2010 Frank Meinl, Crytek, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/), accessed through the Unity Classic Sponza repository. Experimental lighting data and render outputs are adaptations, not the original scene assets. The original report also evaluated measurements with an HDR sky subject to no-derivatives restrictions; adapted images and grids from that HDR source are not distributed here.

[Experiments overview](README.md) · [Benchmark Results](../Benchmark%20Results/README.md)

**Andrew Kapica — GoblinFlash.** AI-assisted development; experiment-specific results do not imply full D3D12 support.
