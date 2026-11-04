# Pinned dependencies for Native DX12 Linux (Ubuntu 26.04)

This directory acquires and builds the third-party dependencies of the package.
Nothing here installs system packages or writes outside the directories you
pass explicitly.

## 1. System packages

Install the packages listed in `apt-packages.txt` (one `apt-get install` line is
at the top of that file). Ubuntu 26.04 LTS on amd64 is the only documented host.

## 2. Acquire sources (network)

```sh
python3 -I deps/prepare_deps.py fetch --cache "$HOME/ndx12-cache"
```

`deps.lock.json` pins every input:

| Source | Pin | Used by |
| --- | --- | --- |
| Mesa | git `d1e369d8a63eb82ba277e4e25d35982ce2760204` + 6 Rust crates from its wraps | Intel, RTX, AMD |
| dxil-spirv (LLVMBC) | git `8434b0639fb2a48ce13aac08a420ecce5d23df0e` + 5 pinned submodules | all |
| DirectX-Headers | git `ee479f0bd5f7b884f202bcf0c3f076cc050dd256` (v1.619.5) | Intel |
| DXC | release v1.9.2609 archive, SHA-256 `96faadc7…aa39a1` | all |
| libdrm | 2.4.133 archive, SHA-256 `fc68f9d0…77b4f5` | AMD |
| NVIDIA open-gpu-kernel-modules | 73 headers at tag 615.78.08, each by SHA-256 | RTX |
| FidelityFX-ParallelSort | `FFX_ParallelSort.h` at `0c539948c8d196ae338d91efbc8ca495f1ea0d1d` | RTX |

Each acquired tree must equal its complete file manifest in `manifests/` (paths,
sizes, SHA-256, symlinks). A difference fails the fetch; there is no fallback to
another revision. Git sources are fetched by commit, not by branch or tag.

Mirrors are allowed only through explicit, verified options:
`--git-mirror NAME[:SUBMODULE]=REPO`, `--file-override FILE` (matched by SHA-256)
and `--tree-override NAME=DIR` (accepted only if the full manifest matches).

## 3. Build dependencies

```sh
python3 -I deps/prepare_deps.py build --package-root "$PWD" \
    --cache "$HOME/ndx12-cache" --build-root "$HOME/ndx12-build/deps" \
    --jobs 2 --offline --targets intel,rtx,amd
```

- `--jobs` is limited to 1..4.
- `--offline` runs every build command in a new network namespace (`unshare -rn`).
- `--extra-path DIR` adds an explicit tool directory, for example an unpacked
  official `cbindgen` package, ahead of `/usr/bin`.

The build:

- copies verified trees into the build root;
- builds dxil-spirv;
- builds Mesa for RTX (NAK compiler libraries), for AMD (RadeonSI, with a private
  libdrm 2.4.133 prefix) and for Intel (Iris with the package's two Mesa patches
  and six frontend targets);
- reproduces the FFX base inputs. `ordinary.spv` and the five base adapter
  outputs must match their pinned SHA-256 values;
- avoids build-root paths in outputs: every Mesa configuration gets a Meson native
  file (`meson-native-reproducible.ini`) whose `rust_args` map the build root to
  `@NDX12_BUILD@`, and dxil-spirv is built with its install RPATH set to
  `$ORIGIN` (`CMAKE_BUILD_WITH_INSTALL_RPATH=ON`), so its ELF files carry exactly
  `$ORIGIN` without CMake's padding entry; `libdxil-spirv-c-shared` therefore also
  gets RUNPATH `$ORIGIN`. Paths outside the build root, such as the package root,
  are not mapped.
  A build root containing `'`, `\` or a newline is refused. Before the Intel
  build, the hash-verified `libdxil-spirv-c-shared` is copied under its ELF SONAME
  into `mesa-intel-build/src/gallium/`, beside the `$ORIGIN`-linked targets.

The result is `deps.json` (schema `ndx12.ubuntu-deps-result.v1`) in the build root.
It records absolute paths, the tool identities, the installed package versions
and every command. The package build reads this file.

## Limits

- This builds dependencies on the CPU only; it executes no GPU work.
- Pins prove identity, not licensing. See the package `NOTICE` for licences.
