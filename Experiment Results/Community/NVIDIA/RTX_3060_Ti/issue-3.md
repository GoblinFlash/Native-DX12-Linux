# Issue #3 — RTX 3060 Ti, benchmark v0.1.4

**Existing v0.1.4 results — Native DX12 memory backing: SYSMEM (system-memory buffers, not VRAM).** This is the documented backing of the release artifact, not independent observation of the submitted host. Vulkan memory backing: **NOT_RECORDED**; do not infer it from Native DX12. [Release evidence](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.4/NDX12_GPU_Benchmark/README.md#L111). The experimental VRAM candidate is separate.

**Source:** [Community Issue #3](https://github.com/GoblinFlash/Native-DX12-Linux/issues/3) (reporter: `labj1987`), with attached `share-results-v0.1.4.tar.gz`.

**Review scope:** The submitted `run.json`, `summary.txt` and all exported CSVs were checked for internal consistency, with no archive members executed. The original per-process GPU receipts are **not** included; this review does not independently reproduce GPU work or validate every GPU runtime claim.

| Field | Submitted / checked export |
| --- | --- |
| GPU | NVIDIA GeForce RTX 3060 Ti, PCI `10de:2489` |
| NVIDIA driver | 620.70.06 Open |
| OS | Ubuntu 26.04.1 LTS; kernel `7.3.3-kernelpop` |
| Benchmark package | v0.1.4 / v21-r14; release archive SHA-256 `a4d707dd50fa9fa22d554732d4e97dfbb54c5ab4ce6fee225c7d554afd1f399a` |
| Submitted results archive SHA-256 | `1a2e6db004472d83194e25ca09180b725ddc483a4ae78a2f7a2c2abcc9ffeba7` |
| Process statuses in exported CSV | 189/189 VERIFIED: 119 native, 70 Vulkan reference; 0 FAIL, HELD, NOT_RUN, UNKNOWN |
| Reported timestamp qualification | QUALIFIED in all four suites under the runner's cross-process clock model |
| Clock policy | Unchanged |

Representative medians from the exported tables (native results are **GPU ticks**, Vulkan results are **nanoseconds**; whole-work measurements, not shader-only):

| Workload | Native SYSMEM median GPU ticks | Vulkan reference median ns |
| --- | ---: | ---: |
| Affine | 6,720 | 10,336 |
| ParallelSort N515 | 477,184 | 194,560 |
| D4, 128×128 | 5,728 | 7,936 |
| K root uint4, 64×64 | 27,632 | 16,912 |
| WaveForm uint4, 64×64 | 22,096 | 10,624 |

**Important limitation:** The reporter states that an always-on ONNX object-detection process was using the same GPU throughout the run. These times therefore include potential GPU contention, and they must not be pooled with idle-GPU benchmarks or promoted as a universal performance ranking. A conditional tick-to-nanosecond model and 7 paired samples per comparison do not eliminate that limitation.

The archive's GPU identity agrees with Issue #3. Issue #4 was initially misidentified as RTX 3060 Ti, but its reporter later confirmed the tested model is a regular RTX 3060; it is documented [separately](../RTX_3060/README.md) with its own acceptance status.

[Complete extracted v0.1.4 data](../../v0.1.4-submitted-data.md) · [Community GPU index](../../README.md)
