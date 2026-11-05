# Tests

This folder contains test programs, checks and sample workloads for Native DX12 Linux. **It is not a collection of GPU benchmark results.**

For measured experiments and recorded results, see [Experiment Results](../Experiment%20Results/README.md).

## What is in this folder?

| File or folder | What it checks | Current evidence boundary |
| --- | --- | --- |
| [`test_build.py`](test_build.py) | Source integrity, build inputs, dependency caches and expected build failures. | CPU-only tests; no GPU work. |
| [`test_runtime_guard.py`](test_runtime_guard.py) | How the runtime verifier responds to allowed and rejected operations. | CPU-only tests in separate processes; not a general security sandbox. |
| [`test_runtime_release.py`](test_runtime_release.py) | Installed runtime files, relocation, target selection and hardware-profile rejection. | CPU-only checks using controlled inputs; no graphics card is accessed. |
| [`amd/`](amd/) | RadeonSI adapter checks and sample HLSL shaders. | The adapter test uses CPU doubles and explicitly reports `GPU=NOT_RUN`. |
| [`intel/`](intel/) | D3D12 compute and graphics test programs, plus Gallium/Iris probes. | Source programs for specific workloads; their presence does not prove successful GPU execution in this release. |
| [`third_party/miniengine/`](third_party/miniengine/) | Original and adapted MiniEngine histogram shader, adaptation patch and licensing records. | A third-party test component, not proof of a completed GPU benchmark. |

The Intel samples cover compute calculations, triangle rendering, textured drawing and indexed drawing with depth testing. The Gallium probes examine selected driver operations.

## Running the Python CPU checks

Run these commands from the repository root on Linux with the project prerequisites available. Test output must go to a writable directory **outside** the source tree; the scripts keep their per-run evidence directories.

```sh
mkdir -p /tmp/ndx12-test-output
NDX12_TEST_ROOT=/tmp/ndx12-test-output python3 -I -B tests/test_build.py
NDX12_TEST_ROOT=/tmp/ndx12-test-output python3 -I -B tests/test_runtime_guard.py
```

`test_runtime_release.py` additionally requires the `project/runtime-inputs` directory from a completed build:

```sh
NDX12_TEST_ROOT=/tmp/ndx12-test-output \
NDX12_RUNTIME_INPUTS=/path/to/build/project/runtime-inputs \
python3 -I -B tests/test_runtime_release.py
```

Replace `/path/to/build` with the actual external build directory. For prerequisites, the full build procedure and the optional Python `-O` checks, see [Build and CPU validation](../docs/validation.md) and the [container guide](../container/README.md).

## GPU tests and results

Passing these CPU checks does not demonstrate game compatibility or a GPU performance improvement. The recorded [NVIDIA RTX 4090 results](../Experiment%20Results/NVIDIA/README.md) are documented separately. A simpler public GPU benchmark runner is still in development.

Third-party files retain their own terms. See [MiniEngine notices](third_party/miniengine/NOTICE.md) and its upstream license.
