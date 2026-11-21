# Community submission — Issue #11

**Export consistency: REQUIRES_REVIEW**
**Owner acceptance: NOT_RECORDED**

CHECKED refers to export consistency, not a successful or independently verified GPU run.
Intake does not record owner acceptance or infer it from a merged PR.

Source: [Issue #11](https://github.com/GoblinFlash/Native-DX12-Linux/issues/11)

**Native DX12 memory backing: UNKNOWN (release evidence NOT_RECORDED)**
Vulkan memory backing: NOT_RECORDED; Native placement is not attributed to the reference.
Backing is classified from documented release identity, not independently observed host allocations.

| Field | Intake observation |
| --- | --- |
| State | MANUAL_REVIEW |
| Reason | GPU_MISMATCH |
| Claimed GPU | NVIDIA/RTX_3090 |
| Archive GPU | NVIDIA/RTX_3060 |
| Claimed release | v0.1.5 |
| Archive release | v0.1.5 |
| Driver | Not established |

Model/PCI field consistency is checked against pinned vendor data; this is not hardware authentication.

The source Issue and attachment are untrusted reports. Matching catalog fields and recalculated
medians do not authenticate the machine, receipt provenance, GPU readbacks or execution.
Review background contention and all reporter notes in the Issue; they are not copied here.
Actual per-dispatch clocks are not proven. Native GPU ticks and Vulkan nanoseconds stay separate.
A reported 189/189 VERIFIED count is not independent GPU qualification.

No numeric result or uploaded chart is proposed while this refusal remains unresolved.
Inspect and correct the source Issue/attachment, then request a new reviewed intake.

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

## Required source correction

The submitted archive SHA-256 is identical to Issue #10 and identifies RTX 3060 (`10de:2503`), not the claimed RTX 3090. No RTX 3090 measurements are available from this attachment. Provide a genuine v0.1.5 share-results bundle from the RTX 3090, with matching GPU model/PCI ID, release identity and driver in `run.json` and corresponding exported tables. Renaming the archive or editing the Issue declaration is insufficient. A maintainer must reconcile any correction; this record remains MANUAL_REVIEW.
