# Community benchmark results

Community submissions are collected as public [Benchmark Results issues](https://github.com/GoblinFlash/Native-DX12-Linux/issues?q=is%3Aissue+label%3Abenchmark%3Asubmission). A GitHub Actions workflow adds a GPU-model label for supported exact model names. A label is **categorization only**, not a correctness or performance endorsement.

## Curated GPU folders

- [NVIDIA RTX 4090](NVIDIA/RTX_4090/README.md)
- [NVIDIA RTX 3090](NVIDIA/RTX_3090/README.md) — issue #5, clock qualification unavailable
- [NVIDIA RTX 3060 Ti](NVIDIA/RTX_3060_Ti/README.md) — issue #3, background GPU contention disclosed
- [NVIDIA RTX 3060](NVIDIA/RTX_3060/README.md) — issue #4 on hold: submitted model disagrees with attachment
- [NVIDIA RTX 4060 Laptop GPU](NVIDIA/RTX_4060_Laptop_GPU/README.md) — issue #2

Additional models, including other Laptop GPU, Ti, Super, D, AMD, and Intel variants, must receive **separate folders** when a submission is approved. An unrecognized model receives the label **gpu:unclassified** and remains visible in Issues. It must not be silently grouped with a similar card.

## Review before inclusion

A maintainer checks the submitted benchmark version and source/archive identity, exact GPU model and driver, actual GPU submission/completion, output correctness, run status, workload and timing method, and any failures or limitations. Check privacy and remove sensitive information from the proposed public summary. Keep failed and partial runs accurately described; do not promote them to a performance PASS.

The linked issue-specific pages below are reviews of exported archive consistency, **not independent GPU reruns**. Only after explicit maintainer approval may a short, attributed, reviewed summary be published under the corresponding GPU folder, for example **NVIDIA/RTX_4090/issue-123.md**. Link to the original public Issue, identify the reviewed source version and evidence scope, and avoid copying untrusted archives or raw logs into the repository. No workflow automatically downloads attachments, commits files, or publishes results.

Measurements from different GPU models, drivers, clocks, memory placements, workloads, and benchmark versions must not be merged into one performance comparison without a matching measurement protocol.

[All experiment results](../README.md)
