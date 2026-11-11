# Native DX12 Linux

**Experimental native Direct3D 12 on Linux — without Vulkan or VKD3D translation.**

Andrew Kapica — GoblinFlash

<p>
  <a href="https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.5"><img src=".github/readme-assets/button-download.svg" alt="Download benchmark v0.1.5" height="54"></a>
  <a href="NDX12_GPU_Benchmark/HOW_TO_RUN.md"><img src=".github/readme-assets/button-run.svg" alt="How to run" height="54"></a>
  <a href="Experiment%20Results/README.md"><img src=".github/readme-assets/button-results.svg" alt="Results" height="54"></a>
</p>

<picture>
  <source media="(max-width: 650px)" srcset=".github/readme-assets/about-mobile.svg">
  <img src=".github/readme-assets/about-desktop.svg" alt="About the project: native D3D12 exploration, NVIDIA compute execution demonstrated, full applications and games not supported" width="950">
</picture>

## Current Progress

<picture>
  <source media="(max-width: 650px)" srcset=".github/readme-assets/progress-mobile.svg">
  <img src=".github/readme-assets/progress-desktop.svg" alt="Native GPU execution demonstrated; benchmark v0.1.5 available; community submissions underway" width="950">
</picture>

## Current Work

**DEVELOPMENT ACTIVE**

<picture>
  <source media="(max-width: 650px)" srcset=".github/readme-assets/nvidia-mobile.svg">
  <img src=".github/readme-assets/nvidia-desktop.svg" alt="NVIDIA RTX active: native GPU optimization, command submission, shader scheduling and performance experiments" width="950">
</picture>

<picture>
  <source media="(max-width: 650px)" srcset=".github/readme-assets/goal-mobile.svg">
  <img src=".github/readme-assets/goal-desktop.svg" alt="Goal: reduce unnecessary work, improve GPU execution efficiency and performance while preserving correct results" width="950">
</picture>

<picture>
  <source media="(max-width: 650px)" srcset=".github/readme-assets/benchmark-mobile.svg">
  <img src=".github/readme-assets/benchmark-desktop.svg" alt="Benchmark and community testing: collecting submissions and expanding hardware coverage" width="950">
</picture>

<picture>
  <source media="(max-width: 650px)" srcset=".github/readme-assets/frontend-mobile.svg">
  <img src=".github/readme-assets/frontend-desktop.svg" alt="D3D12 frontend: expanding the experimental native implementation and GPU integration" width="950">
</picture>

## Hardware Roadmap

<picture>
  <source media="(max-width: 650px)" srcset=".github/readme-assets/roadmap-mobile.svg">
  <img src=".github/readme-assets/roadmap-desktop.svg" alt="Roadmap: NVIDIA RTX active development; AMD Radeon CPU-side development; Intel Iris Xe early testbed. No completion percentages." width="950">
</picture>

This roadmap shows **development focus**, not a percentage of Direct3D 12 completion. No delivery dates or full application compatibility are implied.

## Explore the Project

- [Benchmark details and supported hardware](NDX12_GPU_Benchmark/README.md) — workloads, requirements and hardware-specific validation records.
- [Submit benchmark results](https://github.com/GoblinFlash/Native-DX12-Linux/issues/new?template=benchmark_results.yml) — community submissions, including partial or failed runs.
- [Experiment Results](Experiment%20Results/README.md) — technical measurements, comparisons and recorded outcomes.
- [Build the source](container/README.md) — CPU-side build instructions; a successful build is not a GPU test.
- [Native pipeline overview](docs/native_dx12_linux_pipeline.svg) — experimental NVIDIA execution path.
- [NVIDIA Developer Forums discussion](https://forums.developer.nvidia.com/t/native-directx-12-on-linux/386938) — public progress and feedback.

The documented build environment is Ubuntu 26.04 x86-64. Hardware results belong to their recorded package revisions. **The v0.1.5 release has CPU-side validation; it is not a new GPU qualification of every listed card.**

## License and Credits

Created by **Andrew Kapica — GoblinFlash**. Project-owned material is licensed under **GPL-3.0-or-later**. Third-party components retain their original licenses; see [LICENSE](LICENSE) and [NOTICE](NOTICE).

### Community Contributors

- [Hyrules](https://github.com/Hyrules) — Benchmark testing, bug reports and valuable feedback.

<sub>Experimental project · Native compute subset only · Status updated 11 November 2026</sub>
