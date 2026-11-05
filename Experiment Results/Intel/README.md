# Intel — Experiment Results

**Early development hardware:** Intel Iris Xe.

Intel was used during early development of Native DX12 Linux. The public repository contains example programs and build checks, but it does not yet include a qualified Intel GPU performance benchmark.

## What can be examined in the source?

| Program | What it is designed to test |
| --- | --- |
| [Compute](../../tests/intel/compute.cpp) | GPU calculations and checking the returned values |
| [Triangle](../../tests/intel/triangle.cpp) | Drawing a basic shape and checking the image |
| [Textured quad](../../tests/intel/textured_quad.cpp) | Drawing a rectangle with a texture |
| [Indexed depth](../../tests/intel/indexed_depth.cpp) | Drawing with indexed geometry and depth testing |
| [Gallium probes](../../tests/intel/probes/) | Selected driver and interface behavior |

These files describe test workloads. Their presence alone does not establish a successful GPU run or a performance result for the current release.

**Next step:** publish clearly identified Intel GPU test results and measurements when available.

[All experiment results](../README.md) · [Project home](../../README.md)
