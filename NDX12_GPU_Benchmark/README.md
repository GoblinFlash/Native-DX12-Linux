# Native DirectX 12 Experimental Benchmark For Linux

This project explores running a subset of Direct3D 12 workloads natively on Linux. It connects shader compilation and GPU command submission to the existing NVIDIA driver, with no Vulkan or CUDA runtime in the native execution path.

This package brings that work into a runnable benchmark. It includes the native runtime, precompiled shaders, a desktop application, interactive graphics demos, correctness checks and result charts. A separate Vulkan reference runs corresponding workloads on the same GPU for comparison.

The goal is to make the work testable on more machines and collect reproducible results.

## Getting started

**[Download v0.1.9](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.9)** and follow [How to run](HOW_TO_RUN.md). One self-contained installer replaces the three-file installation used by v0.1.5 and earlier.

```bash
sudo bash NDX12-Benchmark-v0.1.9.run
```

Open **Native DX12 Benchmark** from the desktop or application menu.

## What it tests

| Test | Workload |
| --- | --- |
| Compute suite | Affine N129, Affine N515, ParallelSort N515 and the Native 4096-key ParallelSort variants (24 dispatches and 1 dispatch) |
| Test 1 — D4 | Histogram workload with Original, D4 and Q8PL variants where admitted |
| Test 2 — K | Full compute chain with scalar and uint4 variants |
| Test 3 — K WaveForm | A different histogram algorithm, with scalar and uint4 variants |
| Test 4 — FWHT | Fast Walsh–Hadamard Transform |
| Test 5 — Sponza / Cube Matrix | Scalar and Tensor Core 4-bit lighting decoders |
| Test 5 — Neural Grid | Reflected-light compute chain |
| Sponza (Raster) / Sponza (Raster) 4K | Native graphics-to-compute workloads at 1920 × 1080 and 3840 × 2160 |

The launcher runs admitted workloads and reports correctness checks, GPU timings and result charts. The available cases and process counts depend on the GPU, driver and selected workloads. Vulkan reference execution is separate and available only for supported workloads.

WaveForm changes the algorithm relative to K. Both native and Vulkan paths use the WaveForm workload in Test 3.

### Graphics demos

| Demo | Workload |
| --- | --- |
| Earth 4K | Interactive animated globe with camera controls |
| nBody 128 | 128-particle animation; separate Vulkan comparison option |
| nBody 10K | 10,240 particles at 1920 × 1080 |
| nBody 4K | 10,240 particles at 3840 × 2160 |

The application includes a benchmark launcher, integrated results, GPU Monitoring, GPU Control, Diagnostics, Bug Report, Live Output, Log Recording and Saved Reports. GPU management features and X11/Wayland presentation depend on the hardware, driver and desktop session.

## Hardware and requirements

The v0.1.9 package includes the following NVIDIA architecture profiles:

| GPU family (primary architecture) | Profile |
| --- | --- |
| GeForce RTX 20 | SM75 |
| GeForce RTX 30 | SM86 |
| GeForce RTX 40 | SM89 |
| GeForce RTX 50 | SM120 |

The package contains runtime profiles for NVIDIA Open drivers **615.78.08**, **620.70.06**, **620.70.10** and **620.73.04**. The launcher checks the actual GPU model, device identity, loaded driver and workload admission. These architecture families are not a guarantee that every model or every demo/driver combination is supported or tested.

Requirements: Linux x86-64, glibc 2.34 or newer, Bash, system Python 3.9 or newer with the maintained tar extraction filter, sudo, Polkit with `/usr/bin/pkexec`, NVIDIA UVM and the Qt host libraries (including OpenGL, X11/XCB and Kerberos GSSAPI). The installer bundles CPython 3.14, PySide6 Essentials and Shiboken. No separately installed CUDA toolkit or local shader compiler is needed to run the packaged workloads.

### Current release validation

The [v0.1.9 release notes](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.9#validation-and-current-limits) record a Full Benchmark with 173 verified samples and clean closure of all four tested demos on an RTX 4060 Ti with NVIDIA Open 620.73.04. Pre-submit allocation refusal cleanup was tested on that device; no Xid errors were reported. The RTX 4090 IOMMU configuration that motivated the fix was not verified on this release.

See [Benchmark Results](../Benchmark%20Results/README.md) for model- and release-specific measurements and submitted results. Historical runs do not qualify newer package bytes.

### Historical GPU tables and validation (v0.1.5 and earlier)

These are the model names admitted by the historical v0.1.5 package's GPU tables. This is not the current v0.1.9 compatibility list. All models below are **NVIDIA GeForce** GPUs. Admission also requires matching PCI device/subsystem identifiers and the reported model name.

**Tested on real hardware** means a recorded benchmark run exists for that model in the revisions identified below. It does not mean every board, laptop configuration, driver profile or later package revision has been tested. **Not yet tested on real hardware** means no hardware result was recorded in this historical validation summary.

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
| RTX 3060 (`10de:2503`) | Manual v21-r12 extraction; no install receipt[^manual-r12-3060] | 620.70.06 | Shared summary reports FULL / COMPLETE; 189/189 VERIFIED (119 native, 70 Vulkan). Host/GPU clock check QUALIFIED in all four suites |
| RTX 3090 (`10de:2204`) | Manual v21-r12 extraction; no install receipt[^manual-r12-3090] | 620.70.06 | Shared summary reports FULL / COMPLETE; 189/189 VERIFIED (119 native, 70 Vulkan). Host/GPU clock check NOT_QUALIFIED: HOST_TIMESTAMP_BRACKET in all four suites; no cross-API timing percentages |
| RTX 4060 (`10de:2882`) | v0.1.3 (v21 r13), archive SHA-256 beginning `6fbf42ac` | 615.78.08 | Stopped before any GPU work: a start-up check of the loaded native library failed on a btrfs subvolume (`NATIVE_LOADED_IMAGE`). Fixed in v0.1.4. The GPU was not tested |

The two manual v21-r12 entries are based on shared result summaries supplied by the owner. Their `run.json` records identify Ubuntu 26.04.1 LTS. Both summaries report 933 matching entries for `MANIFEST.sha256` with SHA-256 `ea1df965833b44eb74e62dd3e08e9abc105336f85c13417de6c8007a4246a28e`. No install receipt was present; these submissions do not establish verified-installer use or the identity of release v0.1.2. The counts and clock qualification are reported by the shared archives. Raw per-process receipts were not reviewed, and these GPU runs were not independently reproduced.

[^manual-r12-3060]: Submitted share archive SHA-256: `1eeb87bfcb6c098684999922d4c213e5eab157001c26c68d06aecd3f92f23f8a`.
[^manual-r12-3090]: Submitted share archive SHA-256: `34c36ba4217f6f8ee040e576399d0e8ba5923f772b0634d18c4177fc9e02bc17`.

The earlier maintainer-recorded runs above were recorded on physical GPUs assigned to Linux VMs. They establish hardware execution, not bare-metal testing. The v0.1.0 candidate (v21 r9, archive SHA-256 beginning `d7eeb415`) completed its full RTX 4090 run on 9 November 2026 using NVIDIA Open driver 620.70.06. The same release was installed and started on RTX 3090; its compute suite completed and D4 was interrupted at the maintainer’s request. K and WaveForm were not run in that session. Earlier package revisions also ran on RTX 4090 with driver 615.78.08 and on RTX 3090 with driver 620.70.06; those earlier results do not validate the changed bytes of v0.1.0.

## Reading and sharing results

The benchmark measures specific workloads, not game FPS or full Direct3D 12 compatibility. GPU timings exclude much of the CPU setup and result-validation work. Native-versus-Vulkan timing conclusions depend on the host/GPU clock qualification.

The current desktop benchmark uses VRAM for native and Vulkan reference data buffers. Native shader code and the Full Benchmark channel control block also use VRAM. Inspect the placement recorded for the individual run; historical releases and standalone reference tools can use different memory profiles.

The application includes GPU and system RAM telemetry. RAM usage describes the whole host.

After a run, select **Share Results** next to **Run log**, or use **Result files** to find the exported `share-results-*.tar.gz` archive. **[Submit benchmark results](https://github.com/GoblinFlash/Native-DX12-Linux/issues/new?template=benchmark_results.yml)**. Completed, partial and failed runs are welcome. Inspect the archive before attaching it. Keep full raw evidence private because it can contain machine identifiers.

## Release notes

- [v0.1.9](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.9) — VRAM channel control blocks and cleanup after supported pre-submit allocation refusals.
- [v0.1.8](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.8) — Earth Wayland swap-pool correction.
- [v0.1.7](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.7) — demos alongside other GPU clients.
- [v0.1.6](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.6) — single-file installer, desktop application, additional GPU profiles, workloads and demos.
- [v0.1.5](RELEASE-v0.1.5.md) — historical three-file release.

Previous release assets, tagged documentation and validation records remain available. See [Source and licenses](SOURCE_AND_LICENSES.md) for the applicable source and license scope. The `ndx12-install.py` file retained in this directory belongs to the old v0.1.5 installation method; it is not the current installer.
