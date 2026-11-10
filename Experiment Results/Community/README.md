# Community benchmark results

Community submissions are collected as public [Benchmark Results issues](https://github.com/GoblinFlash/Native-DX12-Linux/issues?q=is%3Aissue+label%3Abenchmark%3Asubmission). A GitHub Actions workflow adds a GPU-model label for supported exact model names. A label is **categorization only**, not a correctness or performance endorsement.

## Curated GPU folders

- [NVIDIA RTX 4090](NVIDIA/RTX_4090/README.md)
- [NVIDIA RTX 3090](NVIDIA/RTX_3090/README.md)

Additional models, including Laptop GPU, Ti, Super, D, AMD, and Intel variants, must receive **separate folders** when a submission is approved. An unrecognized model receives the label **gpu:unclassified** and remains visible in Issues. It must not be silently grouped with a similar card.

## Review before inclusion

A maintainer checks the submitted benchmark version and source/archive identity, exact GPU model and driver, actual GPU submission/completion, output correctness, run status, workload and timing method, and any failures or limitations. Check privacy and remove sensitive information from the proposed public summary. Keep failed and partial runs accurately described; do not promote them to a performance PASS.

Only after explicit maintainer approval may a short, attributed, reviewed summary be added under the corresponding GPU folder, for example **NVIDIA/RTX_4090/issue-123.md**. Link to the original public Issue, identify the reviewed source version and evidence scope, and avoid copying untrusted archives or raw logs into the repository. No workflow automatically downloads attachments, commits files, or publishes results.

Measurements from different GPU models, drivers, clocks, memory placements, workloads, and benchmark versions must not be merged into one performance comparison without a matching measurement protocol.

[All experiment results](../README.md)
