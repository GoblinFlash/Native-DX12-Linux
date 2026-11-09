# Native DirectX 12 Experimental Benchmark For Linux — v0.1.0

The first public, experimental benchmark release. Native compute runs on Linux through the NVIDIA driver, with a separate Vulkan reference, correctness checks and charts. Native data buffers use **system memory (SYSMEM)**; the separate VRAM experiment is not included.

**[How to run](https://github.com/GoblinFlash/Native-DX12-Linux/blob/main/NDX12_GPU_Benchmark/HOW_TO_RUN.md)** — download the installer, benchmark archive and starter; install once, then use `ndx12-benchmark`.

## Hardware validation

| GPU | NVIDIA Open driver | This release |
| --- | --- | --- |
| RTX 4090 | 620.70.06 | Full run: 119 native and 70 Vulkan reference processes passed correctness checks |
| RTX 3090 | 620.70.06 | Installer, sudo authentication, integrity check and interactive startup passed. Partial run: 95 processes passed correctness checks (56 native, 39 Vulkan), 94 not run |

Both runs used physical GPUs assigned to Linux VMs. The RTX 3090 run was stopped at the maintainer's request: the compute suite completed, D4 was partially completed, and K/WaveForm were not run. It is not a full-run PASS. Driver 615.78.08 and other admitted GPU models have not been tested with these exact release bytes; older results are identified separately in the [benchmark overview](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.0/NDX12_GPU_Benchmark/README.md).

## Files

v0.1.0 is the public version of tested package revision v21 r9. The runnable archive keeps its internal name and was not repacked for publication. Download the first two assets below and the installer linked from How to run. The source archive is for developers and is not needed to run the benchmark.

| File | SHA-256 | Bytes |
| --- | --- | ---: |
| `ndx12-native-benchmark-v21-615.78.08-620.70.06.tar.gz` | `d7eeb41588d041c88d1c7c06eee508e109c61da1afffecdef16de1d45d0c0eb2` | 2517024 |
| `ndx12_start.py` | `8cd0ca349f4535741ae8a673b3aa10de4a0b5f953c283543a453a850337aced5` | 10958 |
| `ndx12-benchmark-v0.1.0-source.tar.gz` | `e315d10c89612667a493e8e94432efa182625fe0a88c297f9c492b5ed6c1530a` | 5661837 |
| `ndx12-install.py` — repository file at tag `v0.1.0` | `7bec0ee218c29fa390c6f1be3e7ba0eaefd18f9bb0050ee8acfd61531df66421` | 18475 |

The installer is deliberately a repository file rather than a release asset. It pins the archive, starter and package manifest; no checksum copying is needed. The checksum files attached to this release are convenience checks, not an independent trust anchor. Repository compromise is outside this unsigned distribution's protection.

## Sources and licensing

The source companion includes both architecture source snapshots, shader sources, exact custom adapter sources, pinned CPU build recipes and retained third-party notices. All 20 D4/K/WaveForm variants were rebuilt from HLSL; all 60 code/QMD/shader-info outputs matched the runtime archive. This was CPU compilation, not another GPU test.

Project-owned material is GPL-3.0-or-later. Third-party terms remain intact. See [Source and licenses](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.0/NDX12_GPU_Benchmark/SOURCE_AND_LICENSES.md) and the source companion README for build scope and known source-build limitations. GitHub's automatically generated repository source archives are separate from this benchmark source companion.

Experimental compute workloads only: this release does not establish full Direct3D 12 support, game compatibility, or general performance superiority. Share results through [GitHub issues](https://github.com/GoblinFlash/Native-DX12-Linux/issues); inspect the share bundle and keep raw machine evidence private.
