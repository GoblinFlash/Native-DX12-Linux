# Issue #2 — RTX 4060 Laptop GPU, benchmark v0.1.4

**Existing v0.1.4 results — Native DX12 memory backing: SYSMEM (system-memory buffers, not VRAM).** This is the documented backing of the release artifact, not independent observation of the submitted host. Vulkan memory backing: **NOT_RECORDED**; do not infer it from Native DX12. [Release evidence](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.4/NDX12_GPU_Benchmark/README.md#L111). The experimental VRAM candidate is separate.

**Source:** [Community Issue #2](https://github.com/GoblinFlash/Native-DX12-Linux/issues/2) (reporter: `chinese-wzq`), with its attached `share-results-v0.1.4.tar.gz`.

**Review scope:** Original submitted archive downloaded and inspected without executing code. Its `run.json`, `summary.txt` and exported CSV files agree on the GPU identity, completeness and result statuses. The raw per-process GPU receipts are **not** part of the share archive. This is **archive-consistency review**, not independent GPU execution or broad hardware qualification.

| Field | Submitted / checked export |
| --- | --- |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU, PCI `10de:28e0` |
| NVIDIA driver | 620.70.06 Open |
| OS | Arch Linux; kernel `7.3.3-1-cachyos-bore` |
| Benchmark package | v0.1.4 / v21-r14; release archive SHA-256 `a4d707dd50fa9fa22d554732d4e97dfbb54c5ab4ce6fee225c7d554afd1f399a` |
| Submitted results archive SHA-256 | `5f32e1b4e96bfcca6051a8662e59b02e8ccd47088c120b1f6f82f5f2a8a518b0` |
| Process statuses in exported CSV | 189/189 VERIFIED: 119 native, 70 Vulkan reference; 0 FAIL, HELD, NOT_RUN, UNKNOWN |
| Reported timestamp qualification | QUALIFIED in all four suites under the runner's cross-process clock model |
| Clock policy | Unchanged; actual dispatch clocks were not independently measured |

Representative medians from the exported tables (native results are **GPU ticks**, Vulkan results are **nanoseconds**; not raw shader-only timing):

| Workload | Native SYSMEM median GPU ticks | Vulkan reference median ns |
| --- | ---: | ---: |
| Affine | 15,776 | 10,112 |
| ParallelSort N515 | 2,517,184 | 191,008 |
| D4, 128×128 | 17,904 | 7,904 |
| K root uint4, 64×64 | 114,064 | 89,872 |
| WaveForm uint4, 64×64 | 58,464 | 10,688 |

These measurements apply only to the reported machine and run. For this submission the runner reports no clear Affine difference in 7 paired repeats, even though the median changes; do not treat its median difference alone as a qualified speedup or slowdown. The report's clock model is conditional on a stable GPU timestamp relationship. Original device submissions and buffer readbacks were not independently inspected.

[Community GPU index](../../README.md)
