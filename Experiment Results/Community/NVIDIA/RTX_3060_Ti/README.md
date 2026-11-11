# NVIDIA GeForce RTX 3060 Ti — community results

**Archive-consistency checked** submission:

- [Issue #3 — v0.1.4 benchmark](issue-3.md), reported on a desktop RTX 3060 Ti (PCI `10de:2489`).

The exported `run.json`, summary and CSV files are internally consistent, but the original per-process GPU receipts were not included. Timings were recorded while an unrelated ONNX inference service was also using the GPU; this is **not** a controlled idle-GPU performance baseline.

Issue #4 is **not** an RTX 3060 Ti result. Its original model mismatch was clarified by the reporter, who confirmed a regular RTX 3060. See the [RTX 3060 submission status](../RTX_3060/README.md).

[Extracted v0.1.4 measurements](../../v0.1.4-submitted-data.md#rtx-3060-ti--issue-3) · [All community GPU results](../../README.md)
