# NVIDIA GeForce RTX 3060 — community results

**Existing v0.1.4 results — Native DX12 memory backing: SYSMEM (system-memory buffers, not VRAM).** This is the documented backing of the release artifact, not independent observation of the submitted host. Vulkan memory backing: **NOT_RECORDED**; do not infer it from Native DX12. [Release evidence](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.4/NDX12_GPU_Benchmark/README.md#L111). The experimental VRAM candidate is separate.

**Review status: reporter clarification received; final maintainer acceptance pending.**

[Issue #4](https://github.com/GoblinFlash/Native-DX12-Linux/issues/4) was originally submitted as RTX 3060 Ti, but the v0.1.4 archive identifies **NVIDIA GeForce RTX 3060 (PCI `10de:2503`)**. The reporter subsequently checked the physical card and confirmed that it is the regular RTX 3060.

The attached export reports **189/189 VERIFIED** process statuses, including 119 native and 70 Vulkan reference processes. All four conditional native tick-to-nanosecond checks are reported QUALIFIED. These are exported statuses, not independently repeated GPU execution.

One exported row has `kernel_records=1` (compute / affine515 / native / repeat 4). The reporter identified it as an `hrtimer` interrupt-latency message, unrelated to GPU faults, and reported no Xid/ECC/NVRM errors. The original kernel log line is not included in the shared archive; the explanation is **reporter-provided**, not independently verified.

**[Read the extracted v0.1.4 measurements](../../v0.1.4-submitted-data.md#rtx-3060--issue-4)**. Publishing these submitted values does not mean the run has been accepted as an independently qualified performance baseline.

[All community GPU results](../../README.md)
