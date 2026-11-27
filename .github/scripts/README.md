# Community benchmark intake operator guide

Community intake proposes **UNVERIFIED draft PRs**, grouped by exact GPU model and benchmark release. Enabling the workflow and accepting each result require repository-owner approval. The separate `benchmark-gpu-categories.yml` labels Issues and dispatches a non-manual intake retry after first adding the submission label, or when rerunning a categorizer job after dispatch failure; intake does not change labels or close Issues.

## Processing and permissions

The workflow handles `issues` opened, edited, reopened and labeled events, plus an explicit `workflow_dispatch` Issue number. It runs trusted scripts from the triggering `main` revision, only in `GoblinFlash/Native-DX12-Linux`. The Issue must be open, have a `[Results]` title and `benchmark:submission` label. OWNER/MEMBER/COLLABORATOR submissions can be processed immediately. Outside contributors need a maintainer-applied `benchmark:intake-approved` label or a maintainer's **manual** dispatch. A categorizer-triggered `workflow_dispatch` has `intake_mode: label-reconciled` and explicitly does not count as manual permission; `intake_mode: manual` (the default for existing maintainer calls) retains the current manual route. This is intake authorization, not benchmark acceptance.

The Issue form's release field is plain text (for example `v0.1.7`, `0.1.7` or `NDX12-Benchmark-v0.1.7.run`), so a new release needs no form or catalogue change. A field without any release number (`Other or unknown`, empty) takes the release recorded in the archive's `run.json`. A named release must equal the archive's (`VERSION_MISMATCH` otherwise); suffixes such as `v0.1.5-rc.1` and two different releases stay `VERSION_UNKNOWN`. The GPU label workflow covers all 44 fixed NVIDIA RTX models supported by the intake parser, plus the listed AMD/Intel entries. Exact Ti/Super/D/Laptop suffixes stay separate. Explicit `GeForce 4060` and `NVIDIA GeForce 4060` aliases map to the fixed desktop `RTX 4060` entry, but bare `4060` and cross-vendor strings do not.

A `Full test completed` or `Selected tests completed` claim means all requested processes reported execution completion (`completed == expected`), not that all passed `VERIFIED`. A run with one completed `FAIL` may remain `overall: FAILED` and retain only the `VERIFIED` processes' numeric measurements; failed counts, failure markers and `NONCOMPLETE_RUN` warnings remain visible. A stopped/failed-to-start claim cannot describe a run whose process schedule fully executed. None of these status selections is independent correctness evidence.

For outside contributors without processing permission, `prepare` completes without `ready=true` and `propose` remains skipped. The Actions step summary and warning now explicitly say `AWAITING_INTAKE_APPROVAL` (or `NOT_ELIGIBLE` for a closed/invalid Issue). A green GitHub run **does not** imply a draft PR or a merged record. For an authorized submission without publishable measurements, the prepare job emits a warning and records the Issue number and reason in its Actions summary, and the workflow skips the draft job. Check the `prepare` summary, the actual draft PR, and the final repository tree. These messages do not alter acceptance policy or grant automation new Issue-write permissions.

The `benchmark:intake-approved` label must exist before a maintainer can apply it. Intake and the GPU categorizer do not create that label. If it is absent, obtain explicit owner approval to create it, or use an authorized manual `workflow_dispatch` after the workflow is enabled. Do not grant workflow label-writing permissions to work around this prerequisite.

| Job | Token permissions | Work |
| --- | --- | --- |
| `gpu-category` (separate workflow) | issues: write, actions: write | Reconcile fixed labels; dispatch a non-manual intake retry when adding the submission label, or on a rerun (`GITHUB_RUN_ATTEMPT` > 1) when the label persists after failure. Normal edits with existing labels do not dispatch duplicates. The draft writer is independently idempotent. The extra Actions scope is for `workflow_dispatch`, not benchmark acceptance. |
| `prepare` | contents: read, issues: read | Read fresh Issue, download one public attachment without credentials, validate bounded data, upload only a typed JSON proposal. |
| `propose` | contents: write, pull-requests: write, issues: read | Revalidate typed proposal and fresh Issue, render sanitized files with trusted code, add files on a new intake branch and create a draft PR. |

To protect a pending maintainer manual dispatch from being replaced by a later automatic Issue event, intake uses `concurrency.queue: max` with `cancel-in-progress: false`. GitHub can queue up to 100 pending runs per group; this preserves authorization mode on each queued event, but the approval gate still runs when a job starts. Live queue behavior has not been verified on GitHub.

The intake workflow's default token permissions are empty; the separate categorizer explicitly grants `issues: write` and `actions: write` for fixed label/dispatch APIs. GitHub suppresses ordinary `GITHUB_TOKEN`-generated label events, but allows explicit `workflow_dispatch` events; no PAT or GitHub App secret is required for this scoped retry. Review this new permission before publication. Checkout uses a full action SHA and `persist-credentials: false`. No Issue body is inserted into shell code. Attachment content is never executed, imported, checked out or extracted to disk. The write-token job never downloads the archive. It accepts no paths, executable code, HTML, SVG, URLs or free-form prose from the proposal. The intermediate artifact contains only `proposal.json`, expires after three days, and uses the current run ID and attempt. Artifact service retention/deletion is not controlled by the parser.

The successful prepare job exports its artifact name as a job output. A retry of only the failed propose job uses that preserved name, rather than looking for a new-attempt artifact that was never uploaded. GitHub preserves outputs from jobs omitted from a partial rerun; see [re-running jobs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs). An expired/deleted artifact requires a fresh preparation, not bypassing validation.

Repository administrators must separately permit Actions to create PRs; intake does not change that setting. If GitHub returns `API_403`, inspect Actions/repository policy before retrying. See [GitHub Actions repository settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository). A PR event created with `GITHUB_TOKEN` can create an approval-required CI run; a writer may need to select **Approve workflows**. Do not assume that CI ran automatically or treat a missing run as a pass. See [workflow triggering](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

The repository's default token permission is separate from the explicit job permissions above. A settings read, including `default_workflow_permissions` or `can_approve_pull_request_reviews`, does not prove that this workflow can create a PR at runtime and does not authorize approving reviews. Verify effective policy with an approved deployment test; intake never submits approving reviews.

## Supported archives and fixed paths

Public releases `v0.1.4` and `v0.1.5` use `ndx12-share.v2` and stay pinned: their archive identity must equal the `community_releases.json` entry (archive name/size/hash, package ID, manifest count/hash, installer/starter hashes), with status `VERIFIED` and driver 615.78.08 or 620.70.06. Every later release `vX.Y.Z` uses `ndx12-share.v3` and is imported without a catalogue entry: the identity status may be `VERIFIED` (run from the archive) or `INSTALLED` (the installed benchmark), the driver is any NVIDIA version that the Issue and `run.json` both name, and a package that is not an exact catalogued build carries the `PACKAGE_NOT_CATALOGUED` warning. Identity fields in a share bundle are self-reported: a catalog match checks consistency, not authorship or authenticity.

For v3, Native and Vulkan timing columns and units are in exact nanoseconds. The desktop schedules admit the existing Compute, D4, K and WaveForm workloads plus FWHT, Sponza and Neural Grid. Complete process coverage is required for all requested steps. A case or arm that a later release adds to a known suite (for example Compute `parallel-sort4096-1`) is accepted with all of its repeats and charted after the known ones; its name must match `[a-z0-9][a-z0-9_-]{0,47}`. Partial archives with omitted process schedules require manual review. Standalone G-buffer bundles require manual review. Each measured suite gets its own chart covering its scheduled workloads. Private builds without a verified public installation receipt remain outside automatic intake.

Attachment names may be `share-results.tar.gz`, `share-results-v0.1.5.tar.gz`, the benchmark's own `share-results-<card>-<release>.tar.gz` (card: up to 24 lowercase letters/digits such as `4090` or `3080ti`; release: `vX.Y.Z` or `release-unknown`), or the older names with a three- or four-digit numeric prefix whose first digit is nonzero, followed by a hyphen: for example, `3090-share-results-v0.1.5.tar.gz`. Filename version components are limited to three digits each. Other prefix forms such as `RTX-3090-` or `3090-ti-` are unsupported and require manual handling. The prefix and filename version are discovery hints only: GPU classification and release checks use the Issue fields and actual `run.json`/catalog fields. A filename starting `3090-` cannot classify a bundle as RTX 3090. The internal archive root/member allowlist stays `ndx12-results/`; no filename is used as an output path.

Outputs use `Benchmark Results/<vendor>/<exact_GPU>/<release>/issue-N/`. Categories come from a fixed dictionary. Ti, Super, Laptop GPU and D suffixes remain distinct. Unclassified submissions and exports without measurements stay in their source Issues. Issue numbers are bounded positive integers. No string from a submission becomes an arbitrary path.

| Limit | Maximum |
| --- | ---: |
| Issue body | 64 KiB |
| Compressed bundle | 8 MiB |
| Expanded gzip stream | 16 MiB |
| Individual tar member | 2 MiB |
| Tar headers, including directory/PAX headers | 64 |
| PAX metadata | 1 KiB, mtime only |
| Parsed process/measurement rows | 189 per v2 schedule, up to 512 for v3 |
| Intermediate typed proposal | 512 KiB |
| Attachment redirects | 3, fixed HTTPS hosts only |
| Socket timeout / total download budget | 15 s / 45 s, checked between bounded reads |
| Workflow job timeout | 3 minutes per job |

The v2 archive member allowlist is `run.json`, `processes.csv`, `samples.csv`, `compute-vulkan-samples.csv`, `test1-d4-processes.csv`, `test1-d4-vulkan-processes.csv`, `test2-k-processes.csv`, `test2-k-vulkan-processes.csv`, `test3-kw-processes.csv`, `test3-kw-vulkan-processes.csv`, `summary.txt`, `charts.html`, and `charts/{results,d4-chart,k-chart,kw-chart}.svg`, under `ndx12-results/`. V3 adds Native and Vulkan process tables for Test 4 FWHT, Native process tables for Test 5 Sponza and Neural Grid bounce, and their generated charts. Non-measurement files are skipped, not parsed or copied. Only regular files and the two expected directories are accepted. Links, devices, sparse/GNU extensions, duplicate files, unknown members, traversal and PAX path/size/link overrides fail closed. Member counts and expansion limits apply even to skipped content.

JSON duplicate keys, nonfinite/oversized numbers, malformed CSV, unexpected headers/statuses/schedules, duplicate/missing measurements and count/identity contradictions are refused. Claimed Issue GPU, release, recognized package/archive hash, driver and run status are checked against archive fields. Driver input accepts the numeric version plus a bounded optional NVIDIA Open/proprietary description, including parentheses; only the numeric version is copied. A malformed, missing, permanently unavailable (HTTP404/410), unsupported or contradictory bundle yields `MANUAL_REVIEW`, a fixed reason code and no numeric output. Transient download errors/timeouts fail the prepare job without creating a proposal/branch/PR, so they can be retried. Generic input failures do not publish exception text. Infrastructure/API failures stop the job without accepting a result.

## Sanitized results and evidence limits

### GPU and PCI field consistency

Preparation compares the exact Issue/archive GPU category and the recorded
`run.json` vendor/device PCI ID with `community_gpu_pci.json`. Its factual
NVIDIA mappings come from the pinned upstream 620.70.06 README commit/blob
recorded in that file; several IDs may match one model. An explicit PCI suffix
in either model field must also match the recorded ID. Malformed, unknown,
unrecorded or contradictory identities stay in manual review without numeric
data. Unmapped models require new reviewed evidence rather than guessed IDs.
Only vendor/device IDs are retained; PCI locations, subsystem IDs, hostnames
and serial identifiers are not exported. A match is self-reported consistency,
not authentication of the GPU, subsystem, provenance or execution.

The internal typed proposal is now `ndx12.community-intake.v2`, with one
canonical `pci` field. The writer repeats the model/PCI check before any API
call. The uploaded `ndx12-share.v2` archive and release identity pins are
unchanged. Old internal v1 proposals must be prepared again; old orphan
branches keep strict exact-byte recovery and may require manual reconciliation.
Existing published records are not rewritten by this schema transition.

The draft writer also proposes updates to **both public result indexes**:
[`Benchmark Results/README.md`](../../Benchmark%20Results/README.md) and
[`Benchmark Results/SUBMISSIONS.md`](../../Benchmark%20Results/SUBMISSIONS.md).
The writer may also refresh guarded release reports and GPU/version indexes as described below. Issue-specific files remain additive. Index blobs are fetched from the exact base Git tree and verified by Git object SHA,
size, UTF-8 format and managed section markers before any Git write. New entries link the exact
GPU/release/Issue folder; reports show export consistency and owner acceptance separately; historic v0.1.4 measurements are preserved.
The initial index section may be inserted only into the two exact pre-migration Git blobs
recorded from main `8e720506`; their original headings and curated prose are preserved.
Both the input and updated UTF-8 index must fit within 128 KiB.
Missing, malformed or hand-modified markers stop intake instead of overwriting documentation.
Concurrent unmerged intake PRs may touch the same indexes and require manual Git conflict
resolution before owner-approved merge. An index link is never acceptance of an experiment.

Each model page links to its benchmark versions. Each version page embeds the charts for each run in order. Titles use the GPU model and version. A complete v0.1.4 or v0.1.5 run has 6 Compute, 9 D4, 6 K and 6 K WaveForm bars. The rendering uses the panel layout of the published v0.1.5 benchmark. Bars show the median, whiskers span the minimum and maximum and tooltips give the sample count. Times below one millisecond use ns. Larger values use ms rounded to two decimal places. Exports without qualified clocks keep independent scales.

Each run retains its typed record, memory-backing evidence, process CSV, measurement CSV and summary CSV alongside the charts. Intake builds graphics from validated data. Measured series from different runs are never combined. Issues requiring clarification stay in Issues.

The run heading links to its source. `run-context.json` records the source URL and archive digest. Reviewed historical OS or background load is bound to that digest. On the pinned v0.1.4 and v0.1.5 NVIDIA packages, the legacy `GPU_TICKS` field contains semaphore timestamps with a nanosecond time base. The CSV projection preserves the numeric value. Each run's host/GPU clock envelope is a separate check. The chart shows release-documented Native buffer placement and the recorded Vulkan placement status.

Frame tables support native half-tick medians and Vulkan nanoseconds with up to 20 decimal places, without exponent notation; values must be between zero and 10^15. Rounds and native first/warmup/empty tick fields remain integers. Whole measurement values stay JSON integers; fractional values use canonical decimal strings in the typed proposal and retain their exact numeric value in CSV. Summary arithmetic uses exact fractions, including a possible 21st decimal place for an even-sample median. Only chart bar geometry uses floating-point scaling. The writer revalidates these formats before any API call. It also rejects `NOT_RUN` processes with completed execution and `VERIFIED` processes with negative submission states. GPU vendor prefixes match only their corresponding model family; contradictory vendor/model names stay pending classification.

The typed record preserves export checks and warnings. `CHECKED` does not mean the benchmark succeeded: failed/partial runs retain their reported state and negative evidence. `Owner acceptance: NOT_RECORDED` describes intake evidence, not proof that the owner has not reviewed the submission. Intake does not read acceptance from Issues, approval labels or PR merges. A maintainer may separately record an explicit owner decision through a reviewed change; intake never grants one. The internal `UNVERIFIED_SUBMISSION` warning stays intact. Each record retains self-reported identity, no independent GPU rerun, unavailable raw readbacks, unproven per-dispatch clocks and unassessed background contention caveats. Clock qualification/envelopes are explicitly reported values. Kernel-record counts and noncomplete states remain visible; private error details do not. A reported VERIFIED count is not independent GPU qualification. Review the source Issue for redactions, ONNX/background use, clock/model explanations, provenance and negative evidence. Unstructured Issue prose cannot be comprehensively compared to CSV fields; its manual review remains mandatory.

## Idempotence, edits and recovery

Each Issue uses `community/benchmark-issue-N` and at most one automatically proposed PR. Events are serialized per Issue. The writer checks for an existing `issue-N.md`, `issue-N-submission.md`, or versioned `issue-N/{README.md,record.json}` anywhere below Community, and for any prior PR on that branch, including closed/merged PRs. It skips those records instead of adding duplicates. Issues #2/#3/#4/#5 are additionally reserved for manual curated migration, even when their data exists only in the central report, as with #4. Reopened/edited events do not refresh existing files or branches; a maintainer must reconcile revisions manually.

The writer checks the Issue fingerprint (number, title, body, state and the two eligibility labels: `benchmark:submission` and `benchmark:intake-approved`) and intake permission before writing objects and again immediately before `git/refs`. A content/state/eligibility change at either gate stops creation of the branch. Unreferenced objects may remain if the change occurs during object uploads. Comment timestamps, GPU-category labels and unrelated labels do not invalidate the fingerprint. `record.json` pins the prepared source fingerprint and bundle SHA-256; no later Issue data silently replaces that snapshot.

After a new ref succeeds, the writer creates a draft for that pinned snapshot even if the Issue changes, closes or loses intake authorization afterward. The PR body records the prepared and observed content fingerprints, snapshot commit, bundle hash and eligibility observation. Source status is `MATCH_AT_CHECK`, `STALE`, or `UNKNOWN` if the final read fails or is malformed. This post-ref observation annotates the draft rather than blocking it and leaving an avoidable orphan. No raw Issue prose or API error text is copied into the body. `STALE`/`UNKNOWN` requires explicit reconciliation before acceptance; compare the live Issue and actual PR head with the pinned fingerprints/commit. GitHub provides no atomic Issue/ref/PR transaction, so even `MATCH_AT_CHECK` describes only one observation. No acceptance follows from a successful API call.

A PR API failure, interrupted job or ambiguous ref response can still leave an orphan intake branch. A retry only creates the missing draft PR when the branch has exactly the original proposal message, one parent, the expected diff (added Issue files and added/modified guarded aggregate/index files) and exact blob bytes/modes. Its parent must still be an ancestor of current main. The existing-orphan path also requires a fresh matching Issue fingerprint and intake permission immediately before creating the PR; it never uses the new-ref allowance for late changes. Human edits, foreign branches and unrelated history stop recovery. No branch/ref is updated, forced or deleted. Objects created before an API failure may remain unattached; automatic destructive cleanup is deliberately absent. Unexpected main file/path collisions stop the proposal; only guarded index/aggregate paths are updated in a Draft PR. Recovery also requires identical aggregate source record/report/GPU-index identities on current main; changed aggregate inputs stop recovery rather than presenting a stale report as fresh.

If an existing orphan no longer matches the current proposal/source or permission, recovery reports `EXISTING_BRANCH_CHANGED`, `SOURCE_CHANGED` or an eligibility refusal with no additional writes. A maintainer inspects the orphan's commit message/content, current Issue and existing PR list. Under explicit owner approval, the maintainer can either create a manually reviewed UNVERIFIED draft with accurate source/provenance, or retire the exact stale orphan and rerun preparation. Never silently reuse changed bytes, weaken recovery checks, force-update/delete a branch or accept results to clear this condition.

## Migration and approval

The four `v0.1.4/README.md` indexes for Issues #2/#3/#4/#5 link existing per-GPU records and the centralized `v0.1.4-submitted-data.md` tables/charts. They do not move, duplicate or overwrite historical records. Issue #4's clarification is received with maintainer acceptance pending; #3 discloses ONNX contention; #5 has four NOT_QUALIFIED clock checks. Check current main before any backfill. Existing records cause the writer to skip those Issues, even if manually dispatched.

[Issue #11](https://github.com/GoblinFlash/Native-DX12-Linux/issues/11) originally carried the RTX 3060 archive from Issue #10. The reporter replaced it with an RTX 3090 v0.1.5 export (SHA-256 `39b40115bb69bd3587011584d643aaf047024c87993462ef055380ec4d622131`). Its 189 exported measurements are in the [RTX 3090 release folder](../../Benchmark%20Results/NVIDIA/RTX_3090/v0.1.5/). All four host/GPU clock checks are NOT_QUALIFIED. Keep Native and Vulkan on independent scales.

For a new draft, the maintainer reviews GPU/release/catalog consistency, pinned/observed source revisions, numeric tables and source caveats, privacy, archive provenance, timing/clock evidence, completion/correctness scope, contention and negative results. Resolve stale or unknown source observations before acceptance. Only after explicit owner approval may a maintainer accept/merge a submission. Intake grants no merge, release, label or Issue-close authority.

Before enabling intake, maintainers review workflow changes under repository code-review policy, final permissions, action pins, target repository/branch, existing workflows/records and repository PR-creation policy, and obtain owner approval. Resolve policy refusals without bypassing repository controls. Verify delivery and token permissions with an approved bounded test before relying on production intake; CPU tests alone do not establish them.

## CPU-only verification

From the repository root, with Python 3.10 or newer, its standard library, and Node.js on `PATH` for the real JavaScript GPU-categorizer test:

```bash
python3 -I -B -m unittest discover -s tests -v
python3 -I -O -B -m unittest discover -s tests -v
```

Tests generate deterministic synthetic bundles and use a stateful fake API for every write. They cover numeric output, exact categories/releases, malformed and adversarial archives, privacy, bounded network reads, stale Issues, duplicate events, protected curated records and orphan-branch recovery. Temporary fixtures use Python's configured temp directory; set `TMPDIR` to a dedicated temporary directory when needed. Tests do not contact GitHub, start GPUs, build runtimes or authenticate a real token.

To inspect a previously downloaded bundle locally without network or Git writes:

```bash
python3 -I -B .github/scripts/community_intake.py \
  --issue-json issue.json --bundle share-results-v0.1.5.tar.gz --output proposal.json
```

This command writes a new typed proposal only and refuses to overwrite an existing output. `--issue-json` is a local fixture/preview interface; it does not authorize GitHub processing. Never run the separate publisher's `--apply` interface before deployment approval. Unsupported archive formats/releases, automatic refresh after edits, full prose/privacy review and independent GPU/clock/provenance qualification remain manual capabilities.

## Native data-buffer memory backing

`memory-backing.json` is derived during rendering from the exact documented release identity. v0.1.4 and v0.1.5 are SYSMEM only when the complete catalogue identity matches the separately verified memory-evidence fingerprint. A changed/new identity or refused proposal produces UNKNOWN/NOT_RECORDED. Issue prose and extra archive fields cannot override this classification. Vulkan backing remains NOT_RECORDED. This labels documented release behavior, not independently observed host allocation or accepted benchmark claims. Future VRAM releases require their own evidence; the release pins, share archive and intermediate proposal schema are unchanged. Existing records/drafts are never silently rewritten; changed generated file sets can require manual handling of old orphans under the existing strict recovery rules.

## Rebuild a version report locally

Use `community_intake.py --issue-json ISSUE.json --bundle SHARE.tar.gz --output proposal.json` to create a bounded, sanitized proposal from each public source. This local analysis route can inspect a closed historical submission; it grants no live intake or GitHub write permission. Keep source Issue JSON and raw archives outside the public output. Check the exact GPU/release fields and refusals before review.

Run `python3 .github/scripts/community_version_report.py --version v0.1.5 --proposal proposal-10.json --proposal proposal-11.json --proposal proposal-14.json --proposal proposal-15.json --existing-issue 15 --output NEW_LOCAL_OUTPUT`. The destination must have no existing output files. `--existing-issue` references the existing run’s files without regenerating its record or charts. New matching Issues receive normal sanitized records. The report omits submissions requiring correction and exports without measurements. All inputs must claim the requested exact version; duplicate Issue IDs are refused. Multiple matching submissions for the same GPU/release keep separate Issue records and share one GPU/version index linking every corresponding report section.

### Aggregate updates in the draft writer

For a recognized release the writer reads sanitized `record.json` files from the exact base tree, revalidates every field using the same writer-side checks, and adds the new record, release report, affected GPU/version index and both overview tables to **one draft tree**. It does not fetch old attachments, execute uploaded code or regenerate historical per-Issue data/charts. Multiple Issues for one GPU remain separate observations. The workflow leaves submissions without publishable measurements in Issues and skips the draft job.

Generated blocks use `<!-- ndx12:<key>:start/end -->` markers. The existing block must exactly match the rendering of the validated old records before it can be replaced. Missing markers, hand edits inside a generated block, missing/invalid records, path collisions and oversize content stop the entire proposal before any write. Keep owner acceptance decisions and annotations **outside** these blocks; those bytes are preserved exactly. Intake never writes or infers acceptance. Individual all-version links occupy a separate details section rather than any release's table.

Limits are 32 records per release including the incoming record, 512 KiB per typed record, 4 MiB total record content per release and 512 KiB per aggregate document. The existing overview index limit remains 128 KiB. Blob object ID, size, mode and base64 are checked before parsing. GPU/release paths still come exclusively from validated GPU categories and `vX.Y.Z` release numbers. The sole legacy-v1 bridge is Issue #15's exact historical Git blob `2e0ede8ca75435f97b643806d80612579a52dd05`, archive hash and separately archive-checked PCI `10de:2882`; it adapts in memory and does not rewrite that record. Other legacy or modified v1 records require explicit migration.

All measured releases use the same version index. The four historical v0.1.4 runs have typed records reconstructed from their public archives.

### Freshness check and concurrent merges

A draft is consistent with **its base-tree snapshot**. Two parallel intakes can both be valid against that snapshot, then leave stale tables if merged without refreshing. Run the read-only check on the prospective merged checkout:

```sh
python3 -B .github/scripts/community_aggregate.py --verify-root .
```

`AGGREGATES_CURRENT` checks known-release records against every generated report, GPU index and overview block; stale or edited blocks produce MANUAL_REVIEW and a nonzero exit. It does not prove GPU execution or approval. The local checker also bounds total scanning to 128 versioned records / 16 MiB. It never writes files, fetches or publishes.

**Required integration decision:** the existing [community aggregate freshness workflow](../workflows/community-aggregate-freshness.yml) runs `--verify-root` on the prospective merge tree for pull requests and on merge-group trees. Enforcement still requires owner-approved configuration of **Community aggregate freshness** as a required check, with strict up-to-date checks or a merge queue. The writer alone cannot guarantee freshness across concurrent merges. Until required-check enforcement is configured, maintainers must review the check results and refresh stale drafts before merging. The writer uses existing permissions; no expanded token scope or new workflow trigger is needed for the draft update itself. No generated graph, reported completion count or overview entry accepts benchmark claims.
