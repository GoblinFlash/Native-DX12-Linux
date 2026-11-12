# AGENTS.md — Native DX12 Linux

Instructions for AI coding agents and contributors preparing changes to this repository.

**Project owner and final decision-maker:** Andrew Kapica — GoblinFlash.

## Project scope

Native DX12 Linux is an **experimental native Linux Direct3D 12 subset**. It does not use Vulkan/VKD3D as a D3D12 runtime translation layer. Initial work focuses on NVIDIA RTX, followed by AMD Radeon and Intel; early Intel Iris Xe work remains part of the project.

A DXIL/SPIR-V conversion step does not by itself mean that Vulkan is used as the runtime. Do not claim full D3D12 compatibility, working games or general performance superiority without matching end-to-end evidence.

## Before making changes

1. Read the relevant source and documentation. Check existing Issues and pull requests before starting a duplicate task.
2. Keep one focused change per PR. Preserve unrelated edits, historical experiments, negative results and existing hardware-specific records.
3. Do not silently replace dependencies, source pins, test expectations, licensing notices or public benchmark data.
4. For broad architecture changes, new hardware support or significant refactors, open an Issue and agree on scope first.
5. Do not put private machine paths, credentials, raw logs, private agent conversations or unreleased evidence into public files.

## Using AI agents

AI assistance is welcome and should be disclosed. A human submitter remains responsible for understanding the change, verifying the result and answering review questions.

- Before staging, committing, pushing, creating a PR or changing branches, an agent must have its human operator's explicit authorization for the specific operation and target. Do not assume that a request to investigate or fix something grants publication rights.
- Do not push directly to upstream `main`, merge PRs, create releases or modify GitHub labels/issues without specific maintainer permission.
- Do not start paid cloud instances, run GPU experiments, install system packages or change hardware settings without explicit permission.
- Review AI-generated code for correctness, provenance, duplicated upstream code, licensing and security. An agent's assertion that tests passed is not test evidence.

## Submitting a pull request

1. Fork the repository or use a branch you are authorized to modify; open a PR against `main`. Use **Draft** while work or verification is incomplete.
2. Link the relevant Issue. Explain the problem, proposed behavior and exact scope. Avoid unrelated formatting or cleanup.
3. **Disclose AI assistance** in the PR description: which tools helped and whether they generated code, tests, analysis or documentation. No private prompts or chat transcripts are required.
4. Include real test commands, outputs or a concise summary with explicit **PASS / FAIL / NOT_RUN**. Distinguish CPU build/test checks from GPU execution.
5. List hardware, driver, OS, package/benchmark revision and evidence links for any hardware claim. Preserve failures, clock limitations, background load and other caveats.
6. Identify copied or adapted material and its original source/license. Include required attribution and notices; do not relicense third-party material as project-owned code.
7. Respond to review findings and update tests/evidence. If final code bytes change, the final review must cover those changed bytes.

**Suggested PR description:**

- **Purpose and scope:** what changed, why, and related Issue.
- **AI assistance:** tools used and the parts they helped with.
- **Changed files / behavior:** before and after, including limitations.
- **Verification:** commands actually run, PASS/FAIL/NOT_RUN, and relevant artifacts.
- **Hardware evidence:** exact GPU, driver, revision, submission/completion/readback where applicable; otherwise `GPU=NOT_RUN`.
- **Provenance / licenses:** original sources, adaptations and notices.
- **Open questions:** unresolved findings, risks and follow-up work.

## Evidence boundaries

- **Build PASS is not GPU PASS.** Compilation, CPU simulations, shader code generation and a successful GitHub workflow do not prove GPU execution.
- GPU claims require actual submission, synchronization/completion and checked output on the identified hardware. Do not promote a reported archive status to independent GPU qualification.
- Preserve timing units and clock qualification. Native GPU ticks and Vulkan nanoseconds are not directly comparable without a qualified conversion model. State memory backing (e.g. SYSMEM/VRAM) only when supported by the specific artifact.
- Keep NVIDIA, AMD and Intel findings separated by hardware lane. Do not generalize one GPU's results to other models or drivers.
- Benchmark submissions from external testers should use the [Benchmark Results Issue form](https://github.com/GoblinFlash/Native-DX12-Linux/issues/new?template=benchmark_results.yml). Intake labels and generated Draft PRs do **not** mean that a result is accepted.

For CPU build and test commands, see [Build and CPU validation](docs/validation.md) and [Tests](tests/README.md). Run only the checks relevant to the change and report missing prerequisites honestly. Do not describe mocked hardware tests as real GPU runs.

## Review, licensing and acceptance

- Every code file intended for public release must receive a **completed CodeRabbit review of its final bytes**. Maintainers coordinate that review; skipped, pending or partial checks are not PASS. Other reviewers and CI are useful but do not replace this requirement.
- The maintainer checks provenance, third-party licensing, privacy, tests and performance claims before accepting a PR.
- GPL-3.0-or-later applies to approved project-owned material; third-party licenses remain intact. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
- **Only Andrew Kapica — GoblinFlash authorizes acceptance, merging and release.** A passing test, review approval or AI recommendation does not grant that authority.

Keep public technical documentation in English, with concrete evidence and clear limits.
