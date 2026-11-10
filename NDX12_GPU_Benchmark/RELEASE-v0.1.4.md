# Native DirectX 12 Experimental Benchmark For Linux — v0.1.4

This is a new release identity. It does not replace or retag v0.1.3.

v0.1.4 admits the **whole GeForce RTX 40 series** on the SM89 runtime and fixes a start-up check that stopped the benchmark on btrfs subvolumes.

## RTX 40 series

v0.1.4 admits all 25 RTX 40 PCI device IDs of the NVIDIA 615.78.08 and 620.70.06 supported-chips lists. The RTX 4090 and the RTX 4060 family were already admitted. New in v0.1.4:

| GPU | PCI device IDs |
| --- | --- |
| RTX 4090 D | 2685 |
| RTX 4080 SUPER | 2702 |
| RTX 4080 | 2704 |
| RTX 4070 Ti SUPER | 2689, 2705 |
| RTX 4070 Ti | 2782 |
| RTX 4070 SUPER | 2783 |
| RTX 4070 | 2709, 2786 |
| RTX 4090 Laptop GPU | 2717, 2757 |
| RTX 4080 Laptop GPU | 27A0, 27E0 |
| RTX 4070 Laptop GPU | 2820, 2860 |
| RTX 4050 Laptop GPU | 28A1, 28E1 |

**Apart from the RTX 4090, no RTX 40 card has completed this benchmark.** Admission by the GPU table is not a hardware test. The SM89 shaders were compiled for and run on an RTX 4090; running on other Ada chips is expected but not verified. Results from these cards are especially welcome.

## btrfs fix

An RTX 4060 run of v0.1.3 stopped with `HELD cause: NATIVE_LOADED_IMAGE` before any GPU work. After loading its native library, the runtime compared the device number in `/proc/self/maps` with the one from `stat()`. On a btrfs subvolume these two differ: `stat()` reports the subvolume's device, `/proc/self/maps` the filesystem's. This was measured on the tester's host (btrfs root, `stat()` 00:26, maps 00:25, the same inode).

v0.1.4 no longer compares the device number. The check still requires the exact library path, the same inode and an executable mapping. A new CPU test covers this, including the btrfs case. The GPU of that host has not been tested yet.

If a v0.1.3 run stopped this way, restart the computer before installing v0.1.4. The stopped run leaves its benchmark worker held, and restarting releases it.

## What changed

All four runtimes were rebuilt. Files changed in each:
- `native_words_binding.py`;
- in the two SM89 runtimes, also `gpu_identity.py`;
- the pinned entries of these files in `runtime_inputs.json`.

All shaders and the native library `libndxwords.so` are byte-identical to v0.1.3. The launcher's supported-GPU message and the package revision (v21 r14) changed; everything else in the tools is unchanged.

Follow [How to run](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.4/NDX12_GPU_Benchmark/HOW_TO_RUN.md). Use the v0.1.4 installer with the exact archive and starter below. The installer writes v0.1.4 into the receipt checked by the launcher. The share bundle is named `share-results-v0.1.4.tar.gz`. Without a checked receipt it is named `share-results-release-unknown.tar.gz`, as before.

## Artifacts

| File | SHA-256 | Bytes |
| --- | --- | ---: |
| `ndx12-native-benchmark-v21-615.78.08-620.70.06.tar.gz` | `a4d707dd50fa9fa22d554732d4e97dfbb54c5ab4ce6fee225c7d554afd1f399a` | 2535982 |
| `ndx12_start.py` | `8cd0ca349f4535741ae8a673b3aa10de4a0b5f953c283543a453a850337aced5` | 10958 |
| `ndx12-benchmark-v0.1.4-source.tar.gz` | `5a90d8b8ecb639af8f5e7d2a0f4af7df54b5fe8c0ad00476c98df0f6f06de70a` | 4190313 |
| `ndx12-install.py (repository file)` | `2a0d6f0daa0948d4de84f29b066f0a7f3cd4f281d567b349ccdade5748010dd3` | 21200 |

The embedded MANIFEST.sha256 is `b00bf06c49c64fcd9ae87e12c208cad14a99d4f251b2c44aaef3246e9ac07c5e`. Checksums identify bytes; they do not prove GPU execution.

## Validation and limits

These CPU results were recorded for these exact bytes:
- **Suites:** eight suites of 582 tests each (the 577 of v0.1.3 and five new loaded-library tests), covering SM89 and SM86, both driver runtimes, normal and optimized Python.
- **Installer:** 31 unit tests and 34 end-to-end cases in namespaces.
- **Identity test:** it pins the 25 RTX 40 IDs taken from both supported-chips lists. IDs in neither list are refused.
- **Runtime selection:** checked on the archive's own four identity modules. Each RTX 40 ID is accepted only by the SM89 runtimes, while the RTX 30 series selects SM86 as before. The exception is the RTX 3050 A Laptop GPU, which selects SM89.
- **Loaded-library test:** it fails on the v0.1.3 module only in the btrfs case and passes on the v0.1.4 one. The tester's recorded `/proc/self/maps` rows are refused by the v0.1.3 check and accepted by the v0.1.4 one.
- **Independent review:** a read-only review checked the archive, installer, source companion and these documents. Two documentation findings were fixed.

An installed v0.1.3 package is replaced through the same "does not verify, moved aside" path tested for v0.1.0. An end-to-end upgrade from v0.1.3 itself was not run. These checks do not execute GPU workloads or authenticate real sudo.

**GPU NOT_RUN.** Older hardware results apply only to the revisions named in their reports. This release adds no performance, device-compatibility or new GPU-correctness claim. The stored clock presets remain for the RTX 4090 and RTX 3090 only. On other GPUs, keep the current clocks or enter them manually; a preset that the GPU does not support is refused before anything changes.

A pre-existing reporting limitation remains in direct command-line Vulkan auto mode: some non-executed probe states may be described incorrectly in the summary. The interactive launcher selects explicit on/off mode. This limitation is not a claim that Vulkan executed.

## Sources and licenses

The source companion contains the matching SM86/SM89 source snapshots, tests, shader sources and pinned CPU build recipes. Third-party notices and licenses are preserved unchanged.

See [Source and licenses](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.4/NDX12_GPU_Benchmark/SOURCE_AND_LICENSES.md) and the companion README for historical build evidence and known build limitations.

The four runtimes were rebuilt for v0.1.4 from the included sources, with the same pinned container image and recipe as v0.1.3. No fresh rebuild of the dependencies or compilers is claimed.

The source snapshots omit the two prebuilt development executables `sm89/tools/vulkan_ref/ndx12_vulkan_ref` and `sm86/tools/vulkan_ref/ndx12_vulkan_ref`, which contained local build paths. Their C++ source and build command remain, and the runnable archive carries its own checked copy.
