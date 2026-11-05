# Build and CPU validation

This page explains how the source package is built and checked on the CPU, and what those checks do and do not establish. GPU experiment measurements and their original charts are organized separately:

- [NVIDIA RTX 4090 — measured experiments and execution checks](../Experiment%20Results/NVIDIA/README.md)
- [AMD — CPU-side adapter checks](../Experiment%20Results/AMD/README.md)
- [Intel — early Iris Xe development and test programs](../Experiment%20Results/Intel/README.md)

The [`tests/` folder](../tests/README.md) contains test code and sample workloads, not the experiment
results. The NVIDIA, AMD and Intel results are under `Experiment Results/`.

## CPU build

The entrypoint is build.py. See [dependencies](../deps/README.md) and
[the build container](../container/README.md) for prerequisites, pinned source
acquisition and output ownership. The tools do not install system packages.
Build outputs, dependency caches and source directories must be separate.

Run these commands from the source root, after explicitly installing prerequisites.
The first command accesses the network and writes a dependency cache. The second
uses a fresh output directory and runs CPU compilation/admission checks only:

```sh
python3 -I -B deps/prepare_deps.py fetch --cache /absolute/ndx12-cache
python3 -I -B build.py --build-root /absolute/fresh-ndx12-build \
  --cache /absolute/ndx12-cache --jobs 2 --offline --targets intel,rtx,amd
```

The cache must be outside the source and build roots. The build root must be fresh.
Jobs are limited to four; two are the example setting. --offline uses a network
namespace and refuses missing inputs. For OCI execution the launcher provides
--network=none and does not request nested unshare; retain its launch receipt.
A successful build writes project/build-results.json, but does not launch GPU work.

An earlier real Podman build compiled all three selected CPU targets from a
verified local dependency cache. That receipt predates six runtime-input/template
changes: 172 of 178 input files match the later runtime input set. The later
production runtime stage passed CPU verification using existing pinned compiler
outputs; it did not repeat the full dependency/compiler build.

In a later validation on 2026-11-03, one public-endpoint fetch into a fresh
cache exited 0, followed by complete offline manifest verification: 13/13
entries passed. The same cache was reused and verified again for the build
below, without another fetch.

A recorded source revision then
passed one clean all-target CPU build in an existing immutable Podman toolchain
image: `--targets intel,rtx,amd`, `--jobs 2`, outer `--network=none`, no devices,
exit 0 in 516 seconds. All 18 dependency commands exited 0. Of 37 project
commands, 35 exited 0 and two expected refusals exited 1 with
`RTX_REJECT:DIRECT_PROFILE`. Installed runtime verification passed normally
and with `-O`: 177 files, 81 runtime pins, 61 packet pins and 43 modules.
AMD retains `full_frontend_link=false`; GPU execution was `NOT_RUN`.

The current documentation and source lock succeed those built bytes; no clean
rebuild of the current source revision is claimed here. The historical result does not provision a
clean host or transfer the recorded GPU qualification to rebuilt artifacts.
Bit-identical complete outputs across hosts or build roots are not promised.

## CPU regression checks

Tests require an explicit existing output directory outside the source root.
They create retained per-run subdirectories. Execute normal and optimized Python:

```sh
NDX12_TEST_ROOT=/absolute/ndx12-test-output python3 -I -B tests/test_build.py
NDX12_TEST_ROOT=/absolute/ndx12-test-output python3 -I -B -O tests/test_build.py
NDX12_TEST_ROOT=/absolute/ndx12-test-output python3 -I -B tests/test_runtime_guard.py
NDX12_TEST_ROOT=/absolute/ndx12-test-output python3 -I -B -O tests/test_runtime_guard.py
```

After a completed build, relocation/profile tests consume its runtime-inputs:

```sh
NDX12_TEST_ROOT=/absolute/ndx12-test-output NDX12_RUNTIME_INPUTS=/absolute/fresh-ndx12-build/project/runtime-inputs python3 -I -B tests/test_runtime_release.py
NDX12_TEST_ROOT=/absolute/ndx12-test-output NDX12_RUNTIME_INPUTS=/absolute/fresh-ndx12-build/project/runtime-inputs python3 -I -B -O tests/test_runtime_release.py
```

Recorded tests on the pinned source ran 20 build-test methods, 14 runtime-release
methods and one guard method containing 27 source-defined subcases per Python
mode. A subcase count is distinct from unittest method count. Runtime admission
checked 177 installed files, 81 runtime pins, 61 packet pins and 43 loaded modules.
Device access and native libraries were blocked in those admission checks;
CARD_INFO profile checks were mocked. These are CPU results, not device execution.

The loader retains logical @PACKAGE@/, @HEADERS@/ and @ARTIFACTS@/ locators.
It checks traversal/symlink boundaries and reads metadata/content from the same
opened descriptor. /proc/self/fd is required. This is a trusted-interpreter
integrity boundary, not an OS sandbox for arbitrary native code or existing FDs.

## GPU use and current limits

There is currently no documented public plan generator or end-to-end NVIDIA
benchmark runner in this source export. `native_bootstrap.py` consumes an explicitly
pinned host/workload plan; a copied development plan is not a portable example.
The [recorded NVIDIA measurements](../Experiment%20Results/NVIDIA/measurement-details.md)
therefore cannot be replayed as a public one-command demo yet.
The build container exposes no GPU devices and never enables execution.

No public runtime split or Intel/AMD removal is implied. Affine and ParallelSort
share admission and dependencies. CPU preparation, a saved receipt, code review
and fresh hardware execution are separate evidence levels.

## Licensing

Andrew Kapica project-owned portions: Copyright (C) 2026 Andrew Kapica,
GPL-3.0-or-later; see [LICENSE](../LICENSE). Third-party originals, adaptations and declaration
material retain their applicable original terms and notices; see [NOTICE](../NOTICE) and
component licence files. This is not a blanket GPL relicensing of dependencies
or a clean-room claim.

The source distribution excludes dependency trees, build outputs, toolchain/OCI
images, credentials, private sessions and raw development evidence.
