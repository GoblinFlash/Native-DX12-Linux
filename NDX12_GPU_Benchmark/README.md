# Native DirectX 12 Experimental Benchmark For Linux

This project explores running a subset of Direct3D 12 compute workloads natively on Linux. It connects shader compilation and GPU command submission to the existing NVIDIA driver, with no Vulkan or CUDA runtime in the native execution path.

This package brings that work into a runnable benchmark. It includes the native runtime, precompiled shaders, an interactive launcher, correctness checks and result charts. A separate Vulkan reference runs corresponding workloads on the same GPU for comparison.

The goal is to make the work testable on more machines and collect reproducible results.

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
| RTX 3060 | Not yet tested on real hardware |
| RTX 3060 Ti | Not yet tested on real hardware |
| RTX 3070 | Not yet tested on real hardware |
| RTX 3070 Ti | Not yet tested on real hardware |
| RTX 3080 | Not yet tested on real hardware |
| RTX 3080 Ti | Not yet tested on real hardware |
| RTX 3090 | Tested on real hardware |
| RTX 3090 Ti | Not yet tested on real hardware |
| RTX 4090 | Tested on real hardware |

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

RTX 3050 A Laptop GPU uses the SM89 runtime; the other listed laptop models use SM86. The RTX 4090 entry above is the desktop model. RTX 40 series Laptop GPUs are not included in this list.

#### Recorded hardware validation

| GPU | Package tested | NVIDIA Open driver | Recorded result |
| --- | --- | --- | --- |
| RTX 3090 | v19, archive SHA-256 beginning `e61a1372` | 620.70.06 | Full run completed: 119 native and 70 Vulkan reference processes passed correctness checks |
| RTX 4090 | Earlier D4/A benchmark package, archive SHA-256 beginning `99963342` | 620.70.06 | Full run completed: 119 native processes passed correctness checks; Vulkan was not run in this recorded run |

These results were recorded on physical GPUs assigned to Linux VMs. They establish hardware execution, not bare-metal testing. The v20 tool changes have CPU validation only in this summary. Hardware validation of the final corrected release remains to be recorded; neither row should be read as validation of that release or of driver 615.78.08.

Linux x86-64, a working systemd service manager, standard CPython 3.13 or newer with the GIL enabled, sudo and NVIDIA UVM are required. The optional Vulkan reference also needs the Vulkan loader, NVIDIA Vulkan driver and glibc 2.38 or newer. No local shader compiler or CUDA installation is needed.

## Getting started

See [How to run](HOW_TO_RUN.md) for installation, launch instructions and sharing results.

## Reading and sharing results

The benchmark measures specific compute workloads, not game FPS or full Direct3D 12 compatibility. GPU timings exclude much of the CPU setup and result-validation work. Native-versus-Vulkan timing conclusions depend on the documented cross-process clock model.

The current package uses system-memory data buffers. The experimental VRAM candidate is separate and is not included.

The v20 candidate adds system RAM telemetry and process snapshots to the existing GPU telemetry. RAM usage describes the whole host. Its updated tools have CPU validation; hardware results from earlier revisions must remain identified as such.

The launcher produces a combined charts page and a `share-results.tar.gz` bundle. Inspect that bundle before sharing it. Keep the full raw evidence folder private because it contains machine identifiers.

**Current status: experimental release candidate. Review and corrections are ongoing.**
