#!/usr/bin/env python3
"""Typed-data-only draft PR writer. Never downloads, executes, merges or approves."""
import argparse
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
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def sha(value):
    intake.need(type(value) is str and re.fullmatch('[0-9a-f]{40}', value), 'API_SHA')
    return value


def get_optional(api, endpoint):
    try:
        return api.get(endpoint)
    except intake.Refused as error:
        if str(error) == 'API_404':
            return None
        raise


def tree_entries(api, tree_sha):
    result = api.get('git/trees/' + sha(tree_sha) + '?recursive=1')
    intake.need(result.get('truncated') is False and type(result.get('tree')) is list and
                len(result['tree']) <= 10000, 'TREE_LIMIT')
    return result['tree']


def existing_issue(entries, issue_number):
    pattern = re.compile(r'^Experiment Results/Community/(?:[^/]+/)*issue-' + str(issue_number) +
                         r'(?:-submission)?(?:\.md|/(?:README\.md|record\.json))$')
    return any(type(row.get('path')) is str and pattern.fullmatch(row['path']) for row in entries)


def check_current_source(api, proposal, manual):
    """Hard gate before new refs, and before recovering an existing orphan."""
    current = api.get('issues/' + str(proposal['issue']))
    intake.eligible(current, manual)
    revision = intake.issue_fingerprint(current)
    intake.need(revision == proposal['source_revision'], 'SOURCE_CHANGED')
    return revision


def observe_after_new_ref(api, proposal, manual):
    """Annotate the already-created snapshot; late changes cannot strand its PR."""
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
    """All writes are bounded additions on a new branch; existing bytes never change."""
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
    files = intake.render(proposal)
    names = set(files)
    for row in entries:
        path = row.get('path', '')
        intake.need(path not in names and not any(name.startswith(path+'/') and row.get('type') != 'tree'
                                                 for name in names), 'BASE_OUTPUT_COLLISION')
    branch = 'community/benchmark-issue-' + str(expected_issue)
    requests = api.get('pulls?state=all&head=GoblinFlash:' + branch + '&per_page=100')
    intake.need(type(requests) is list and len(requests) < 100, 'PR_LIST_LIMIT')
    if requests:
        return {'status': 'EXISTING_PR_REQUIRES_REVIEW', 'issue': expected_issue}
    plan = intake.digest(intake.json_bytes({path: intake.digest(data) for path, data in sorted(files.items())}))
    message = ('Propose unverified community result for Issue #' + str(expected_issue) +
               '\n\nsource:' + proposal['source_revision'] + '\ncontent:' + plan)
    previous = get_optional(api, 'git/ref/heads/' + branch)
    if previous:
        # Recover only an unchanged orphan created by the exact same proposal.
        previous_sha = sha(previous['object']['sha'])
        previous_commit = api.get('git/commits/' + previous_sha)
        intake.need(previous_commit.get('message') == message and
                    len(previous_commit.get('parents', [])) == 1, 'EXISTING_BRANCH_CHANGED')
        prior_base = sha(previous_commit['parents'][0]['sha'])
        if prior_base != base:
            ancestry = api.get('compare/' + prior_base + '...' + base)
            intake.need(ancestry.get('merge_base_commit', {}).get('sha') == prior_base and
                        ancestry.get('behind_by') == 0, 'EXISTING_BRANCH_CHANGED')
        diff = api.get('compare/' + prior_base + '...' + previous_sha)
        intake.need(type(diff.get('files')) is list and
                    {x['filename'] for x in diff['files']} == names and
                    all(x['status'] == 'added' for x in diff['files']), 'EXISTING_BRANCH_CHANGED')
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
