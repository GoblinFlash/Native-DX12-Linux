# Community benchmark results

**Release-specific memory backing:** existing v0.1.4 results use **Native DX12 memory backing: SYSMEM (system-memory buffers, not VRAM)**. The documented v0.1.5 release also uses SYSMEM; future releases require separate artifact-bound evidence. Vulkan memory backing is NOT_RECORDED and is not inferred from Native DX12. The experimental VRAM candidate is separate. [v0.1.4 evidence](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.4/NDX12_GPU_Benchmark/README.md#L111) · [v0.1.5 evidence](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.5/NDX12_GPU_Benchmark/README.md#L113).

Community submissions are collected as public [Benchmark Results issues](https://github.com/GoblinFlash/Native-DX12-Linux/issues?q=is%3Aissue+label%3Abenchmark%3Asubmission). A GitHub Actions workflow labels recognized GPU models. **Labels categorize submissions; they do not approve correctness or performance claims.**

## Automated community intake — UNVERIFIED

<!-- ndx12-community-intake:start -->
<!-- ndx12-community-intake:end -->

Intake entries remain **UNVERIFIED** even after a draft PR is merged. Export consistency does not prove GPU execution or permit Native-versus-Vulkan rankings.

## Curated v0.1.4 report

**[Benchmark v0.1.4 — charts and extracted results for RTX 3060, RTX 3060 Ti, RTX 3090 and RTX 4060 Laptop GPU](v0.1.4-submitted-data.md)**

This report contains GPU-specific charts and median values recalculated from the four attached `share-results-v0.1.4.tar.gz` archives. The separate Native (GPU ticks) and Vulkan (nanoseconds) columns preserve the units, including the RTX 3090 run where conversion was **NOT_QUALIFIED**. Charts show four selected workloads per GPU; full numeric variants remain in the tables.

## Existing curated GPU folders and review status

- [NVIDIA RTX 4090](NVIDIA/RTX_4090/README.md) — reserved for approved community submissions; maintainer-recorded experiments are [separate](../NVIDIA/README.md).
- [NVIDIA RTX 3090](NVIDIA/RTX_3090/README.md) — [Issue #5](NVIDIA/RTX_3090/issue-5.md), archive-consistency reviewed; all four timestamp checks NOT_QUALIFIED.
- [NVIDIA RTX 3060 Ti](NVIDIA/RTX_3060_Ti/README.md) — [Issue #3](NVIDIA/RTX_3060_Ti/issue-3.md), archive-consistency reviewed; concurrent ONNX GPU usage disclosed.
- [NVIDIA RTX 3060](NVIDIA/RTX_3060/README.md) — Issue #4 model and kernel-message explanation received from reporter; **maintainer acceptance pending**.
- [NVIDIA RTX 4060 Laptop GPU](NVIDIA/RTX_4060_Laptop_GPU/README.md) — [Issue #2](NVIDIA/RTX_4060_Laptop_GPU/issue-2.md), archive-consistency reviewed.

The issue-specific reviews cover exported archive consistency, **not independent GPU reruns**. A new model needs its own GPU folder and must not be combined with a similar GPU name.

## Review before approval

Before approval, inspect the benchmark and archive identity, exact GPU and driver, reported GPU submission/completion, output correctness, run status, timing model, failures, and privacy. Keep raw evidence and machine identifiers out of public summaries. Failed, partial and unqualified runs remain visible with their actual limitations.

The GPU categorizer labels Issues. The separate intake workflow described below proposes draft PRs for review. A folder or Issue link is not itself a maintainer performance endorsement.

## Intake and versioned storage

The intake workflow reads only a bounded, supported share-results data format and proposes a **draft PR**. A maintainer must authorize processing for an outside contributor with `benchmark:intake-approved` or a manual workflow dispatch. This authorization permits intake only; it does not accept the result. No workflow merges, approves, closes Issues or changes the existing GPU-category labels.

New records use `<vendor>/<exact_GPU>/<release>/issue-<number>/`. Ti, Laptop GPU, Super and D models remain distinct. Unknown GPUs and conflicting model/release identities go to `Pending_Classification/<release>/issue-<number>/`; unknown releases use `Unidentified_Version`. Strings from an Issue never become arbitrary paths.

Supported, internally consistent archives produce sanitized process/measurement CSV, recalculated medians and a fresh chart with separate Native GPU-tick and Vulkan-nanosecond scales. Uploaded HTML, SVG, prose, system details and raw logs are not copied. A missing, malformed, unsupported or inconsistent archive produces only a clearly marked manual-review record, with no extracted measurements.

Every generated record remains **UNVERIFIED**, including a reported 189/189 count or QUALIFIED clock status. The share export does not establish independent GPU execution, readback correctness, actual per-dispatch clocks, receipt provenance or absence of background contention. Review the source Issue and its caveats before approval.

Existing curated records stay in place. Version indexes link to those records and the centralized tables instead of duplicating them:

| Issue | Exact GPU / release | Migration |
| --- | --- | --- |
| #2 | [RTX 4060 Laptop GPU / v0.1.4](NVIDIA/RTX_4060_Laptop_GPU/v0.1.4/README.md) | Link existing review and centralized measurements. |
| #3 | [RTX 3060 Ti / v0.1.4](NVIDIA/RTX_3060_Ti/v0.1.4/README.md) | Preserve disclosed concurrent ONNX GPU usage. |
| #4 | [RTX 3060 / v0.1.4](NVIDIA/RTX_3060/v0.1.4/README.md) | Preserve model explanation received and maintainer acceptance pending. |
| #5 | [RTX 3090 / v0.1.4](NVIDIA/RTX_3090/v0.1.4/README.md) | Preserve all four NOT_QUALIFIED timestamp checks. |
| #11 | Claimed RTX 3090 / v0.1.5 | The inspected attachment reports RTX 3060: GPU_MISMATCH. Manual review under Pending_Classification; no RTX 3090 measurements are imported. Recheck the live Issue before processing. |

One Issue has one stable intake branch and draft PR. Duplicate, edited or reopened events never overwrite an existing review, PR or curated record. The source is checked immediately before creating a new branch ref. A later Issue change is shown in the draft body as `STALE`, with prepared/observed source fingerprints and the pinned snapshot commit; an unavailable final observation is `UNKNOWN`. Reviewers reconcile these observations before acceptance. Recovery of a pre-existing orphan still requires matching source, permission and exact branch bytes. See [the intake operator guide](https://github.com/GoblinFlash/Native-DX12-Linux/blob/main/.github/scripts/README.md) for permissions, limits, tests, failure handling and the owner approval gate.

[All experiment results](../README.md)
