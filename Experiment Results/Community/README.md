# Community benchmark results

Community submissions are collected as public [Benchmark Results issues](https://github.com/GoblinFlash/Native-DX12-Linux/issues?q=is%3Aissue+label%3Abenchmark%3Asubmission). A GitHub Actions workflow labels recognized GPU models. **Labels categorize submissions; they do not approve correctness or performance claims.**

## Latest submitted data

**[Benchmark v0.1.4 — charts and extracted results for RTX 3060, RTX 3060 Ti, RTX 3090 and RTX 4060 Laptop GPU](v0.1.4-submitted-data.md)**

This report contains GPU-specific charts and median values recalculated from the four attached `share-results-v0.1.4.tar.gz` archives. The separate Native (GPU ticks) and Vulkan (nanoseconds) columns preserve the units, including the RTX 3090 run where conversion was **NOT_QUALIFIED**. Charts show four selected workloads per GPU; full numeric variants remain in the tables.

## GPU-specific folders and review status

- [NVIDIA RTX 4090](NVIDIA/RTX_4090/README.md) — reserved for approved community submissions; maintainer-recorded experiments are [separate](../NVIDIA/README.md).
- [NVIDIA RTX 3090](NVIDIA/RTX_3090/README.md) — [Issue #5](NVIDIA/RTX_3090/issue-5.md), archive-consistency reviewed; all four timestamp checks NOT_QUALIFIED.
- [NVIDIA RTX 3060 Ti](NVIDIA/RTX_3060_Ti/README.md) — [Issue #3](NVIDIA/RTX_3060_Ti/issue-3.md), archive-consistency reviewed; concurrent ONNX GPU usage disclosed.
- [NVIDIA RTX 3060](NVIDIA/RTX_3060/README.md) — Issue #4 model and kernel-message explanation received from reporter; **maintainer acceptance pending**.
- [NVIDIA RTX 4060 Laptop GPU](NVIDIA/RTX_4060_Laptop_GPU/README.md) — [Issue #2](NVIDIA/RTX_4060_Laptop_GPU/issue-2.md), archive-consistency reviewed.

The issue-specific reviews cover exported archive consistency, **not independent GPU reruns**. A new model needs its own GPU folder and must not be combined with a similar GPU name.

## Review before approval

Before approval, inspect the benchmark and archive identity, exact GPU and driver, reported GPU submission/completion, output correctness, run status, timing model, failures, and privacy. Keep raw evidence and machine identifiers out of public summaries. Failed, partial and unqualified runs remain visible with their actual limitations.

No workflow automatically downloads submissions, commits benchmark data or approves the results. A folder or Issue link is not itself a maintainer performance endorsement.

[All experiment results](../README.md)
