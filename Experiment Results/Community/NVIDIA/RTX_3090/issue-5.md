# Issue #5 — RTX 3090, benchmark v0.1.4

**Existing v0.1.4 results — Native DX12 memory backing: SYSMEM (system-memory buffers, not VRAM).** This is the documented backing of the release artifact, not independent observation of the submitted host. Vulkan memory backing: **NOT_RECORDED**; do not infer it from Native DX12. [Release evidence](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.4/NDX12_GPU_Benchmark/README.md#L111). The experimental VRAM candidate is separate.

**Source:** [Community Issue #5](https://github.com/GoblinFlash/Native-DX12-Linux/issues/5) (reporter: `Hyrules`), with attached `share-results-v0.1.4.tar.gz`.

**Review scope:** The submitted `run.json`, `summary.txt`, and exported CSVs agree on device, workload completeness and statuses. The original per-process GPU receipts are not included. This is **archive-consistency review**, not an independent GPU rerun or a performance qualification.

| Field | Submitted / checked export |
| --- | --- |
| GPU | NVIDIA GeForce RTX 3090, PCI `10de:2204` |
| NVIDIA driver | 620.70.06 Open |
| OS | Ubuntu 26.04.1 LTS; kernel `7.0.0-38-generic` |
| Benchmark package | v0.1.4 / v21-r14; release archive SHA-256 `a4d707dd50fa9fa22d554732d4e97dfbb54c5ab4ce6fee225c7d554afd1f399a` |
| Submitted results archive SHA-256 | `1728b58997966588d62b7e5f0d12d86d2f0aeab0013545f9613f46de9eba6d87` |
| Process statuses in exported CSV | 189/189 VERIFIED: 119 native, 70 Vulkan reference; 0 FAIL, HELD, NOT_RUN, UNKNOWN |
| Native tick-to-ns model | **NOT_QUALIFIED in all four suites**: `HOST_TIMESTAMP_BRACKET`, `GPU_AFTER_HOST_WINDOW` |
| Clock policy | Unchanged |

Representative medians from the exported tables. **Do not compare the two columns as performance ratios:** the native GPU tick duration was not qualified as nanoseconds.

| Workload | Native SYSMEM median GPU ticks (uncalibrated) | Vulkan reference median ns |
| --- | ---: | ---: |
| Affine | 23,488 | 11,648 |
| ParallelSort N515 | 1,497,600 | 201,888 |
| D4, 128×128 | 16,416 | 9,744 |
| K root uint4, 64×64 | 134,576 | 101,936 |
| WaveForm uint4, 64×64 | 58,528 | 12,480 |

The reporting defect for native clock `NOT_QUALIFIED` concerns time unit comparability, **not** whether Vulkan executed. The shared CSV includes all 70 Vulkan reference processes and the exported statuses mark them VERIFIED. No native-vs-Vulkan percentage or superiority claim is made for this submission.

[Community GPU index](../../README.md)
