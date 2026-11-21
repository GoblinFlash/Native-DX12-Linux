# NVIDIA — Benchmark Results

**Test hardware:** GeForce RTX 4090 (Ada Lovelace).

These are recorded GPU compute experiments. The two performance charts compare a version before a specific change with a version after it. Both versions were checked for correct output.

## Test 1 — Faster histogram calculations

**What does it do?** The GPU counts how often each number from 0 to 255 appears in 16,384 generated values, similar to counting brightness levels in an image.

**What changed?** Four repeated operations were grouped together in the experimental NVIDIA shader compiler path.

| Arrangement of the same 16,384 values | Before | After | Less time |
| --- | ---: | ---: | ---: |
| 128×128 | 3,392 ns | 2,624 ns | 22.64% |
| 32×512 | 7,936 ns | 4,848 ns | 39.01% |
| 16×1024 | 14,112 ns | 7,872 ns | 44.22% |

The arrangements describe how the generated values were organized for the test. They are not display resolutions. The recorded experiment passed 2,880 full output-buffer comparisons.

![RTX 4090 histogram experiment — original before-and-after chart](rtx4090-d4-original.png)

## Test 2 — Four GPU programs working together

**What does it do?** Four connected GPU programs prepare generated numbers, count them and combine the counts into a final result.

**What changed?** The final program reads four neighboring counts together instead of reading them one at a time.

| Generated input | Before | After | Less time for all four programs |
| --- | ---: | ---: | ---: |
| 64×64 (4,096 values) | 4,608 ns | 4,336 ns | 5.90% |
| 127×65 (8,255 values) | 5,632 ns | 5,344 ns | 5.11% |

This measures the complete four-program GPU sequence, not just the changed final program. The recorded experiment passed 2,620 full output-buffer comparisons. Vulkan and CUDA appear on the chart as separate reference measurements, not a universal speed ranking.

![RTX 4090 full GPU sequence — original chart](rtx4090-fullbench-original.png)

## Other recorded RTX 4090 execution tests

| Test | What was checked | Result in the recorded run |
| --- | --- | --- |
| Affine u32 | A small numerical calculation and its complete output | GPU work completed; output matched the independent expected result |
| FidelityFX ParallelSort | Sorting 515 values across 40 GPU dispatches | GPU work completed; the final sorting and permutation checks passed |

These two execution checks do not include a qualified performance comparison.

## Submitted benchmark results by GPU model

Reports from external contributors are organized under the exact GPU model. They are distinct from the maintainer-recorded experiments above; export checks do not imply independent GPU execution or owner acceptance.

- [GeForce RTX 3060](RTX_3060/README.md)
- [GeForce RTX 3060 Ti](RTX_3060_Ti/README.md)
- [GeForce RTX 3090](RTX_3090/README.md)
- [GeForce RTX 4060](RTX_4060/v0.1.5/README.md)
- [GeForce RTX 4060 Laptop GPU](RTX_4060_Laptop_GPU/README.md)
- [GeForce RTX 4090](RTX_4090/v0.1.5/README.md)

[All submissions and review status](../SUBMISSIONS.md). Unresolved GPU identities remain in [Pending Classification](../Pending_Classification/v0.1.5/issue-11/README.md) rather than being assigned to a model.

## Reproducing the results

Work is underway to make GPU benchmarks easier to run on another Linux machine. The public source release does not yet contain a ready-to-run version of these exact benchmark campaigns. The underlying development evidence for the charts is retained privately.

For the recorded hardware, methods, source identities and limitations, see [measurement and execution details](measurement-details.md). Build and CPU checks are documented [separately](../../docs/validation.md).

[All benchmark results](../README.md) · [Project home](../../README.md)
