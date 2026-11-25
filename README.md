# Native DX12 Linux

**Native-DX12-Linux is an experimental Direct3D 12 runtime for Linux that executes directly on the GPU — completely bypassing Vulkan and VKD3D translation layers. Built around a direct shader pipeline (DXIL → NIR → NAK) and low-level NVIDIA RTX compute execution.**

**Help test and shape the next optimizations!**

**I strongly encourage anyone with a supported NVIDIA RTX 20/30/40/50 Series GPU on Linux to download the benchmark and [submit your results](https://github.com/GoblinFlash/Native-DX12-Linux/issues/new?template=benchmark_results.yml). Every single submission, including, full/partial runs or even failures provides critical real-world hardware data needed to guide next low-level compiler and runtime optimizations.**

**Andrew Kapica — GoblinFlash**

**AI-assisted development:** This project uses AI tools to assist with research, implementation, testing, code review, and documentation. AI-assisted contributions are subject to the same technical review, testing, and licensing requirements as other contributions. See the [contribution guidelines](AGENTS.md).

<p>
  <a href="https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.5"><img src=".github/readme-assets/button-download.svg" alt="Download benchmark v0.1.5" height="54"></a>
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

### Experimental GPU Measurements — Campaign 019 (RTX 4060 Ti)

The campaign used a **16,384-sample, 256-bin histogram** on an NVIDIA GeForce **RTX 4060 Ti**. Earlier dynamic-clock tests showed P8 power-state readings after Native runs, so the comparison was repeated with **locked clocks** (2310 MHz core / 9001 MHz memory). Recorded monitoring samples during the locked-clock campaign showed P0 / 2310 / 9001 MHz.

**All 67 campaign runs completed**, with bit-exact output validation reported by the campaign author. The following results are medians of four processes for each workload. **Both paths report elapsed GPU time in nanoseconds (ns) for these results. At 1,000,000 ns and above, reports display ms to at most two decimal places.**

| Workload Variant | 256×64 Native (ns) | 256×64 NVIDIA Vulkan (ns) | 16×1024 Native (ns) | 16×1024 NVIDIA Vulkan (ns) |
| :--- | ---: | ---: | ---: | ---: |
| **Empty Kernel (Baseline)** | **4,480** | 6,792 | **4,424** | 6,792 |
| **D4 (Reference)** | **5,032** | 8,160 | **10,864** | 15,680 |
| **Q8PL (Packed INT8 Opt.)** | **4,816** | 7,992 | **7,344** | 9,152 |

**Measurement limitations:** The Native and Vulkan timing windows differ, and Native buffers use VRAM while the Vulkan reference uses system memory. Therefore, the numbers above are **independent experimental observations**, not directly comparable execution times or evidence of a specific cross-API speedup. The empty-kernel measurements also include their respective measurement/submission brackets; they do not isolate API translation overhead. Independent review is pending.


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
- [Benchmark Results](Benchmark%20Results/README.md) — technical measurements, comparisons and recorded outcomes.
- [Build the source](container/README.md) — CPU-side build instructions; a successful build is not a GPU test.
- [Native pipeline overview](docs/native_dx12_linux_pipeline.svg) — experimental NVIDIA execution path.
- [NVIDIA Developer Forums discussion](https://forums.developer.nvidia.com/t/native-directx-12-on-linux/386938) — public progress and feedback.

The documented build environment is Ubuntu 26.04 x86-64. Hardware results belong to their recorded package revisions. **The v0.1.5 release has CPU-side validation; it is not a new GPU qualification of every listed card.**

## License and Credits

Created by **Andrew Kapica — GoblinFlash**. Project-owned material is licensed under **GPL-3.0-or-later**. Third-party components retain their original licenses; see [LICENSE](LICENSE) and [NOTICE](NOTICE).

### Community Contributors

- [Hyrules](https://github.com/Hyrules) — Benchmark testing, bug reports and valuable feedback.

<sub>Experimental project · Native compute subset only · Status updated 11 November 2026</sub>
