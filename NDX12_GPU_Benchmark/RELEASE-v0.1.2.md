# Native DirectX 12 Experimental Benchmark For Linux — v0.1.2

This is a new release identity. It does not replace or retag v0.1.1.

Charts now show the release from the verified installation receipt and the operating system. Without a checked receipt they show `Release unknown`; an OS name containing a host or account name is withheld. The share bundle is named `share-results-v0.1.2.tar.gz`, or `share-results-release-unknown.tar.gz` when the installation identity cannot be verified.

The share bundle now also contains `ndx12-results/charts.html`, the charts page built from exactly the chart images in the same bundle (`charts/*.svg`). It runs no script and loads nothing from outside; a bundle without an exported chart has no page. Earlier releases wrote this page only next to the bundle.

Follow [How to run](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.2/NDX12_GPU_Benchmark/HOW_TO_RUN.md). Use the v0.1.2 installer with the exact archive and starter below. The archive retains its internal v21 r12 name and development-time v0.1.1 examples; those examples do not identify this released installation. The installer writes v0.1.2 into the receipt checked by the launcher.

## Artifacts

| File | SHA-256 | Bytes |
| --- | --- | ---: |
| `ndx12-native-benchmark-v21-615.78.08-620.70.06.tar.gz` | `e8073d51d834820e04907f4ab774686a988995a99e11bc381d509044c1f4bb80` | 2534378 |
| `ndx12_start.py` | `8cd0ca349f4535741ae8a673b3aa10de4a0b5f953c283543a453a850337aced5` | 10958 |
| `ndx12-benchmark-v0.1.2-source.tar.gz` | `daecf85cb6532e006a8a3f514e164b563213f57b8ac0f93378c0cb37a369c8e5` | 4186558 |
| `ndx12-install.py (repository file)` | `27505db672054f703039d950bbcb685048ac5d21d32fdcbbf4a940fe016fe45d` | 21163 |

The embedded MANIFEST.sha256 is `ea1df965833b44eb74e62dd3e08e9abc105336f85c13417de6c8007a4246a28e`. Checksums identify bytes; they do not prove GPU execution.

## Validation and limits

CPU results recorded for these exact runtime and installer bytes: 31 installer unit tests, 34 installer end-to-end cases in namespaces, 46 mutants plus an unchanged baseline, and eight suites (576 tests for each SM89 profile and 577 for each SM86 profile, normal and optimized Python). The share-bundle page was checked by tests that fail without the change, and by re-exporting two saved real runs (a complete RTX 4090 run and a stopped RTX 3090 run) on the CPU: each bundle held `charts.html` with its exported charts byte for byte, the correct COMPLETE or PARTIAL state, and no private value in a scan against each run's own identifiers. An installed v0.1.1 package is replaced by the same "does not verify, moved aside" path tested for v0.1.0; an end-to-end upgrade from v0.1.1 itself was not run. After the suites, one source test file changed (a synthetic GPU identifier and a stricter page-privacy test; it is not part of the runnable archive); its 42 tests were re-run for SM89 and SM86 with both driver runtimes, normal and optimized Python. These checks do not execute GPU workloads or authenticate real sudo.

**GPU NOT_RUN.** Older hardware results apply only to the revisions named in their reports. This release adds no performance, device-compatibility or new GPU-correctness claim. The separate experimental VRAM work is not included.

A pre-existing reporting limitation remains in direct command-line Vulkan auto mode: some non-executed probe states may be described incorrectly in the summary. The interactive launcher selects explicit on/off mode. This limitation is not a claim that Vulkan executed.

## Sources and licenses

The source companion contains the matching SM86/SM89 source snapshots, tests, shader sources and pinned CPU build recipes. Third-party notices and licenses are preserved unchanged. See [Source and licenses](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.2/NDX12_GPU_Benchmark/SOURCE_AND_LICENSES.md) and the companion README for historical build evidence and known build limitations. No fresh dependency/compiler rebuild is claimed for v0.1.2. The source snapshots omit the two prebuilt development executables `sm89/tools/vulkan_ref/ndx12_vulkan_ref` and `sm86/tools/vulkan_ref/ndx12_vulkan_ref`, which contained local build paths; their C++ source and build command remain, and the runnable archive carries its own checked copy.
