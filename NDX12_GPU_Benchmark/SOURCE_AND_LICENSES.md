# Source and licenses — v0.1.4

Project-owned material is licensed under **GPL-3.0-or-later**, with attribution **Andrew Kapica — GoblinFlash**. Third-party originals and adapted portions retain their incoming licenses and notices. The project license does not relicense those portions.

Download the [source companion](https://github.com/GoblinFlash/Native-DX12-Linux/releases/download/v0.1.4/ndx12-benchmark-v0.1.4-source.tar.gz) alongside the [runnable release](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.4). Both are available from the same release page without a separate request.

| Component | Source / notice location in the companion |
| --- | --- |
| Native runtime, launcher and build tools | `sm86/`, `sm89/`; project `LICENSE` and `NOTICE` |
| Native CPU word helper | Runtime helper C sources within both snapshots |
| Separate Vulkan reference | `sm89/tools/vulkan_ref/ndx12_vulkan_ref.cpp` |
| D4, K and WaveForm shaders | `shader-build/hlsl/`, exact adapter snapshots in `shader-build/compilers/`, pinned `recipes.json` and `build.py` |
| Microsoft MiniEngine histogram adaptation | Retained upstream license, attribution and adaptation patch; component section in `NOTICE` |
| AMD FidelityFX ParallelSort adaptation | `shaders/parallel_sort/` in each snapshot; AMD MIT notice in `NOTICE` |
| Microsoft DirectX declaration-derived material | Component attribution and MIT terms in `NOTICE` |
| Mesa integration patch context and NVIDIA declaration inputs | Per-component source pins and retained notices in `NOTICE` and the snapshots |
| GCC runtime used by the Vulkan reference | `third-party/GCC-15-COPYRIGHT.txt`, including the GCC Runtime Library Exception |
| External build dependencies | Revision/file pins and acquisition scripts in each snapshot's `deps/`; incoming licenses accompany the acquired source |

The runtime archive contains a native CPU helper and a separate Vulkan reference executable. It does not bundle Mesa or LLVM compiler libraries. The installed NVIDIA driver and Vulkan loader are external requirements. Precompiled GPU shaders are accompanied by their sources and build recipes in the source companion.

The 20-variant D4/K/WaveForm HLSL rebuild and 60-file code/QMD/shader-info match were recorded for v0.1.0. The shader recipes, inputs and runtime shader outputs are retained unchanged here; that build was not repeated for v0.1.4. This does not claim a fresh rebuild of every dependency or byte-identical reproduction of the CPU executables. The companion README describes build prerequisites and known source-build limitations.

The custom compiler adapters reuse earlier project units and consult upstream APIs and implementations. This is not a clean-room claim. Original attributions are retained; no blanket claim of original authorship is made for third-party material.

The v0.1.4 runtime archive is the v21 r14 package identified in the release notes. All four runtimes were rebuilt with the loaded-library check fix in `backends/nvidia/runtime/native_words_binding.py`, and the two SM89 runtimes also with the whole RTX 40 series in `backends/nvidia/runtime/gpu_identity.py` (and their pinned entries in `runtime_inputs.json`). Their shaders and native library are byte-identical to v0.1.3. No new GPU execution was performed for v0.1.4. Embedded development metadata and version examples are historical; the v0.1.4 installer supplies the released identity through its checked receipt. The source snapshots omit the two prebuilt development executables `sm89/tools/vulkan_ref/ndx12_vulkan_ref` and `sm86/tools/vulkan_ref/ndx12_vulkan_ref`, which contained local build paths; their C++ source and the build command in the companion README remain.
