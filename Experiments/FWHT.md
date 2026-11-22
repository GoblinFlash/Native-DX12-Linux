# FWHT — dependent native compute workloads

<sub>Development experiment · recorded 12 November 2026 · not a released benchmark result</sub>

The Fast Walsh–Hadamard Transform (FWHT) is established mathematics, not a newly invented algorithm. It was used here as a deterministic workload for examining dependent GPU tasks, memory visibility, resource reuse and safe completion in the experimental native execution path.

## Recorded scope

- **RTX 5070:** a bounded pilot compared GPU execution intervals across selected memory-placement profiles. Saved outputs were checked, but one variant had a tool-audit limitation and does not carry the same qualification as the fully accepted profile.
- **RTX 4090:** a separate pilot compared host-side costs of fresh and retained sessions. Those results concern preparation and lifecycle overhead, **not a measured speedup of shader execution**.
- CPU tooling and integration checks were recorded for an early full-benchmark candidate. At that checkpoint, the integrated candidate's NVIDIA GPU execution and final release qualification were **not completed**.

## What this does not establish

These observations do not prove improved NVIDIA L1/L2 cache behavior, an advantage over Vulkan, support across other GPUs or complete Direct3D 12 functionality. Host elapsed time and GPU timestamps measure different intervals. Later package revisions must be tested separately.

**Status: pilot evidence only.** A final, independently checked integrated benchmark result was not available at the recorded checkpoint.

[Experiments overview](README.md) · [Benchmark Results](../Benchmark%20Results/README.md)

**Andrew Kapica — GoblinFlash.**
