#!/usr/bin/env python3
"""Typed-data-only draft PR writer. Never downloads, executes, merges or approves."""
import argparse
import base64
import binascii
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re

_spec = importlib.util.spec_from_file_location('trusted_intake', Path(__file__).with_name('community_intake.py'))
intake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(intake)


def git_blob(data):
    """Return the Git SHA-1 object ID for the supplied blob bytes, without storing them."""
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def sha(value):
    """Require and return a lowercase 40-hex Git object ID, or raise API_SHA."""
    intake.need(type(value) is str and re.fullmatch('[0-9a-f]{40}', value), 'API_SHA')
    return value


def get_optional(api, endpoint):
    """Return an API GET result, treating only API_404 as an absent resource."""
    try:
        return api.get(endpoint)
    except intake.Refused as error:
        if str(error) == 'API_404':
            return None
        raise


def tree_entries(api, tree_sha):
    """Read one recursive Git tree and refuse truncated, malformed or oversized listings."""
    result = api.get('git/trees/' + sha(tree_sha) + '?recursive=1')
    intake.need(result.get('truncated') is False and type(result.get('tree')) is list and
                len(result['tree']) <= 10000, 'TREE_LIMIT')
    return result['tree']


def existing_issue(entries, issue_number):
    """Report whether tree entries contain an existing legacy or versioned Issue record."""
    pattern = re.compile(r'^Experiment Results/Community/(?:[^/]+/)*issue-' + str(issue_number) +
                         r'(?:-submission)?(?:\.md|/(?:README\.md|record\.json))$')
    return any(type(row.get('path')) is str and pattern.fullmatch(row['path']) for row in entries)


INDEX_START = '<!-- ndx12-community-intake:start -->'
INDEX_END = '<!-- ndx12-community-intake:end -->'
INDEX_NOTE = ('Intake entries remain **UNVERIFIED** even after a draft PR is merged. '
              'Export consistency does not prove GPU execution or permit Native-versus-Vulkan rankings.')
INDEXES = {
    'Experiment Results/README.md': ('\n## Curated community benchmark data — v0.1.4\n', 'Community/'),
    'Experiment Results/Community/README.md': ('\n## Curated v0.1.4 report\n', ''),
}
# Exact public main 8e720506 index blobs, before managed-section migration.
INDEX_BOOTSTRAP = {
    'Community/': ('c594a30eb9c6b74ecde7bd3b38fd7ac840b70006',
                   '\n## Latest community benchmark data — v0.1.4\n'),
    '': ('9ac283a9f673501c90f838b09ccb4ee001d0c66a', '\n## Latest submitted data\n'),
}


def index_entry(proposal, prefix):
    """Format a link only from validated catalogue identity and a fixed result path."""
    folder = intake.record_folder(proposal)
    gpu = proposal['claimed_gpu']
    if gpu in intake.GPUS and folder.startswith(intake.ROOT + gpu + '/'):
        label = gpu.split('/')[0] + ' ' + intake.GPUS[gpu]
    else:
        label = 'Pending classification'
    version = proposal['claimed_version'] or 'Unidentified release'
    relative = prefix + folder[len(intake.ROOT):] + '/README.md'
    return (f'- [{label} / {version} / Issue #{proposal["issue"]}]({relative}) '
            f'— **UNVERIFIED** (`{proposal["state"]}`); maintainer review required.')


def update_index(source, proposal, anchor, prefix):
    """Insert one pending entry within a small, explicitly managed Markdown region.

    Historical curated reports and all prose outside the markers are byte-preserved.
    Fail closed if a maintainer removed a marker, changed its format or duplicated an Issue.
    """
    intake.need(type(source) is bytes and len(source) <= 128 * 1024, 'INDEX_FORMAT')
    try:
        body = source.decode('utf-8')
    except UnicodeError:
        raise intake.Refused('INDEX_FORMAT') from None
    intake.need(body.endswith('\n') and '\r' not in body, 'INDEX_FORMAT')
    entry = index_entry(proposal, prefix)
    if INDEX_START not in body and INDEX_END not in body:
        bootstrap = INDEX_BOOTSTRAP.get(prefix)
        intake.need(bootstrap is not None and git_blob(source) == bootstrap[0], 'INDEX_FORMAT')
        anchor = bootstrap[1]
        intake.need(body.count(anchor) == 1, 'INDEX_ANCHOR')
        block = ('\n## Automated community intake — UNVERIFIED\n\n' + INDEX_START +
                 '\n' + entry + '\n' + INDEX_END + '\n\n' + INDEX_NOTE + '\n')
        updated = body.replace(anchor, block + anchor, 1).encode('utf-8')
        intake.need(len(updated) <= 128 * 1024, 'INDEX_FORMAT')
        return updated
    intake.need(body.count(INDEX_START) == 1 and body.count(INDEX_END) == 1, 'INDEX_FORMAT')
    start = body.index(INDEX_START) + len(INDEX_START)
    stop = body.index(INDEX_END)
    intake.need(start < stop and body[start] == '\n' and body[stop-1] == '\n', 'INDEX_FORMAT')
    entries = body[start+1:stop-1]
    intake.need(not entries or all(line.startswith('- [') and ') — **UNVERIFIED** (' in line
                                   for line in entries.split('\n')), 'INDEX_FORMAT')
    intake.need('/issue-' + str(proposal['issue']) + '/README.md)' not in entries, 'INDEX_DUPLICATE')
    updated = (body[:start+1] + entry + '\n' + entries + ('\n' if entries else '') +
               body[stop:]).encode('utf-8')
    intake.need(len(updated) <= 128 * 1024, 'INDEX_FORMAT')
    return updated


def indexed_files(proposal, api, entries):
    """Return result artifacts plus two guarded updates to existing public indexes."""
    files = intake.render(proposal)
    for path, (anchor, prefix) in INDEXES.items():
        found = [row for row in entries if row.get('path') == path]
        intake.need(len(found) == 1 and found[0].get('type') == 'blob' and
                    found[0].get('mode') == '100644', 'INDEX_BASE')
        object_id = sha(found[0].get('sha'))
        data = api.get('git/blobs/' + object_id)
        intake.need(type(data) is dict and data.get('encoding') == 'base64' and
                    type(data.get('content')) is str and
                    type(data.get('size')) is int and 0 <= data['size'] <= 128 * 1024 and
                    sha(data.get('sha')) == object_id, 'INDEX_BLOB')
        try:
            raw = base64.b64decode(data['content'].replace('\n', '').replace('\r', ''),
                                   validate=True)
        except (ValueError, binascii.Error):
            raise intake.Refused('INDEX_BLOB') from None
        intake.need(len(raw) == data['size'] and git_blob(raw) == object_id, 'INDEX_BLOB')
        files[path] = update_index(raw, proposal, anchor, prefix)
    return files


def check_current_source(api, proposal, manual):
    """Read the current Issue and require eligibility plus the prepared content revision.

    Return the matching fingerprint. A change/read/eligibility refusal stops
    new-ref publication or strict orphan recovery; this GET is not an atomic
    lock on future Issue edits and performs no writes.
    """
    current = api.get('issues/' + str(proposal['issue']))
    intake.eligible(current, manual)
    revision = intake.issue_fingerprint(current)
    intake.need(revision == proposal['source_revision'], 'SOURCE_CHANGED')
    return revision


def observe_after_new_ref(api, proposal, manual):
    """Return a source/eligibility observation for an already-created new ref.

    A later edit or revoked eligibility becomes STALE; unreadable/malformed
    observations become UNKNOWN without copying raw errors. This annotation
    does not block the draft attempt or replace its pinned data. Subsequent
    PR API failures can still leave an orphan requiring separate recovery.
    """
    try:
        current = api.get('issues/' + str(proposal['issue']))
        revision = intake.issue_fingerprint(current)
        try:
            intake.eligible(current, manual)
        except intake.Refused as error:
            if str(error) in ('NOT_ELIGIBLE', 'AWAITING_INTAKE_APPROVAL'):
                return {'revision': revision, 'status': 'STALE', 'eligibility': 'INELIGIBLE'}
            raise
        return {'revision': revision,
                'status': 'MATCH_AT_CHECK' if revision == proposal['source_revision'] else 'STALE',
                'eligibility': 'ELIGIBLE'}
    except (intake.Refused, OSError, KeyError, TypeError, AttributeError, ValueError,
            OverflowError, RecursionError):
        # Do not copy API errors or raw Issue content into the public PR.
        return {'revision': None, 'status': 'UNKNOWN', 'eligibility': 'UNKNOWN'}


def publish(proposal, api, expected_issue, manual=False):
    """Propose validated result files on a fixed branch and create only an UNVERIFIED draft PR.

    proposal is revalidated before any api call. Existing records/PRs return
    idempotent statuses; unchanged orphan recovery checks exact bytes/history
    and fresh source permission. New branches recheck the Issue immediately
    before refs, then annotate later source changes in the pinned draft body.
    Return a status mapping or raise Refused/API errors. Partial failures may
    leave objects/refs; no force-update, merge, approval or Issue close occurs.
    """
    intake.validate_proposal(proposal)
    intake.need(proposal['issue'] == expected_issue, 'ISSUE_NUMBER_MISMATCH')
    check_current_source(api, proposal, manual)
    head = api.get('git/ref/heads/main')
    base = sha(head['object']['sha'])
    parent = api.get('git/commits/' + base)
    entries = tree_entries(api, parent['tree']['sha'])
    if existing_issue(entries, expected_issue):
        return {'status': 'ALREADY_RECORDED', 'issue': expected_issue}
    if expected_issue in intake.LEGACY:
        # Issue #4 has centralized curated data without a legacy issue-4.md page.
        return {'status': 'CURATED_MANUAL_MIGRATION', 'issue': expected_issue}
    branch = 'community/benchmark-issue-' + str(expected_issue)
    requests = api.get('pulls?state=all&head=GoblinFlash:' + branch + '&per_page=100')
    intake.need(type(requests) is list and len(requests) < 100, 'PR_LIST_LIMIT')
    if requests:
        return {'status': 'EXISTING_PR_REQUIRES_REVIEW', 'issue': expected_issue}
    previous = get_optional(api, 'git/ref/heads/' + branch)
    prior_commit = None
    if previous:
        previous_sha = sha(previous['object']['sha'])
        prior_commit = api.get('git/commits/' + previous_sha)
        intake.need(len(prior_commit.get('parents', [])) == 1, 'EXISTING_BRANCH_CHANGED')
        prior_base = sha(prior_commit['parents'][0]['sha'])
        if prior_base != base:
            ancestry = api.get('compare/' + prior_base + '...' + base)
            intake.need(ancestry.get('merge_base_commit', {}).get('sha') == prior_base and
                        ancestry.get('behind_by') == 0, 'EXISTING_BRANCH_CHANGED')
            old_parent = api.get('git/commits/' + prior_base)
            source_entries = tree_entries(api, old_parent['tree']['sha'])
        else:
            source_entries = entries
    else:
        source_entries = entries
    files = indexed_files(proposal, api, source_entries)
    names = set(files)
    for row in entries:
        path = row.get('path', '')
        intake.need((path not in names or path in INDEXES) and
                    not any(name.startswith(path+'/') and row.get('type') != 'tree'
                            for name in names), 'BASE_OUTPUT_COLLISION')
    plan = intake.digest(intake.json_bytes({path: intake.digest(data) for path, data in sorted(files.items())}))
    message = ('Propose unverified community result for Issue #' + str(expected_issue) +
               '\n\nsource:' + proposal['source_revision'] + '\ncontent:' + plan)
    if previous:
        # Recover only an unchanged orphan created by the exact same proposal.
        previous_commit = prior_commit
        intake.need(previous_commit.get('message') == message, 'EXISTING_BRANCH_CHANGED')
        diff = api.get('compare/' + prior_base + '...' + previous_sha)
        intake.need(type(diff.get('files')) is list and
                    {x['filename'] for x in diff['files']} == names and
                    all(x['status'] == ('modified' if x['filename'] in INDEXES else 'added')
                        for x in diff['files']), 'EXISTING_BRANCH_CHANGED')
        previous_entries = {x['path']: x for x in tree_entries(api, previous_commit['tree']['sha'])}
        intake.need(all(previous_entries.get(path, {}).get('sha') == git_blob(data) and
                        previous_entries[path].get('mode') == '100644' for path, data in files.items()),
                    'EXISTING_BRANCH_CHANGED')
        # A pre-existing orphan is recoverable only while source and permission match.
        revision = check_current_source(api, proposal, manual)
        snapshot_sha = previous_sha
        observation = {'revision': revision, 'status': 'MATCH_AT_CHECK', 'eligibility': 'ELIGIBLE'}
        observation_point = 'ORPHAN_RECOVERY_PREFLIGHT'
    else:
        check_current_source(api, proposal, manual)
        tree = []
        for path, data in sorted(files.items()):
            blob = api.post('git/blobs', {'content': data.decode(), 'encoding': 'utf-8'})
            intake.need(sha(blob['sha']) == git_blob(data), 'API_BLOB_MISMATCH')
            tree.append({'path': path, 'type': 'blob', 'mode': '100644', 'sha': blob['sha']})
        created_tree = api.post('git/trees', {'base_tree': sha(parent['tree']['sha']), 'tree': tree})
        commit = api.post('git/commits', {'message': message, 'tree': sha(created_tree['sha']), 'parents': [base]})
        snapshot_sha = sha(commit['sha'])
        # No API call may intervene between this hard gate and creating the ref.
        check_current_source(api, proposal, manual)
        created_ref = api.post('git/refs', {'ref': 'refs/heads/' + branch, 'sha': snapshot_sha})
        intake.need(sha(created_ref['object']['sha']) == snapshot_sha, 'API_REF_MISMATCH')
        observation = observe_after_new_ref(api, proposal, manual)
        observation_point = 'AFTER_NEW_REF'
    url = 'https://github.com/' + intake.REPOSITORY + '/issues/' + str(expected_issue)
    body = ('**UNVERIFIED — maintainer review and explicit owner approval required.**\n\n'
            'Source: [Issue #' + str(expected_issue) + '](' + url + ').\n\n'
            'Intake state: `' + proposal['state'] + '`; reason: `' + proposal['reason'] + '`.\n\n'
            '| Snapshot and source observation | Value |\n| --- | --- |\n'
            '| Prepared Issue revision (content SHA-256) | `' + proposal['source_revision'] + '` |\n'
            '| Observed Issue revision (content SHA-256) | `' + (observation['revision'] or 'NOT_AVAILABLE') + '` |\n'
            '| Source status | `' + observation['status'] + '` |\n'
            '| Eligibility at observation | `' + observation['eligibility'] + '` |\n'
            '| Observation point | `' + observation_point + '` |\n'
            '| Snapshot commit | `' + snapshot_sha + '` |\n'
            '| Bundle SHA-256 | `' + (proposal['bundle_sha256'] or 'NOT_RECORDED') + '` |\n\n'
            'This draft contains the pinned prepared snapshot. STALE or UNKNOWN source observations '
            'require explicit reconciliation before acceptance. MATCH_AT_CHECK describes one observation, '
            'not an atomic guarantee: compare the live Issue and these fingerprints during review.\n\n'
            'Check the exact GPU/release, raw provenance, clock model, background contention, '
            'negative evidence and privacy. Exported consistency is not independent GPU qualification. '
            'This workflow never merges, approves or closes the Issue.\n\n'
            'Source edits/reopened events do not overwrite this draft; reconcile changed submissions manually.')
    result = api.post('pulls', {'base': 'main', 'head': branch, 'draft': True,
        'title': 'UNVERIFIED community result #' + str(expected_issue), 'body': body})
    return {'status': 'DRAFT_PR_CREATED', 'issue': expected_issue,
            'number': intake.integer(result['number'], 1, 2**31-1), 'files': sorted(files),
            'source_status': observation['status'], 'snapshot_commit': snapshot_sha}


def main(argv=None):
    """Run the workflow publisher only with --apply and the fixed repository identity.

    Read bounded event/proposal files, revalidate them and construct a writable
    API client before publish. Print its status JSON and return zero; refusals
    propagate to the sanitized command error handler. --apply is a capability
    switch, not a replacement for deployment/owner approval.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event', type=Path, required=True)
    parser.add_argument('--proposal', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='explicit write capability; use only after deployment GO')
    args = parser.parse_args(argv)
    intake.need(args.apply and os.environ.get('GITHUB_REPOSITORY') == intake.REPOSITORY, 'WRITE_NOT_AUTHORIZED')
    intake.need(args.proposal.stat().st_size <= intake.MAX_PROPOSAL, 'JSON_LIMIT')
    proposal = intake.validate_proposal(intake.load_json(args.proposal.read_bytes()))
    event = intake.load_json(args.event.read_bytes(), intake.MAX_API)
    issue_number, manual = intake.event_issue(event)
    api = intake.GitHub(os.environ.get('GH_TOKEN'), writable=True)
    result = publish(proposal, api, issue_number, manual)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (intake.Refused, OSError, KeyError, TypeError, ValueError) as error:
        print('Draft proposal refused: ' + (str(error) if isinstance(error, intake.Refused) else 'INPUT_OR_API_FORMAT'))
        raise SystemExit(1)
