# Source and licenses — v0.1.0

Project-owned material is licensed under **GPL-3.0-or-later**, with attribution **Andrew Kapica — GoblinFlash**. Third-party originals and adapted portions retain their incoming licenses and notices. The project license does not relicense those portions.

Download the [source companion](https://github.com/GoblinFlash/Native-DX12-Linux/releases/download/v0.1.0/ndx12-benchmark-v0.1.0-source.tar.gz) alongside the [runnable release](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.0). Both are available from the same release page without a separate request.

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

All 20 D4/K/WaveForm architecture/program variants were rebuilt from HLSL on the CPU for this source delivery. Their 60 code, QMD and shader-info output files matched the tested runtime archive. This does not claim a fresh rebuild of every dependency or byte-identical reproduction of the CPU executables. The companion README describes build prerequisites and known source-build limitations.

The custom compiler adapters reuse earlier project units and consult upstream APIs and implementations. This is not a clean-room claim. Original attributions are retained; no blanket claim of original authorship is made for third-party material.

The runtime archive is unchanged from the tested v21 r9 package. Its embedded development metadata describes the status at build time; the release page and companion README describe the final source delivery and hardware validation scope.
