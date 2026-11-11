# Native DirectX 12 Experimental Benchmark For Linux

This project explores running a subset of Direct3D 12 compute workloads natively on Linux. It connects shader compilation and GPU command submission to the existing NVIDIA driver, with no Vulkan or CUDA runtime in the native execution path.

This package brings that work into a runnable benchmark. It includes the native runtime, precompiled shaders, an interactive launcher, correctness checks and result charts. A separate Vulkan reference runs corresponding workloads on the same GPU for comparison.

The goal is to make the work testable on more machines and collect reproducible results.

## Getting started

**[Download v0.1.5](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.5)** and follow [How to run](HOW_TO_RUN.md). After installation, start it with `ndx12-benchmark`.

The release also includes a [source companion](https://github.com/GoblinFlash/Native-DX12-Linux/releases/download/v0.1.5/ndx12-benchmark-v0.1.5-source.tar.gz). See [Source and licenses](SOURCE_AND_LICENSES.md) for contents and build scope.

The links above require the matching tag and release assets. If they are not available, use the [v0.1.4 release and its tagged instructions](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.4/NDX12_GPU_Benchmark/HOW_TO_RUN.md). Do not mix files from different releases.

## What it tests

| Test | Workload |
| --- | --- |
| Compute suite | Affine N129, Affine N515 and ParallelSort N515 |
| Test 1 — D4 | Histogram workload with Original and D4 variants |
| Test 2 — K | Full compute chain with scalar and uint4 variants |
| Test 3 — K WaveForm | A different histogram algorithm, with scalar and uint4 variants |

Each native process submits real GPU work, waits for completion and checks complete result buffers against a CPU reference. Results include GPU timing, correctness outcomes and charts. A full run contains 119 native processes, plus 70 reference processes when Vulkan is available.

WaveForm changes the algorithm relative to K. Both native and Vulkan paths use the WaveForm workload in Test 3.

## Hardware and requirements

One archive contains SM86 and SM89 runtimes for NVIDIA Open kernel drivers **615.78.08** and **620.70.06**. The launcher selects a runtime using the detected GPU and loaded driver.

### GPU models and hardware testing status

These are the model names admitted by the package's GPU tables. All models below are **NVIDIA GeForce** GPUs. Admission also requires matching PCI device/subsystem identifiers and the reported model name.

**Tested on real hardware** means a recorded benchmark run exists for that model in the revisions identified below. It does not mean every board, laptop configuration, driver profile or later package revision has been tested. **Not yet tested on real hardware** means the model is listed for testing, but no hardware result is recorded in this validation summary.

#### Desktop GPUs

| GPU | Status |
| --- | --- |
| RTX 3050 | Not yet tested on real hardware |
| RTX 3050 OEM | Not yet tested on real hardware |
| RTX 3060 | Tested on real hardware |
| RTX 3060 Ti | Not yet tested on real hardware |
| RTX 3070 | Not yet tested on real hardware |
| RTX 3070 Ti | Not yet tested on real hardware |
| RTX 3080 | Not yet tested on real hardware |
| RTX 3080 Ti | Not yet tested on real hardware |
| RTX 3090 | Tested on real hardware |
| RTX 3090 Ti | Not yet tested on real hardware |
| RTX 4060 | Not yet tested on real hardware |
| RTX 4060 Ti | Not yet tested on real hardware |
| RTX 4070 | Not yet tested on real hardware |
| RTX 4070 SUPER | Not yet tested on real hardware |
| RTX 4070 Ti | Not yet tested on real hardware |
| RTX 4070 Ti SUPER | Not yet tested on real hardware |
| RTX 4080 | Not yet tested on real hardware |
| RTX 4080 SUPER | Not yet tested on real hardware |
| RTX 4090 | Tested on real hardware |
| RTX 4090 D | Not yet tested on real hardware |

#### Laptop GPUs

| GPU | Status |
| --- | --- |
| RTX 3050 Laptop GPU | Not yet tested on real hardware |
| RTX 3050 4GB Laptop GPU | Not yet tested on real hardware |
| RTX 3050 6GB Laptop GPU | Not yet tested on real hardware |
| RTX 3050 Ti Laptop GPU | Not yet tested on real hardware |
| RTX 3060 Laptop GPU | Not yet tested on real hardware |
| RTX 3070 Laptop GPU | Not yet tested on real hardware |
| RTX 3070 Ti Laptop GPU | Not yet tested on real hardware |
| RTX 3080 Laptop GPU | Not yet tested on real hardware |
| RTX 3080 Ti Laptop GPU | Not yet tested on real hardware |
| RTX 3050 A Laptop GPU | Not yet tested on real hardware |
| RTX 4050 Laptop GPU | Not yet tested on real hardware |
| RTX 4060 Laptop GPU | Not yet tested on real hardware |
| RTX 4070 Laptop GPU | Not yet tested on real hardware |
| RTX 4080 Laptop GPU | Not yet tested on real hardware |
| RTX 4090 Laptop GPU | Not yet tested on real hardware |

All RTX 40 series GPUs, desktop and Laptop GPU, and the RTX 3050 A Laptop GPU use the SM89 runtime; the other RTX 30 series models use SM86. The RTX 4060 family was added in v0.1.3 and the rest of the RTX 40 series in v0.1.4.

#### Recorded hardware validation

| GPU | Package tested | NVIDIA Open driver | Recorded result |
| --- | --- | --- | --- |
| RTX 4090 | v0.1.0 (v21 r9), archive SHA-256 beginning `d7eeb415` | 620.70.06 | Full run completed: 119 native and 70 Vulkan reference processes passed correctness checks |
| RTX 3090 | v0.1.0 (v21 r9), archive SHA-256 beginning `d7eeb415` | 620.70.06 | Installation and startup passed. Partial run stopped by the maintainer: 95 processes passed correctness checks (56 native, 39 Vulkan); 94 were not run |
| RTX 4090 | v17, full run recorded on 7 November 2026 | 615.78.08 | Full run completed: 119 native and 70 Vulkan reference processes passed correctness checks |
| RTX 3090 | v19, archive SHA-256 beginning `e61a1372` | 620.70.06 | Full run completed: 119 native and 70 Vulkan reference processes passed correctness checks |
| RTX 4090 | Earlier D4/A benchmark package, archive SHA-256 beginning `99963342` | 620.70.06 | Full run completed: 119 native processes passed correctness checks; Vulkan was not run in this recorded run |
| RTX 3060 (`10de:2503`) | Manual v21-r12 extraction; no install receipt[^manual-r12-3060] | 620.70.06 | Shared summary reports FULL / COMPLETE; 189/189 VERIFIED (119 native, 70 Vulkan). Tick-to-ns QUALIFIED in all four suites |
| RTX 3090 (`10de:2204`) | Manual v21-r12 extraction; no install receipt[^manual-r12-3090] | 620.70.06 | Shared summary reports FULL / COMPLETE; 189/189 VERIFIED (119 native, 70 Vulkan). Tick-to-ns NOT_QUALIFIED: HOST_TIMESTAMP_BRACKET in all four suites; no cross-API timing percentages |
| RTX 4060 (`10de:2882`) | v0.1.3 (v21 r13), archive SHA-256 beginning `6fbf42ac` | 615.78.08 | Stopped before any GPU work: a start-up check of the loaded native library failed on a btrfs subvolume (`NATIVE_LOADED_IMAGE`). Fixed in v0.1.4. The GPU was not tested |

The two manual v21-r12 entries are based on shared result summaries supplied by the owner. Their `run.json` records identify Ubuntu 26.04.1 LTS. Both summaries report 933 matching entries for `MANIFEST.sha256` with SHA-256 `ea1df965833b44eb74e62dd3e08e9abc105336f85c13417de6c8007a4246a28e`. No install receipt was present; these submissions do not establish verified-installer use or the identity of release v0.1.2. The counts and clock qualification are reported by the shared archives. Raw per-process receipts were not reviewed, and these GPU runs were not independently reproduced.

[^manual-r12-3060]: Submitted share archive SHA-256: `1eeb87bfcb6c098684999922d4c213e5eab157001c26c68d06aecd3f92f23f8a`.
[^manual-r12-3090]: Submitted share archive SHA-256: `34c36ba4217f6f8ee040e576399d0e8ba5923f772b0634d18c4177fc9e02bc17`.

The earlier maintainer-recorded runs above were recorded on physical GPUs assigned to Linux VMs. They establish hardware execution, not bare-metal testing. The v0.1.0 candidate (v21 r9, archive SHA-256 beginning `d7eeb415`) completed its full RTX 4090 run on 9 November 2026 using NVIDIA Open driver 620.70.06. The same release was installed and started on RTX 3090; its compute suite completed and D4 was interrupted at the maintainer’s request. K and WaveForm were not run in that session. Earlier package revisions also ran on RTX 4090 with driver 615.78.08 and on RTX 3090 with driver 620.70.06; those earlier results do not validate the changed bytes of v0.1.0.

Linux x86-64, a working systemd service manager, standard CPython 3.13 or newer with the GIL enabled, sudo and NVIDIA UVM are required. The optional Vulkan reference also needs the Vulkan loader, NVIDIA Vulkan driver and glibc 2.38 or newer. No local shader compiler or CUDA installation is needed.

## Reading and sharing results

The benchmark measures specific compute workloads, not game FPS or full Direct3D 12 compatibility. GPU timings exclude much of the CPU setup and result-validation work. Native-versus-Vulkan timing conclusions depend on the documented cross-process clock model.

The current package uses system-memory data buffers. The experimental VRAM candidate is separate and is not included.

The package includes system RAM telemetry and process snapshots alongside GPU telemetry. RAM usage describes the whole host. Hardware results are tied to the package revisions in the validation table above.

The launcher produces a combined charts page and a `share-results-v0.1.5.tar.gz` bundle (`share-results-release-unknown.tar.gz` without a verified install receipt; older releases use `share-results.tar.gz`). From v0.1.2 a bundle with at least one chart also contains `charts.html`, the charts page made from those chart images. **[Submit benchmark results](https://github.com/GoblinFlash/Native-DX12-Linux/issues/new?template=benchmark_results.yml)** using the short form; completed, partial and failed runs are welcome. Inspect the bundle and remove private information before attaching it. GitHub issues and attachments are public and linked to your account. Keep the full raw evidence folder private because it contains machine identifiers.

**v0.1.5 validation: CPU checks only. No new GPU execution or real-host installation was performed for the r16 package. SM120 and RTX 50 support are not included.** The hardware results above belong to their named historical revisions and do not validate these package bytes. v0.1.5 improves preload checks, installer rollback diagnostics and kernel-event handling, and its source builder rejects ambiguous PATH entries and keeps offline probes inside its execution boundary; see [v0.1.5 release notes](RELEASE-v0.1.5.md) for the exact changes and validation limits.
