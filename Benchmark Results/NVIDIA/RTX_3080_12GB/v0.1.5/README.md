<!-- ndx12:gpu:NVIDIA/RTX_3080_12GB/v0.1.5:start -->
# RTX 3080 12GB — benchmark v0.1.5

## [Issue #42](https://github.com/GoblinFlash/Native-DX12-Linux/issues/42)

GPU PCI ID: `10de:220a` · Driver: `615.78.08` · Export: **189/189 VERIFIED** · Host/GPU clock check: **QUALIFIED, 4/4 suites**.

**Native DX12 memory backing: SYSMEM (system-memory buffers, not VRAM)**. [Release evidence](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.5/NDX12_GPU_Benchmark/README.md#L113).

![RTX 3080 12GB selected workload medians](issue-42/chart.svg)

*Selected medians from the four suites; all variants appear in the tables below.*

### Compute suite

| Workload / native variant | Native SYSMEM median GPU time | Vulkan median GPU time |
| --- | ---: | ---: |
| Affine | 36,032 ns | 21,696 ns |
| Affine N515 | 28,928 ns | 22,080 ns |
| ParallelSort N515 | 3.05 ms | 268,224 ns |

### Test 1 — D4

| Workload / native variant | Native SYSMEM median GPU time | Vulkan median GPU time |
| --- | ---: | ---: |
| 128×128 Original | 44,240 ns | 19,296 ns |
| 128×128 D4 | 39,920 ns | 19,296 ns |
| 32×512 Original | 66,048 ns | 19,648 ns |
| 32×512 D4 | 41,936 ns | 19,648 ns |
| 16×1024 Original | 104,544 ns | 24,688 ns |
| 16×1024 D4 | 61,312 ns | 24,688 ns |

### Test 2 — K

| Workload / native variant | Native SYSMEM median GPU time | Vulkan median GPU time |
| --- | ---: | ---: |
| 64×64 scalar | 463,120 ns | 108,224 ns |
| 64×64 uint4 | 218,912 ns | 108,224 ns |
| 127×65 scalar | 738,240 ns | 211,552 ns |
| 127×65 uint4 | 986,784 ns | 211,552 ns |

### Test 3 — K WaveForm

| Workload / native variant | Native SYSMEM median GPU time | Vulkan median GPU time |
| --- | ---: | ---: |
| 64×64 scalar | 221,264 ns | 18,384 ns |
| 64×64 uint4 | 218,160 ns | 18,384 ns |
| 127×65 scalar | 537,264 ns | 23,408 ns |
| 127×65 uint4 | 272,944 ns | 23,408 ns |

[Full sanitized per-Issue data](issue-42/README.md) · [All v0.1.5 submissions](../../../v0.1.5-submitted-data.md#rtx-3080-12gb--issue-42)

Exported statuses and clock checks are reported evidence, not independent GPU qualification.
<!-- ndx12:gpu:NVIDIA/RTX_3080_12GB/v0.1.5:end -->
