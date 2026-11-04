# Linux build container — experimental

This is a build environment, not a GPU runtime image. Linux x86-64 users can
retain their host distribution. The image contains Ubuntu 26.04 userspace,
compilers and development packages. Sources and dependency caches are mounted
separately. No GPU, host driver, device directory or container socket is mounted.

**NVIDIA hardware scope: RTX 4090 (Ada SM89), recorded driver 615.78.08 only.**
RTX 3090 (Ampere SM86) and other GPUs are unsupported and unvalidated. Historical
GPU results apply only to their recorded artifacts. This container does not run
hardware tests, and a successful build does not qualify the rebuilt artifacts.
The runtime requires PCI 10de:2684 in the plan before device effects, then checks
actual CARD_INFO against that plan before device binding. Other devices are
refused; this build container does not authorize GPU execution.
Intel and AMD retain the limited scope in the root README; AMD has CPU adapter
checks, not a qualified full frontend/device execution path.

## Image and inputs

The Containerfile pins the official Ubuntu amd64 image manifest by SHA-256 and
uses the Ubuntu archive snapshot 20261102T000000Z. A pinned ca-certificates .deb
bootstraps TLS; its SHA was checked against a Packages index whose SHA appears
in Ubuntu-signed InRelease, verified using the Ubuntu archive keyring from the
base image. Repository signature checks and TLS verification remain enabled. The immutable
historical snapshot uses Check-Valid-Until: no so that its dated signed metadata
can be used after expiry; this does not disable signature/hash verification.
APT uses HTTPS directly, and all three signed InRelease files are independently
pinned in container/snapshot-inrelease.sha256 and checked before installation.
A different signed snapshot or replayed metadata must fail the hash check.
Package names come from deps/apt-packages.txt. Its observed version column is
not an installation constraint; snapshot selection fixes the available archive.
Actual installed versions are recorded in /opt/ndx12/installed-packages.tsv.
Source and FFX output pins remain unchanged; mismatch must fail, never re-pin.

Build the toolchain image explicitly (network is required here):

```sh
python3 -I -B container/run.py image-build --engine podman
# Docker is also accepted with --engine docker.
```

After image-build, obtain the local immutable image ID with
`podman image inspect --format '{{.Id}}' native-dx12-toolchain:experimental`
(or the equivalent docker command). The launcher accepts `sha256:IMAGE_ID` for
a local image, or `repository@sha256:digest` for a separately obtained image,
with --pull=never. No push/publication is required to use a local image. There
is currently no published project image. Do not substitute the Ubuntu base
digest for the completed toolchain image identity.

```sh
mkdir -p /absolute/cache /absolute/empty-output
python3 -I -B container/run.py fetch --engine podman \
  --image REGISTRY/TOOLCHAIN@sha256:DIGEST --cache /absolute/cache
python3 -I -B container/run.py build --engine podman \
  --image REGISTRY/TOOLCHAIN@sha256:DIGEST --cache /absolute/cache \
  --output /absolute/empty-output --jobs 2
```

Replace the uppercase placeholders with an actual verified image identity.
Fetch is network-enabled and writes only the mounted cache. Build uses
--network=none, a read-only cache/source/image, dropped capabilities, the caller's
UID/GID and a fresh writable output. It invokes unchanged build.py **without**
--offline: nested unshare may be denied by OCI policies. Thus deps.json records
`offline: false` and `network_namespace: host`; those fields describe the inner
recipe, not the outer container network namespace. Retain the launch argv and
runtime result when making an externally network-isolated claim. Do not add
--privileged, GPU mounts, seccomp=unconfined or host-network fallback to bypass a
failure. SELinux and rootless filesystem policies require separate host testing;
the launcher does not relabel host data or change system policies.

## CPU launcher tests

An explicit test-output directory is required, as with the other package tests:

```sh
mkdir -p /absolute/test-output
NDX12_TEST_ROOT=/absolute/test-output python3 -I -B container/test_launcher.py
NDX12_TEST_ROOT=/absolute/test-output python3 -I -B -O container/test_launcher.py
```

These tests construct command arguments and exercise refusal paths. They do not
invoke an OCI engine or claim an image build.

## Current validation boundary

The launcher has CPU argument/negative tests in normal and optimized Python.
An earlier actual Podman image build and all-target CPU project build were
recorded for source lock
d9276dcef7c79e3e465d4f2c420f5b525d37ed1e7bbc579c164b3570484c1c85.
That build used a verified local dependency cache. It preceded six later
runtime-input/template changes: 172 of 178 runtime input files match the later
set. The subsequent production runtime stage passed CPU admission using existing
compiler artifacts; it did not repeat the full compiler/dependency build.

In a later validation on 2026-11-03, one public-endpoint fetch into a fresh
cache exited 0, followed by complete offline manifest verification: 13/13
entries passed. The same cache was reused and verified again for the build
below, without another fetch.

The immediate source predecessor of this documentation-only revision then
passed one clean all-target CPU build in an existing immutable Podman toolchain
image: `--targets intel,rtx,amd`, `--jobs 2`, outer `--network=none`, no devices,
exit 0 in 516 seconds. All 18 dependency commands exited 0. Of 37 project
commands, 35 exited 0 and two expected refusals exited 1 with
`RTX_REJECT:DIRECT_PROFILE`. Installed runtime verification passed normally
and with `-O`: 177 files, 81 runtime pins, 61 packet pins and 43 modules.
AMD retains `full_frontend_link=false`; GPU execution was `NOT_RUN`.

This documentation-only revision and its updated source lock succeed those
built bytes; no new clean build of this revision was run. Code, dependencies
and runtime templates are unchanged here. The result does not provision a
clean host or transfer the recorded GPU qualification to rebuilt artifacts.

A bwrap rootfs run is separate from OCI engine execution. Recorded Podman results
do not establish Docker operation, all host
distributions, or qualification of rebuilt GPU artifacts.
A stable image digest does not guarantee bit-identical outputs for every source
path/host; package-path reproducibility remains a separate tracked limitation.
Public image redistribution requires review of included third-party licences,
not just the project's source LICENSE/NOTICE. Publication is not automatic.
