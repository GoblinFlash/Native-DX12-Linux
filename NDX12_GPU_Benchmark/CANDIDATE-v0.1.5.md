# v0.1.5 candidate — package v21-r16

This page records the SM86/SM89 candidate prepared for v0.1.5. Merging a preparation PR does not create the tag or publish the assets. Check the [release page](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.5) for availability. If unavailable, use [v0.1.4 and its tagged instructions](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.4/NDX12_GPU_Benchmark/HOW_TO_RUN.md).

See [release notes](RELEASE-v0.1.5.md) for changes, exact artifact identities, licensing and validation limits, and [How to run](HOW_TO_RUN.md) for installation. The release PR restores the r16 pins after PR #7 while preserving its CodeRabbit rollback repair and test file.

The runtime archive is `eed38c254c8e8cc8310c8fc84fbca6081696f114aadcb63cc584cb2828b448a5`; the source companion is `fc5d6a444af1c930c20ee21a8ed74d0d87e38344b67a85d6f6b572da5259a388`. Neither archive is rebuilt for this documentation change. The installer SHA-256 is `e5ab43e95dde9d347ed66e4daed0811005bb00a37cdc0cc44b56372790fa3f4d`.

CPU evidence is scoped in the release notes. No GPU execution, real-host installation, live btrfs reproduction or SM120 qualification is claimed for r16. Separate experiments and their hardware results are not part of this package.
