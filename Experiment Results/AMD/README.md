# AMD — Experiment Results

**Current public evidence:** CPU-side checks of the RadeonSI adapter. An AMD GPU benchmark has not yet been qualified in this release.

The source includes a CORE/RadeonSI adapter, compiler dependencies and CPU contract tests. Full AMD frontend and device execution have not been qualified in this release.

## What has been tested?

The recorded adapter test covered 56 CPU-side checks, including:

- Supported capabilities and shader preparation.
- Resource views and GPU state descriptions.
- Resource binding and inspection of prepared operations.

The recorded checks also produced four output images. These are CPU-side results, not measured execution on an AMD graphics card.

**Source files:** [AMD adapter tests](../../tests/amd/test_adapter.c) and [sample shaders](../../tests/amd/shaders/).

**Next step:** native AMD GPU execution and measurements with a clearly identified device, driver and test workload.

[All experiment results](../README.md) · [Project home](../../README.md)
