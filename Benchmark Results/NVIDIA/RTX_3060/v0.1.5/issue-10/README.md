# Community submission — Issue #10

**Export consistency: CHECKED**
**Owner acceptance: NOT_RECORDED**

CHECKED refers to export consistency, not a successful or independently verified GPU run.
Intake does not record owner acceptance or infer it from a merged PR.

Source: [Issue #10](https://github.com/GoblinFlash/Native-DX12-Linux/issues/10)

**Native DX12 memory backing: SYSMEM (system-memory buffers, not VRAM)**
Vulkan memory backing: NOT_RECORDED; Native placement is not attributed to the reference.
Backing is classified from documented release identity, not independently observed host allocations.

| Field | Intake observation |
| --- | --- |
| State | DATA_READY |
| Reason | OK |
| Claimed GPU | NVIDIA/RTX_3060 |
| Archive GPU | NVIDIA/RTX_3060 |
| Claimed release | v0.1.5 |
| Archive release | v0.1.5 |
| Driver | 620.70.06 |

Model/PCI field consistency is checked against pinned vendor data; this is not hardware authentication.

The source Issue and attachment are untrusted reports. Matching catalog fields and recalculated
medians do not authenticate the machine, receipt provenance, GPU readbacks or execution.
Review background contention and all reporter notes in the Issue; they are not copied here.
Actual per-dispatch clocks are not proven. GPU durations are shown in ns below 1 ms and in ms from 1 ms.
A reported 189/189 VERIFIED count is not independent GPU qualification.

Reported overall state: `COMPLETE`; failure marker present: `false`.

## Reported process counts

| Suite | Expected | VERIFIED (reported) | FAIL | HELD | NOT_RUN | UNKNOWN | Reported clock check |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| compute | 42 | 42 | 0 | 0 | 0 | 0 | QUALIFIED |
| d4 | 63 | 63 | 0 | 0 | 0 | 0 | QUALIFIED |
| k | 42 | 42 | 0 | 0 | 0 | 0 | QUALIFIED |
| kw | 42 | 42 | 0 | 0 | 0 | 0 | QUALIFIED |

## Recalculated exported measurements

Medians below are calculated from exported per-process values, not from uploaded prose or charts.
Frame-suite values are medians of process medians. No uploaded HTML, image or raw log is reused.

| Suite | Case | Variant | Path | n | Median GPU time |
| --- | --- | --- | --- | ---: | ---: |
| compute | affine |  | native | 7 | 20416 ns |
| compute | affine |  | vulkan | 7 | 9856 ns |
| compute | affine515 |  | native | 7 | 32416 ns |
| compute | affine515 |  | vulkan | 7 | 9664 ns |
| compute | parallel-sort |  | native | 7 | 2.61 ms |
| compute | parallel-sort |  | vulkan | 7 | 182336 ns |
| d4 | 128x128 |  | vulkan | 7 | 7680 ns |
| d4 | 128x128 | B | native | 7 | 27568 ns |
| d4 | 128x128 | D4 | native | 7 | 20688 ns |
| d4 | 16x1024 |  | vulkan | 7 | 15840 ns |
| d4 | 16x1024 | B | native | 7 | 121104 ns |
| d4 | 16x1024 | D4 | native | 7 | 66544 ns |
| d4 | 32x512 |  | vulkan | 7 | 10976 ns |
| d4 | 32x512 | B | native | 7 | 67408 ns |
| d4 | 32x512 | D4 | native | 7 | 40208 ns |
| k | 127x65 |  | vulkan | 7 | 143552 ns |
| k | 127x65 | root-scalar | native | 7 | 240496 ns |
| k | 127x65 | root-uint4 | native | 7 | 211920 ns |
| k | 64x64 |  | vulkan | 7 | 74208 ns |
| k | 64x64 | root-scalar | native | 7 | 117584 ns |
| k | 64x64 | root-uint4 | native | 7 | 108160 ns |
| kw | 127x65 |  | vulkan | 7 | 10496 ns |
| kw | 127x65 | wave-root-scalar | native | 7 | 113264 ns |
| kw | 127x65 | wave-root-uint4 | native | 7 | 110160 ns |
| kw | 64x64 |  | vulkan | 7 | 10208 ns |
| kw | 64x64 | wave-root-scalar | native | 7 | 77008 ns |
| kw | 64x64 | wave-root-uint4 | native | 7 | 74352 ns |

![Exported measurements for Issue #10](chart.svg)

[Open SVG](chart.svg). Full sanitized data: [measurements.csv](measurements.csv),
[summary.csv](summary.csv), [processes.csv](processes.csv).

## Mandatory caveats

- BACKGROUND_NOT_ASSESSED
- CLOCKS_NOT_PROVEN_PER_DISPATCH
- IDENTITY_SELF_REPORTED
- KERNEL_RECORDS_REPORTED
- NO_INDEPENDENT_GPU_RERUN
- RAW_READBACKS_NOT_INCLUDED
- REVIEW_ISSUE_CONTEXT
- SEPARATE_TIMING_UNITS
- UNVERIFIED_SUBMISSION

Owner acceptance is a separate manual decision; this import does not record it.
Intake approval labels authorize processing only; they do not accept these results.
