# Community submission — Issue #15

**Export consistency: CHECKED**
**Owner acceptance: NOT_RECORDED**

CHECKED refers to export consistency, not a successful or independently verified GPU run.
Intake does not record owner acceptance or infer it from a merged PR.

Source: [Issue #15](https://github.com/GoblinFlash/Native-DX12-Linux/issues/15)

**Native DX12 memory backing: SYSMEM (system-memory buffers, not VRAM)**
Vulkan memory backing: NOT_RECORDED; Native placement is not attributed to the reference.
Backing is classified from documented release identity, not independently observed host allocations.

| Field | Intake observation |
| --- | --- |
| State | DATA_READY |
| Reason | OK |
| Claimed GPU | NVIDIA/RTX_4060 |
| Archive GPU | NVIDIA/RTX_4060 |
| Claimed release | v0.1.5 |
| Archive release | v0.1.5 |
| Driver | 615.78.08 |

The source Issue and attachment are untrusted reports. Matching catalog fields and recalculated
medians do not authenticate the machine, receipt provenance, GPU readbacks or execution.
Review background contention and all reporter notes in the Issue; they are not copied here.
Actual per-dispatch clocks are not proven. Native GPU ticks and Vulkan nanoseconds stay separate.
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

| Suite | Case | Variant | Path | Unit | n | Median |
| --- | --- | --- | --- | --- | ---: | ---: |
| compute | affine |  | native | GPU_TICKS | 7 | 22176 |
| compute | affine |  | vulkan | NS | 7 | 8320 |
| compute | affine515 |  | native | GPU_TICKS | 7 | 21408 |
| compute | affine515 |  | vulkan | NS | 7 | 8256 |
| compute | parallel-sort |  | native | GPU_TICKS | 7 | 2599104 |
| compute | parallel-sort |  | vulkan | NS | 7 | 150816 |
| d4 | 128x128 |  | vulkan | NS | 7 | 6896 |
| d4 | 128x128 | B | native | GPU_TICKS | 7 | 26848 |
| d4 | 128x128 | D4 | native | GPU_TICKS | 7 | 20336 |
| d4 | 16x1024 |  | vulkan | NS | 7 | 14048 |
| d4 | 16x1024 | B | native | GPU_TICKS | 7 | 118592 |
| d4 | 16x1024 | D4 | native | GPU_TICKS | 7 | 63760 |
| d4 | 32x512 |  | vulkan | NS | 7 | 9968 |
| d4 | 32x512 | B | native | GPU_TICKS | 7 | 64864 |
| d4 | 32x512 | D4 | native | GPU_TICKS | 7 | 37696 |
| k | 127x65 |  | vulkan | NS | 7 | 15152 |
| k | 127x65 | root-scalar | native | GPU_TICKS | 7 | 320272 |
| k | 127x65 | root-uint4 | native | GPU_TICKS | 7 | 265264 |
| k | 64x64 |  | vulkan | NS | 7 | 10496 |
| k | 64x64 | root-scalar | native | GPU_TICKS | 7 | 141152 |
| k | 64x64 | root-uint4 | native | GPU_TICKS | 7 | 111664 |
| kw | 127x65 |  | vulkan | NS | 7 | 9264 |
| kw | 127x65 | wave-root-scalar | native | GPU_TICKS | 7 | 157984 |
| kw | 127x65 | wave-root-uint4 | native | GPU_TICKS | 7 | 154960 |
| kw | 64x64 |  | vulkan | NS | 7 | 9120 |
| kw | 64x64 | wave-root-scalar | native | GPU_TICKS | 7 | 86336 |
| kw | 64x64 | wave-root-uint4 | native | GPU_TICKS | 7 | 83488 |

![Exported measurements for Issue #15](chart.svg)

[Open SVG](chart.svg). Full sanitized data: [measurements.csv](measurements.csv),
[summary.csv](summary.csv), [processes.csv](processes.csv).

## Mandatory caveats

- BACKGROUND_NOT_ASSESSED
- CLOCKS_NOT_PROVEN_PER_DISPATCH
- IDENTITY_SELF_REPORTED
- NO_INDEPENDENT_GPU_RERUN
- RAW_READBACKS_NOT_INCLUDED
- REVIEW_ISSUE_CONTEXT
- SEPARATE_TIMING_UNITS
- UNVERIFIED_SUBMISSION

Owner acceptance is a separate manual decision; this import does not record it.
Intake approval labels authorize processing only; they do not accept these results.
