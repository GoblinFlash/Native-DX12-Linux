# v0.1.5 candidate — package v21-r16

**Candidate only: v0.1.5 has not been released.** This branch prepares an SM86/SM89 package for NVIDIA Open drivers 615.78.08 and 620.70.06. It contains no SM120 runtime or RTX 50 support.

For the published benchmark, follow [the v0.1.4 instructions](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.4/NDX12_GPU_Benchmark/HOW_TO_RUN.md). The installer on this branch expects the candidate archive and starter below. Their v0.1.5 release download URLs are not available yet.

## Changes from v0.1.4

- The native-library preload guard rejects a matching pathname or inode, including aliases on btrfs. An inode collision on another filesystem also refuses conservatively. The loaded-image check retains btrfs support.
- A failed installer rollback reports the incomplete installation and the path of the preserved previous package instead of saying nothing changed.
- Workqueue CPU-time reports alone no longer stop a run because their function name contains `drm`. Records remain in the evidence window. Critical kernel priorities, NVIDIA-driver and integrity failures still stop the run.
- The separate Vulkan reference saves the child outcome and observed kernel records before propagating a health rejection. Known errors before submission close its observation descriptor and raise a typed failure. An uncertain submission retains its existing handling.
- A service that ended without its completion record is reported separately from an active-service timeout. Its execution outcome remains `UNCERTAIN`; no automatic stop or retry is added.
- The package retains the complete operational README, and packaging checks compare the exported desktop and Vulkan tools with both source snapshots.

The four runtime inventories were updated using existing compiled inputs. Native ELF files, shaders and the starter are unchanged. Existing licenses and third-party notices are retained.

## Validation scope

Final CPU checks passed: four focused runs of 89 test methods (SM86/SM89, normal and optimized Python), eight public-boundary methods against the packaged Vulkan tool, 36 installer unit tests in each Python mode, and 34 named installation cases across 35 user-namespace runs. New Vulkan tests model the external child or service manager; their pipe/parser and filesystem checks are real.

No GPU execution, live btrfs reproduction or host installation was performed for this candidate. Earlier GPU results do not qualify these package bytes. The earlier eight full CPU suites belong to predecessor source identities; they were not rerun for the final tool changes.

## Candidate files

Use the [installer from this branch](ndx12-install.py) only with the matching archive and starter. The source companion is for development and is not needed to run the benchmark. These identities describe prepared files, not a published release.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `ndx12-install.py` | 21654 | `26b7805d4f6ad45a5320554c0e41634106edaac3f1ae7ef808ca92f8a4607877` |
| `ndx12-native-benchmark-v21-615.78.08-620.70.06.tar.gz` | 2506060 | `eed38c254c8e8cc8310c8fc84fbca6081696f114aadcb63cc584cb2828b448a5` |
| `ndx12_start.py` | 10958 | `8cd0ca349f4535741ae8a673b3aa10de4a0b5f953c283543a453a850337aced5` |
| `ndx12-benchmark-v0.1.5-source.tar.gz` | 4199515 | `fc5d6a444af1c930c20ee21a8ed74d0d87e38344b67a85d6f6b572da5259a388` |
| `MANIFEST.sha256` inside the runtime archive | 135206 | `c6bd8d3575a63304783cb412bafa38d31f2de4eeedfc8d9f9e276fbd0e48c56d` |

The source companion contains both architecture snapshots, tests and retained shader/build inputs. It omits prebuilt development executables. The runtime archive has 933 manifest entries; the source companion has 669. Their manifests and exported source bytes were checked. Named privacy scans found no matches; this is not a universal privacy guarantee.
