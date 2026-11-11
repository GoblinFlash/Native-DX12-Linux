# Native DirectX 12 Experimental Benchmark For Linux — v0.1.5

v0.1.5 packages the r16 maintenance changes for SM86 and SM89 with NVIDIA Open drivers 615.78.08 and 620.70.06. It retains the RTX 30/40 device tables from v0.1.4. SM120 and RTX 50 support are not included.

This is a separate release identity. Existing tags and assets, including v0.1.4, are preserved. Release availability is determined by the [v0.1.5 release page](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.5).

## What changed

- **Kernel-event handling:** a workqueue CPU-time warning of the form `workqueue: <function> hogged CPU for >...` no longer stops a run solely because the function contains `drm`. NVIDIA-driver events, integrity/lockup events, critical kernel priorities and other warning forms keep their stop rules. The observed warning remains in the evidence.
- **Native-library preload check:** a matching path or inode is refused, including an alias whose btrfs device field differs from `stat()`. An inode collision on another filesystem is also refused conservatively. The post-load check retains the v0.1.4 btrfs fix.
- **Interpreter admission:** the native binding keeps its strict GIL-enabled interpreter checks and CPU controls.
- **Separate Vulkan reference:** a health rejection saves the child outcome and observed kernel records before propagating the stop. Known pre-submit failures close the observation descriptor. A service that ended without its completion record is distinguished from an active-service timeout; its outcome remains `UNCERTAIN`, with no automatic stop or retry.
- **Installer rollback:** if replacing a package and restoring the previous one both fail, the installer identifies the preserved folder and reports an incomplete installation. The CodeRabbit repair and three regression tests from [PR #7](https://github.com/GoblinFlash/Native-DX12-Linux/pull/7) are retained; this release changes the version and artifact pins.
- **Package manual:** the runnable archive contains the operational README and readable export history. Export checks compare the packaged desktop and Vulkan tools with both source snapshots.

The four runtime inventories use existing compiled inputs. Native ELF files, shaders and the external starter are unchanged; this is not a new compiler or shader build.

## Install and share

Follow [How to run v0.1.5](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.5/NDX12_GPU_Benchmark/HOW_TO_RUN.md). Use the v0.1.5 installer with the matching runtime archive and starter. The installer writes a receipt which the launcher checks before naming the release in charts and `share-results-v0.1.5.tar.gz`.

An older package that does not match this manifest is moved aside before replacement. If rollback fails, preserve the folder named by the installer and resolve the reported file-operation error before retrying. No automatic GPU recovery or retry is added.

## Artifacts

| File | SHA-256 | Bytes |
| --- | --- | ---: |
| `ndx12-native-benchmark-v21-615.78.08-620.70.06.tar.gz` | `eed38c254c8e8cc8310c8fc84fbca6081696f114aadcb63cc584cb2828b448a5` | 2506060 |
| `ndx12_start.py` | `8cd0ca349f4535741ae8a673b3aa10de4a0b5f953c283543a453a850337aced5` | 10958 |
| `ndx12-benchmark-v0.1.5-source.tar.gz` | `fc5d6a444af1c930c20ee21a8ed74d0d87e38344b67a85d6f6b572da5259a388` | 4199515 |
| `ndx12-install.py` (repository file) | `e5ab43e95dde9d347ed66e4daed0811005bb00a37cdc0cc44b56372790fa3f4d` | 21597 |

The runtime's `MANIFEST.sha256` has SHA-256 `c6bd8d3575a63304783cb412bafa38d31f2de4eeedfc8d9f9e276fbd0e48c56d` and covers 933 files. The source companion manifest covers 669 files. Hashes identify bytes; they do not prove GPU execution.

## Validation scope

Saved final-r16 CPU evidence covers four focused runs of 89 test methods (SM86/SM89, normal and optimized Python), eight methods against the actual packaged Vulkan tool, 36 installer tests in each Python mode, and 34 named installation cases across 35 user-namespace runs. The Vulkan process/service controls use CPU models; their filesystem and pipe/parser operations are real.

The eight earlier full suites of 591 tests each belong to predecessor source identities. They were not rerun for the final tool changes. The current release preparation ran 39 installer tests in normal Python and 39 with `-O`: 31 existing unit tests, five filesystem/starter rollback controls and the three public rollback regressions from PR #7. These tests loaded the new release installer and checked its pins against the retained package; predecessor installer hashes were not treated as validation of the new file.

CodeRabbit CLI completed reviews of the selected final r16 files, with exact-byte coverage and retained triage. The final five-file review reported two findings, dismissed using controls for the pinned build recipe and starter; this was not a zero-finding whole-package review. GitHub review of the release PR covers the public PR files, not the private runtime/source archives.

**GPU, real-host installation, live btrfs reproduction and SM120: NOT_RUN for r16.** Results from other revisions or experimental candidates do not qualify this archive. No new performance, GPU-correctness or device-compatibility result is claimed. An end-to-end upgrade from a real installed v0.1.4 host was not run.

A pre-existing reporting limitation remains in direct command-line Vulkan auto mode: some non-executed probe states may be described incorrectly in the summary. The interactive launcher uses explicit on/off mode.

## Sources and licenses

The source companion provides the SM86/SM89 snapshots, tests, shader sources and pinned build recipes matching this runtime package. It omits the two prebuilt development Vulkan-reference executables; their C++ source and build command remain. The companion does not contain the separately distributed top-level release installer or its GitHub regression-test file; those have public repository history.

Project-owned material remains GPL-3.0-or-later. Retained third-party terms and notices are unchanged; there is no clean-room or blanket original-authorship claim. `LICENSE` and `NOTICE` are unchanged in both archives. See [Source and licenses](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.5/NDX12_GPU_Benchmark/SOURCE_AND_LICENSES.md) and the companion README for provenance, build prerequisites and historical rebuild limits.
