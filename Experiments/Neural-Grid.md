# Neural Grid — experimental learned lighting representation

<sub>Research overview · experiments recorded 17–20 November 2026 · not a released benchmark feature</sub>

Neural Grid explores whether learned representations can reduce the storage cost of lighting data while preserving useful reconstruction quality and reasonable GPU execution time. It also examines the cost of using scene-lighting data relative to selected indirect-light computations.

## What has been demonstrated

- Bounded CPU and GPU experiments were recorded on **GeForce RTX 4060 Ti and RTX 4090** for selected workloads.
- Selected learned-decoder and indirect-light outputs were checked against CPU references on their recorded inputs; negative checks were part of the campaigns.
- A compact learned decoder could execute on the experimental native GPU path. For the tested real-scene lighting data, simpler representations were sometimes equally good or better in the measured trade-off.
- Tests indicated meaningful quality-versus-cost differences between prepared lighting data and ray-based work. They do not establish a universally best rendering technique.

## Status and limits

**Status: experimental GPU evidence for specific datasets and one principal scene (Sponza).** These experiments do not establish a complete real-time global-illumination system, performance on moving game scenes, cross-GPU speedups or a Vulkan advantage. Results from different hardware campaigns must not be combined without matching their conditions.

The recorded experiments did not include a matched Vulkan comparison or complete independent release qualification. Future application integration requires its own evidence and licensing checks.

**Scene attribution:** Sponza model © 2010 Frank Meinl, Crytek, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). Experimental lighting data and images are adaptations.

[Experiments overview](README.md) · [Cube Matrix](Cube-Matrix.md)

**Andrew Kapica — GoblinFlash.** AI-assisted development; bounded experimental status only.
