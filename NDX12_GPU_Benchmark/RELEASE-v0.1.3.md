# Native DirectX 12 Experimental Benchmark For Linux — v0.1.3

This is a new release identity. It does not replace or retag v0.1.2.

v0.1.3 admits the **RTX 4060 family** on the SM89 runtime:

| GPU | PCI device IDs |
| --- | --- |
| RTX 4060 | 2808, 2882 |
| RTX 4060 Ti | 2788, 2803, 2805 |
| RTX 4060 Laptop GPU | 28A0, 28E0 |

The IDs and names are the rows of the NVIDIA 615.78.08 and 620.70.06 supported-chips lists. **No RTX 4060 family card has run this benchmark yet.** Admission by the GPU table is not a hardware test. The SM89 shaders were compiled for and run on an RTX 4090; running on these smaller Ada chips is expected but not verified. Results from these cards are especially welcome.

Only the two SM89 runtimes were rebuilt. Two files changed in each:
- `gpu_identity.py`;
- its pinned entry in `runtime_inputs.json`.

All shaders, the native library and the two SM86 runtimes (RTX 30 series) are byte-identical to v0.1.2. The launcher's supported-GPU message and the package revision (v21 r13) changed; everything else in the tools is unchanged.

Follow [How to run](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.3/NDX12_GPU_Benchmark/HOW_TO_RUN.md). Use the v0.1.3 installer with the exact archive and starter below. The installer writes v0.1.3 into the receipt checked by the launcher. The share bundle is named `share-results-v0.1.3.tar.gz`. Without a checked receipt it is named `share-results-release-unknown.tar.gz`, as in v0.1.2.

## Artifacts

| File | SHA-256 | Bytes |
| --- | --- | ---: |
| `ndx12-native-benchmark-v21-615.78.08-620.70.06.tar.gz` | `6fbf42ac493f70cff557cd1b5432c8b359ca0c83ad48de935bedc679d91d4912` | 2535709 |
| `ndx12_start.py` | `8cd0ca349f4535741ae8a673b3aa10de4a0b5f953c283543a453a850337aced5` | 10958 |
| `ndx12-benchmark-v0.1.3-source.tar.gz` | `bddbbe8e03667d8d7a04b9956f11ff6bf55d018998dfd684251a21fcc9952acb` | 4187366 |
| `ndx12-install.py (repository file)` | `2c2f9a8cb70299a779cf6b48616cbc6f1563949642e85a500bbbd7ee10e864c2` | 21186 |

The embedded MANIFEST.sha256 is `883283b08b21c02babab96039aea717b18842cae5821f3de56b90d1384d4db03`. Checksums identify bytes; they do not prove GPU execution.

## Validation and limits

These CPU results were recorded for these exact bytes:
- **Suites:** eight suites of 577 tests each, covering SM89 and SM86, both driver runtimes, normal and optimized Python. The SM89 runtimes were rebuilt for this release; the SM86 runtimes are the v0.1.2 bytes.
- **Installer:** 31 unit tests and 34 end-to-end cases in namespaces.
- **Identity test:** it fails on the v0.1.2 module and passes on the v0.1.3 one.
- **Runtime selection:** checked on the archive's own four identity modules. Each RTX 4060 family ID is accepted only by the SM89 runtimes, while the RTX 4090 and RTX 30 series select their runtimes as before.
- **Independent reviews:** two read-only reviews passed. Two documentation findings were fixed.

An installed v0.1.2 package is replaced through the same "does not verify, moved aside" path tested for v0.1.0. An end-to-end upgrade from v0.1.2 itself was not run. These checks do not execute GPU workloads or authenticate real sudo.

**GPU NOT_RUN.** Older hardware results apply only to the revisions named in their reports. This release adds no performance, device-compatibility or new GPU-correctness claim. The stored clock presets remain for the RTX 4090 and RTX 3090 only. On other GPUs, keep the current clocks or enter them manually; a preset that the GPU does not support is refused before anything changes.

A pre-existing reporting limitation remains in direct command-line Vulkan auto mode: some non-executed probe states may be described incorrectly in the summary. The interactive launcher selects explicit on/off mode. This limitation is not a claim that Vulkan executed.

## Sources and licenses

The source companion contains the matching SM86/SM89 source snapshots, tests, shader sources and pinned CPU build recipes. Third-party notices and licenses are preserved unchanged.

See [Source and licenses](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.3/NDX12_GPU_Benchmark/SOURCE_AND_LICENSES.md) and the companion README for historical build evidence and known build limitations.

The two SM89 runtimes were rebuilt for v0.1.3 from the included sources, with the same pinned container image and recipe as v0.1.2. No fresh rebuild of the dependencies or compilers is claimed.

The source snapshots omit the two prebuilt development executables `sm89/tools/vulkan_ref/ndx12_vulkan_ref` and `sm86/tools/vulkan_ref/ndx12_vulkan_ref`, which contained local build paths. Their C++ source and build command remain, and the runnable archive carries its own checked copy.
