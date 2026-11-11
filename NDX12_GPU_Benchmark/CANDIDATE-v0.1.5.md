# v0.1.5 candidate — package v21-r16

This page records the SM86/SM89 candidate prepared for v0.1.5. Merging a preparation PR does not create the tag or publish the assets. Check the [release page](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.5) for availability. If unavailable, use [v0.1.4 and its tagged instructions](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.4/NDX12_GPU_Benchmark/HOW_TO_RUN.md).

See [release notes](RELEASE-v0.1.5.md) for changes, exact artifact identities, licensing and validation limits, and [How to run](HOW_TO_RUN.md) for installation. The release PR restores the r16 pins after PR #7 while preserving its CodeRabbit rollback repair and test file.

The runtime archive is `eed38c254c8e8cc8310c8fc84fbca6081696f114aadcb63cc584cb2828b448a5`; the source companion is `1061469e9cf78fe49d28e2d1fc6741e04f506c005e7ae473dfb2a5f3c3d9ca99`. The runtime archive is unchanged. The source companion includes the later source-only dependency-builder repair; it was built twice with identical bytes. The installer SHA-256 is `e5ab43e95dde9d347ed66e4daed0811005bb00a37cdc0cc44b56372790fa3f4d`.

CPU evidence is scoped in the release notes. No GPU execution, real-host installation, live btrfs reproduction or SM120 qualification is claimed for r16. Separate experiments and their hardware results are not part of this package.
