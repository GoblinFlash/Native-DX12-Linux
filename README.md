# Native DX12 Linux

**Native-DX12-Linux is an experimental Direct3D 12 runtime for Linux that executes directly on the GPU — completely bypassing Vulkan and VKD3D translation layers. Built around a direct shader pipeline (DXIL → NIR → NAK) and low-level NVIDIA RTX compute execution.**

**Help test and shape the next optimizations!**

**Release notice (25 November 2026):** Benchmark v0.1.6 downloads are temporarily paused while compatibility issues are addressed. Existing results, including partial runs and failures, remain welcome through the [benchmark results form](https://github.com/GoblinFlash/Native-DX12-Linux/issues/new?template=benchmark_results.yml).

**Andrew Kapica — GoblinFlash**

**AI-assisted development:** This project uses AI tools to assist with research, implementation, testing, code review, and documentation. AI-assisted contributions are subject to the same technical review, testing, and licensing requirements as other contributions. See the [contribution guidelines](AGENTS.md).

<p>
  <a href="NDX12_GPU_Benchmark/HOW_TO_RUN.md"><img src=".github/readme-assets/button-run.svg" alt="How to run" height="54"></a>
  <a href="Benchmark%20Results/README.md"><img src=".github/readme-assets/button-results.svg" alt="Results" height="54"></a>
  <a href="Experiments/README.md"><img src=".github/readme-assets/button-experiments.svg" alt="Experiments" height="54"></a>
</p>

## Frequently Asked Questions (FAQ)

### How does Native-DX12-Linux differ from VKD3D-Proton and DXVK?

Compatibility tools on Linux implement Direct3D APIs using Vulkan:

* **DXVK** translates Direct3D 8/9/10/11 → Vulkan.
* **VKD3D-Proton** translates Direct3D 12 → Vulkan.

Both are mature, game-oriented projects. A translation layer introduces an API boundary, but its actual performance cost depends on the workload, implementation, and driver. It cannot be assumed from the architecture alone.

**Native-DX12-Linux does not use Vulkan or VKD3D in its experimental NVIDIA compute path.** Shaders are compiled through **DXIL → NIR → NAK**, and compute work is submitted through native NVIDIA Linux driver interfaces. The project is an experimental, compute-focused subset of Direct3D 12, **not** a drop-in replacement for commercial games or a complete D3D12 implementation.

## Native DirectX 12 Benchmark for Linux — v0.1.6 (downloads paused)

A major update featuring an improved native GPU execution path, expanded benchmark workloads, interactive native graphics demos and a redesigned desktop application.

- **Benchmark:** Generic Global NIR optimizations, VRAM placement for Native DX12 and Vulkan reference buffers, and new ParallelSort 4096 variants.
- **Demos:** Earth 4K, nBody 128, nBody 10K and nBody 4K.
- **GPU Monitoring:** Live GPU telemetry, utilization history, temperatures, clocks and memory usage.
- **GPU Control:** Selected `nvidia-smi` functionality and additional GPU management features, including power limits, fan control, clock locking and Persistence Mode.
- **Installation:** Temporarily unavailable while compatibility updates are tested. The single-file desktop installer will return with the next verified release.

**Downloads are paused.** Please use the [Releases](https://github.com/GoblinFlash/Native-DX12-Linux/releases) page to check which versions are currently available.

GPU management options depend on the hardware and driver. Included RTX profiles do not imply full hardware qualification.

### Benchmark

<img src=".github/readme-assets/v0.1.6/benchmark.png" alt="Native DX12 Benchmark v0.1.6 — workload selection and GPU clock profiles" width="950">

### GPU Monitoring

<img src=".github/readme-assets/v0.1.6/gpu-monitoring.png" alt="Native DX12 Benchmark — live GPU telemetry and utilization history" width="950">

### GPU Control

<img src=".github/readme-assets/v0.1.6/gpu-control.png" alt="Native DX12 Benchmark — NVIDIA GPU control, fan speed, power limits and GPU processes" width="950">

## Current Progress

<picture>
  <source media="(max-width: 650px)" srcset=".github/readme-assets/progress-mobile.svg">
  <img src=".github/readme-assets/progress-desktop.svg" alt="Native GPU execution demonstrated; benchmark v0.1.6 downloads paused; community submissions underway" width="950">
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
- [Benchmark Results](Benchmark%20Results/README.md) — technical measurements, comparisons and recorded outcomes.
- [Build the source](container/README.md) — CPU-side build instructions; a successful build is not a GPU test.
- [Native pipeline overview](docs/native_dx12_linux_pipeline.svg) — experimental NVIDIA execution path.
- [NVIDIA Developer Forums discussion](https://forums.developer.nvidia.com/t/native-directx-12-on-linux/386938) — public progress and feedback.

The documented build environment is Ubuntu 26.04 x86-64. Hardware results belong to their recorded package revisions. **Included GPU profiles do not imply qualification of every listed card.**

## License and Credits

Created by **Andrew Kapica — GoblinFlash**. Project-owned material is licensed under **GPL-3.0-or-later**. Third-party components retain their original licenses; see [LICENSE](LICENSE) and [NOTICE](NOTICE).

### Community Contributors

- [Hyrules](https://github.com/Hyrules) — Benchmark testing, bug reports and valuable feedback.

<sub>Experimental project · Native compute subset only · Status updated 25 November 2026</sub>
