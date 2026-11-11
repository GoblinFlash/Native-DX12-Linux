# Community benchmark intake operator guide

Community intake proposes **UNVERIFIED draft PRs**, grouped by exact GPU model and benchmark release. Enabling the workflow and accepting each result require repository-owner approval. The existing `benchmark-gpu-categories.yml` labels Issues separately; intake does not change labels or close Issues.

## Processing and permissions

The workflow handles `issues` opened, edited, reopened and labeled events, plus an explicit `workflow_dispatch` Issue number. It runs trusted scripts from the triggering `main` revision, only in `GoblinFlash/Native-DX12-Linux`. The Issue must be open, have a `[Results]` title and `benchmark:submission` label. OWNER/MEMBER/COLLABORATOR submissions can be processed immediately. Outside contributors need a maintainer-applied `benchmark:intake-approved` label or a maintainer's manual dispatch. This is intake authorization, not benchmark acceptance.

The `benchmark:intake-approved` label must exist before a maintainer can apply it. Intake and the GPU categorizer do not create that label. If it is absent, obtain explicit owner approval to create it, or use an authorized manual `workflow_dispatch` after the workflow is enabled. Do not grant workflow label-writing permissions to work around this prerequisite.

| Job | Token permissions | Work |
| --- | --- | --- |
| `prepare` | contents: read, issues: read | Read fresh Issue, download one public attachment without credentials, validate bounded data, upload only a typed JSON proposal. |
| `propose` | contents: write, pull-requests: write, issues: read | Revalidate typed proposal and fresh Issue, render sanitized files with trusted code, add files on a new intake branch and create a draft PR. |

The default token permissions are empty. Checkout uses a full action SHA and `persist-credentials: false`. No Issue body is inserted into shell code. Attachment content is never executed, imported, checked out or extracted to disk. The write-token job never downloads the archive. It accepts no paths, executable code, HTML, SVG, URLs or free-form prose from the proposal. The intermediate artifact contains only `proposal.json`, expires after three days, and uses the current run ID and attempt. Artifact service retention/deletion is not controlled by the parser.

The successful prepare job exports its artifact name as a job output. A retry of only the failed propose job uses that preserved name, rather than looking for a new-attempt artifact that was never uploaded. GitHub preserves outputs from jobs omitted from a partial rerun; see [re-running jobs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs). An expired/deleted artifact requires a fresh preparation, not bypassing validation.

Repository administrators must separately permit Actions to create PRs; intake does not change that setting. If GitHub returns `API_403`, inspect Actions/repository policy before retrying. See [GitHub Actions repository settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository). A PR event created with `GITHUB_TOKEN` can create an approval-required CI run; a writer may need to select **Approve workflows**. Do not assume that CI ran automatically or treat a missing run as a pass. See [workflow triggering](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

The repository's default token permission is separate from the explicit job permissions above. A settings read, including `default_workflow_permissions` or `can_approve_pull_request_reviews`, does not prove that this workflow can create a PR at runtime and does not authorize approving reviews. Verify effective policy with an approved deployment test; intake never submits approving reviews.

## Supported archives and fixed paths

Only the `ndx12-share.v2` layouts cataloged for `v0.1.4` and `v0.1.5` are supported. `community_releases.json` pins the benchmark archive name/size/hash, package ID, manifest count/hash and installer/starter hashes. Identity fields in a share bundle are self-reported: a catalog match checks consistency, not authorship or authenticity. New releases or export schemas need an explicitly reviewed catalog/parser update; no guessed version is accepted.

Attachment names may be `share-results.tar.gz`, `share-results-v0.1.5.tar.gz`, or the same names with a three- or four-digit numeric prefix whose first digit is nonzero, followed by a hyphen: for example, `3090-share-results-v0.1.5.tar.gz`. Filename version components are limited to three digits each. Other prefix forms such as `RTX-3090-` or `3090-ti-` are unsupported and require manual handling. The prefix and filename version are discovery hints only: GPU classification and release checks use the Issue fields and actual `run.json`/catalog fields. A filename starting `3090-` cannot classify a bundle as RTX 3090. The internal archive root/member allowlist stays `ndx12-results/`; no filename is used as an output path.

Outputs use `Experiment Results/Community/<vendor>/<exact_GPU>/<release>/issue-N/`. Categories come from a fixed dictionary. Ti, Super, Laptop GPU and D suffixes remain distinct. Unknown GPUs use `Pending_Classification`; mismatched GPU/release/catalog identities also go there. Unknown releases use the literal `Unidentified_Version`. Issue numbers are bounded positive integers. No string from a submission becomes an arbitrary path.

| Limit | Maximum |
| --- | ---: |
| Issue body | 64 KiB |
| Compressed bundle | 8 MiB |
| Expanded gzip stream | 16 MiB |
| Individual tar member | 2 MiB |
| Tar headers, including directory/PAX headers | 64 |
| PAX metadata | 1 KiB, mtime only |
| Parsed process/measurement rows | 189 each |
| Intermediate typed proposal | 128 KiB |
| Attachment redirects | 3, fixed HTTPS hosts only |
| Socket timeout / total download budget | 15 s / 45 s, checked between bounded reads |
| Workflow job timeout | 3 minutes per job |

The fixed archive member allowlist is `run.json`, `processes.csv`, `samples.csv`, `compute-vulkan-samples.csv`, `test1-d4-processes.csv`, `test1-d4-vulkan-processes.csv`, `test2-k-processes.csv`, `test2-k-vulkan-processes.csv`, `test3-kw-processes.csv`, `test3-kw-vulkan-processes.csv`, `summary.txt`, `charts.html`, and `charts/{results,d4-chart,k-chart,kw-chart}.svg`, under `ndx12-results/`. The last six prose/HTML/SVG members are skipped, not parsed or copied. Only regular files and the two expected directories are accepted. Links, devices, sparse/GNU extensions, duplicate files, unknown members, traversal and PAX path/size/link overrides fail closed. Member counts and expansion limits apply even to skipped content.

JSON duplicate keys, nonfinite/oversized numbers, malformed CSV, unexpected headers/statuses/schedules, duplicate/missing measurements and count/identity contradictions are refused. Claimed Issue GPU, release, recognized package/archive hash, driver and run status are checked against archive fields. Driver input accepts the numeric version plus a bounded optional NVIDIA Open/proprietary description, including parentheses; only the numeric version is copied. A malformed, missing, permanently unavailable (HTTP404/410), unsupported or contradictory bundle yields `MANUAL_REVIEW`, a fixed reason code and no numeric output. Transient download errors/timeouts fail the prepare job without creating a proposal/branch/PR, so they can be retried. Generic input failures do not publish exception text. Infrastructure/API failures stop the job without accepting a result.

## Sanitized results and evidence limits

A consistent bundle produces six files: `README.md`, `record.json`, `processes.csv`, `measurements.csv`, `summary.csv` and a newly rendered `chart.svg`. Selected measurements come from numeric CSV, not uploaded summaries or graphics. The chart shows independent scales for Native `GPU_TICKS` and Vulkan `NS`; no cross-API speedup is calculated. Frame-suite aggregate values are medians of process medians. Unknown/private model strings, hostnames, users, paths, IPs, UUIDs, OS/kernel details and raw reporter prose are not copied. The original public Issue/attachment remains outside this workflow's privacy control.

Each record carries **UNVERIFIED**, self-reported identity, no independent GPU rerun, unavailable raw readbacks, unproven per-dispatch clocks and unassessed background contention caveats. Clock qualification/envelopes are explicitly reported values. Kernel-record counts and noncomplete states remain visible; private error details do not. A reported 189/189 VERIFIED result is not independent GPU qualification. Review the source Issue for redactions, ONNX/background use, clock/model explanations, provenance and negative evidence. Unstructured Issue prose cannot be comprehensively compared to CSV fields; its manual review remains mandatory.

## Idempotence, edits and recovery

Each Issue uses `community/benchmark-issue-N` and at most one automatically proposed PR. Events are serialized per Issue. The writer checks for an existing `issue-N.md`, `issue-N-submission.md`, or versioned `issue-N/{README.md,record.json}` anywhere below Community, and for any prior PR on that branch, including closed/merged PRs. It skips those records instead of adding duplicates. Issues #2/#3/#4/#5 are additionally reserved for manual curated migration, even when their data exists only in the central report, as with #4. Reopened/edited events do not refresh existing files or branches; a maintainer must reconcile revisions manually.

The writer checks the Issue fingerprint (number, title, body, state and the two eligibility labels: `benchmark:submission` and `benchmark:intake-approved`) and intake permission before writing objects and again immediately before `git/refs`. A content/state/eligibility change at either gate stops creation of the branch. Unreferenced objects may remain if the change occurs during object uploads. Comment timestamps, GPU-category labels and unrelated labels do not invalidate the fingerprint. `record.json` pins the prepared source fingerprint and bundle SHA-256; no later Issue data silently replaces that snapshot.

After a new ref succeeds, the writer creates a draft for that pinned snapshot even if the Issue changes, closes or loses intake authorization afterward. The PR body records the prepared and observed content fingerprints, snapshot commit, bundle hash and eligibility observation. Source status is `MATCH_AT_CHECK`, `STALE`, or `UNKNOWN` if the final read fails or is malformed. This post-ref observation annotates the draft rather than blocking it and leaving an avoidable orphan. No raw Issue prose or API error text is copied into the body. `STALE`/`UNKNOWN` requires explicit reconciliation before acceptance; compare the live Issue and actual PR head with the pinned fingerprints/commit. GitHub provides no atomic Issue/ref/PR transaction, so even `MATCH_AT_CHECK` describes only one observation. No acceptance follows from a successful API call.

A PR API failure, interrupted job or ambiguous ref response can still leave an orphan intake branch. A retry only creates the missing draft PR when the branch has exactly the original proposal message, one parent, the expected added-file diff and exact blob bytes/modes. Its parent must still be an ancestor of current main. The existing-orphan path also requires a fresh matching Issue fingerprint and intake permission immediately before creating the PR; it never uses the new-ref allowance for late changes. Human edits, foreign branches and unrelated history stop recovery. No branch/ref is updated, forced or deleted. Objects created before an API failure may remain unattached; automatic destructive cleanup is deliberately absent. Existing main file/path collisions stop the proposal.

If an existing orphan no longer matches the current proposal/source or permission, recovery reports `EXISTING_BRANCH_CHANGED`, `SOURCE_CHANGED` or an eligibility refusal with no additional writes. A maintainer inspects the orphan's commit message/content, current Issue and existing PR list. Under explicit owner approval, the maintainer can either create a manually reviewed UNVERIFIED draft with accurate source/provenance, or retire the exact stale orphan and rerun preparation. Never silently reuse changed bytes, weaken recovery checks, force-update/delete a branch or accept results to clear this condition.

## Migration and approval

The four `v0.1.4/README.md` indexes for Issues #2/#3/#4/#5 link existing per-GPU records and the centralized `v0.1.4-submitted-data.md` tables/charts. They do not move, duplicate or overwrite historical records. Issue #4's clarification is received with maintainer acceptance pending; #3 discloses ONNX contention; #5 has four NOT_QUALIFIED clock checks. Check current main before any backfill. Existing records cause the writer to skip those Issues, even if manually dispatched.

Issue #11 claims RTX 3090/v0.1.5. The inspected attachment reports RTX 3060, so `GPU_MISMATCH` yields only a manual-review proposal under `Pending_Classification/v0.1.5/issue-11/`. No RTX 3090 measurements are imported. Re-read the live Issue/archive before processing; later reporter corrections require manual reconciliation.

For a new draft, the maintainer reviews GPU/release/catalog consistency, pinned/observed source revisions, numeric tables and source caveats, privacy, archive provenance, timing/clock evidence, completion/correctness scope, contention and negative results. Resolve stale or unknown source observations before acceptance. Only after explicit owner approval may a maintainer accept/merge a submission. Intake grants no merge, release, label or Issue-close authority.

Before enabling intake, maintainers review workflow changes under repository code-review policy, final permissions, action pins, target repository/branch, existing workflows/records and repository PR-creation policy, and obtain owner approval. Resolve policy refusals without bypassing repository controls. Verify delivery and token permissions with an approved bounded test before relying on production intake; CPU tests alone do not establish them.

## CPU-only verification

From the repository root, with Python 3.10 or newer and only the standard library:

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
