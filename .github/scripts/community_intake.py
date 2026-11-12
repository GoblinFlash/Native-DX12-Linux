#!/usr/bin/env python3
"""Bounded, data-only community intake. It never executes or extracts attachments."""
import argparse
import collections
import csv
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

REPOSITORY = 'GoblinFlash/Native-DX12-Linux'
ROOT = 'Experiment Results/Community/'
MAX_COMPRESSED = 8 * 1024 * 1024
MAX_EXPANDED = 16 * 1024 * 1024
MAX_MEMBER = 2 * 1024 * 1024
MAX_MEMBERS = 64
MAX_PROPOSAL = 128 * 1024
MAX_ISSUE = 64 * 1024
MAX_API = 2 * 1024 * 1024
MAX_PROCESSES = 189
TRANSIENT_ATTACHMENT = frozenset(('ATTACHMENT_UNAVAILABLE', 'ATTACHMENT_TIMEOUT'))
SUITES = ('compute', 'd4', 'k', 'kw')
STATUSES = ('VERIFIED', 'FAIL', 'HELD', 'NOT_RUN', 'UNKNOWN')
CLOCK_MODES = ('UNCHANGED', 'UNCHANGED_UNKNOWN', 'LOCKED', 'LOCK_REQUESTED', 'MANUAL', 'NOT_RECORDED')
FILES = frozenset(('run.json', 'summary.txt', 'processes.csv', 'samples.csv',
    'compute-vulkan-samples.csv', 'test1-d4-processes.csv', 'test1-d4-vulkan-processes.csv',
    'test2-k-processes.csv', 'test2-k-vulkan-processes.csv', 'test3-kw-processes.csv',
    'test3-kw-vulkan-processes.csv', 'charts.html', 'charts/results.svg',
    'charts/d4-chart.svg', 'charts/k-chart.svg', 'charts/kw-chart.svg'))
GPU_NAMES = (
    'RTX 4090', 'RTX 4090 Laptop GPU', 'RTX 4090 D', 'RTX 4080', 'RTX 4080 Super',
    'RTX 4080 Laptop GPU', 'RTX 4070', 'RTX 4070 Ti', 'RTX 4070 Super',
    'RTX 4070 Ti Super', 'RTX 4070 Laptop GPU', 'RTX 4060', 'RTX 4060 Ti',
    'RTX 4060 Laptop GPU', 'RTX 4050 Laptop GPU', 'RTX 3090', 'RTX 3090 Ti',
    'RTX 3080', 'RTX 3080 Ti', 'RTX 3080 Laptop GPU', 'RTX 3080 Ti Laptop GPU',
    'RTX 3070', 'RTX 3070 Ti', 'RTX 3070 Laptop GPU', 'RTX 3070 Ti Laptop GPU',
    'RTX 3060', 'RTX 3060 Ti', 'RTX 3060 Laptop GPU', 'RTX 3050',
    'RTX 3050 Laptop GPU', 'RTX 3050 Ti Laptop GPU', 'RTX 3050 A Laptop GPU',
    'RTX 5090', 'RTX 5090 D', 'RTX 5090 Laptop GPU', 'RTX 5080', 'RTX 5080 Laptop GPU',
    'RTX 5070', 'RTX 5070 Ti', 'RTX 5070 Laptop GPU', 'RTX 5070 Ti Laptop GPU',
    'RTX 5060', 'RTX 5060 Ti', 'RTX 5060 Laptop GPU')
GPUS = {'NVIDIA/' + name.replace(' ', '_'): name for name in GPU_NAMES}
GPUS.update({'AMD/RX_7900_XTX': 'RX 7900 XTX', 'Intel/Arc_A770': 'Arc A770'})
LEGACY = {2: ('NVIDIA/RTX_4060_Laptop_GPU', 'v0.1.4'),
          3: ('NVIDIA/RTX_3060_Ti', 'v0.1.4'),
          4: ('NVIDIA/RTX_3060', 'v0.1.4'), 5: ('NVIDIA/RTX_3090', 'v0.1.4')}
CATALOG_PATH = Path(__file__).with_name('community_releases.json')
# A numeric filename prefix is a bounded hint only, never GPU identity or a path.
ATTACHMENT_URL_PATTERN = re.compile(
    r'https://github\.com/user-attachments/files/[1-9][0-9]{0,19}/'
    r'(?:[1-9][0-9]{2,3}-)?share-results'
    r'(?:-v[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})?\.tar\.gz')


class Refused(Exception):
    """Stable, non-sensitive reason code, never untrusted exception text."""


def need(condition, reason):
    """Require condition to be true; otherwise raise Refused with the fixed reason code."""
    if not condition:
        raise Refused(reason)


def integer(value, low=0, high=10**15):
    """Return a plain int inside inclusive low/high bounds; reject bools and other types."""
    need(type(value) is int and low <= value <= high, 'INTEGER_RANGE')
    return value


def number(value, low=0, high=10**15):
    """Return a finite int or float inside inclusive bounds, or raise NUMBER_RANGE."""
    need(type(value) in (int, float) and math.isfinite(value) and low <= value <= high, 'NUMBER_RANGE')
    return value


def enum(value, choices, reason='ENUM'):
    """Return an allowlisted string value; reject other types with the supplied reason."""
    need(type(value) is str and value in choices, reason)
    return value


def digest(data):
    """Return the lowercase SHA-256 hex digest of the supplied bytes."""
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    """Serialize JSON as deterministic UTF-8 bytes; refuse nonfinite numbers."""
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def load_json(raw, limit=MAX_PROPOSAL):
    """Decode bounded UTF-8 JSON with duplicate-key and numeric limits.

    raw is a byte string and limit is its maximum length. Return the decoded
    value; invalid encoding, syntax, depth, keys or numbers raise fixed Refused
    codes. Decoder hooks below never include raw input in an error.
    """
    need(len(raw) <= limit, 'JSON_LIMIT')
    def pairs(rows):
        """Build one decoded object while rejecting repeated keys instead of overwriting them."""
        result = {}
        for key, value in rows:
            need(key not in result, 'JSON_DUPLICATE_KEY')
            result[key] = value
        return result
    def parse_int(value):
        """Decode a JSON integer token only when its text is at most 18 characters."""
        need(len(value) <= 18, 'JSON_NUMBER_LIMIT')
        return int(value)
    def parse_float(value):
        """Decode a bounded JSON float token and reject overflow or nonfinite results."""
        need(len(value) <= 64, 'JSON_NUMBER_LIMIT')
        result = float(value)
        need(math.isfinite(result), 'JSON_NUMBER_LIMIT')
        return result
    def constant(_):
        """Reject JSON NaN/Infinity constants with a non-sensitive numeric-limit reason."""
        raise Refused('JSON_NUMBER_LIMIT')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_int=parse_int, parse_float=parse_float, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError):
        raise Refused('JSON_FORMAT') from None


def catalog():
    """Read and decode the release catalogue stored beside this script."""
    return load_json(CATALOG_PATH.read_bytes())


def gpu_category(value):
    """Resolve a bounded GPU name to a fixed category, or return None.

    Only the corresponding vendor family's optional prefixes are accepted.
    Whitespace/case, the bounded PCI suffix and Laptop alias are normalized;
    Ti, Super, D and Laptop identities are never merged.
    """
    if type(value) is not str or len(value) > 160:
        return None
    value = re.sub(r' \(PCI [0-9a-f]{4}:[0-9a-f]{4}\)$', '', value, flags=re.I)
    value = ' '.join(value.split()).casefold()
    # Laptop aliases remain Laptop; no suffix or model is discarded.
    if value.endswith(' laptop'):
        value += ' gpu'
    prefixes = {'NVIDIA': r'(?:nvidia )?(?:geforce )?', 'AMD': r'(?:amd )?(?:radeon )?',
                'Intel': r'(?:intel )?'}
    for key, name in GPUS.items():
        vendor = key.split('/')[0]
        canonical = name.casefold()
        if re.fullmatch(prefixes[vendor] + re.escape(canonical), value):
            return key
        # NVIDIA's GeForce brand is an explicit disambiguator for a missing RTX
        # prefix. Do not accept bare numbers or alter Ti/Super/D/Laptop suffixes.
        if vendor == 'NVIDIA' and canonical.startswith('rtx ') and re.fullmatch(
                r'(?:nvidia )?geforce ' + re.escape(canonical[4:]), value):
            return key
    return None


def gpu_pci(gpu, value):
    """Return a canonical vendor/device ID consistent with pinned NVIDIA model data.

    Refuse malformed, unknown and contradictory IDs separately. This checks
    self-reported field consistency only; subsystem identity, physical hardware,
    execution and provenance are not authenticated. Unmapped models fail closed.
    """
    need(type(value) is str and re.fullmatch('[0-9a-f]{4}:[0-9a-f]{4}', value, re.I),
         'GPU_PCI_FORMAT')
    value = value.lower()
    data = load_json(Path(__file__).with_name('community_gpu_pci.json').read_bytes(), MAX_MEMBER)
    need(type(data) is dict and data.get('schema') == 'ndx12.gpu-pci.v1' and
         type(data.get('models')) is dict, 'PROPOSAL_SCHEMA')
    models = data['models']
    need(all(key in GPUS and key.startswith('NVIDIA/') and type(ids) is list and
             0 < len(ids) <= 32 and len(set(ids)) == len(ids) and
             all(type(x) is str and re.fullmatch('10de:[0-9a-f]{4}', x) for x in ids)
             for key, ids in models.items()), 'PROPOSAL_SCHEMA')
    need(gpu in models and any(value in ids for ids in models.values()), 'GPU_PCI_UNVERIFIED')
    need(value in models[gpu], 'GPU_PCI_MISMATCH')
    return value


def issue_fields(issue):
    """Parse a bounded Issue body into unique Markdown heading/value fields.

    Return stripped field text. Malformed bodies, excess bytes or duplicate
    headings raise Refused; no field content is executed or treated as a path.
    """
    need(type(issue) is dict and type(issue.get('body')) is str, 'ISSUE_FORMAT')
    need(len(issue['body'].encode()) <= MAX_ISSUE, 'ISSUE_LIMIT')
    fields, current = {}, None
    for line in issue['body'].splitlines():
        if line.startswith('### '):
            current = line[4:].strip()
            need(current not in fields, 'ISSUE_DUPLICATE_FIELD')
            fields[current] = []
        elif current is not None:
            fields[current].append(line)
    return {name: '\n'.join(lines).strip() for name, lines in fields.items()}


def first_line(value):
    """Return the first nonempty response line, ignoring the form's no-response marker."""
    return next((line.strip() for line in value.splitlines() if line.strip() and line.strip() != '_No response_'), '')


def issue_fingerprint(issue):
    """Hash Issue content/state and only the two intake-eligibility labels.

    Comments, updated_at and unrelated/category labels are excluded so routine
    activity does not invalidate a proposal. Eligibility itself is checked
    separately; this digest is a content revision, not proof of authorization.
    """
    labels = {x if type(x) is str else x['name'] for x in issue.get('labels', [])}
    labels = sorted(labels.intersection(('benchmark:submission', 'benchmark:intake-approved')))
    return digest(json_bytes({'number': issue['number'], 'title': issue['title'],
        'body': issue.get('body', ''), 'state': issue['state'], 'labels': labels}))


def eligible(issue, manual=False):
    """Require an open results Issue, submission label and intake permission.

    manual permits the dispatch route; trusted authors or the approval label
    permit normal Issue intake. Return None on success, or raise a fixed
    eligibility refusal. Processing permission never accepts benchmark claims.
    """
    integer(issue.get('number'), 1, 2**31-1)
    need('pull_request' not in issue, 'NOT_ELIGIBLE')
    need(type(issue.get('title')) is str and issue['title'].startswith('[Results]') and
         issue.get('state') == 'open', 'NOT_ELIGIBLE')
    labels = [x if type(x) is str else x['name'] for x in issue.get('labels', [])]
    need('benchmark:submission' in labels, 'NOT_ELIGIBLE')
    trusted = issue.get('author_association') in ('OWNER', 'MEMBER', 'COLLABORATOR')
    need(manual or trusted or 'benchmark:intake-approved' in labels, 'AWAITING_INTAKE_APPROVAL')


def attachment_url(issue):
    """Return the one distinct attachment URL matching the bounded filename grammar.

    Missing or multiple supported URLs raise Refused. A GPU filename prefix
    is accepted only as a filename hint and never establishes hardware identity.
    """
    urls = set(re.findall(r'https://github\.com/user-attachments/files/[0-9]+/[A-Za-z0-9_.-]+', issue['body']))
    urls = {url for url in urls if ATTACHMENT_URL_PATTERN.fullmatch(url)}
    need(len(urls) == 1, 'ATTACHMENT_MISSING' if not urls else 'ATTACHMENT_AMBIGUOUS')
    return urls.pop()


DOWNLOAD_HOSTS = frozenset(('github.com', 'objects.githubusercontent.com',
    'github-production-user-asset-6210df.s3.amazonaws.com'))


def safe_download_url(url):
    """Require HTTPS, an allowlisted host and no credentials, fragment or foreign port."""
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        raise Refused('ATTACHMENT_URL') from None
    need(parsed.scheme == 'https' and parsed.hostname in DOWNLOAD_HOSTS and
         port in (None, 443) and not parsed.username and not parsed.password and
         not parsed.fragment, 'ATTACHMENT_URL')


class DownloadRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        """Initialize a fresh per-download redirect counter."""
        self.count = 0
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        """Validate each redirected URL and refuse chains longer than three hops."""
        self.count += 1
        need(self.count <= 3, 'ATTACHMENT_REDIRECT_LIMIT')
        safe_download_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download(url, opener=None):
    """Fetch one supported attachment URL using bounded, unauthenticated reads.

    An injected opener supports CPU tests; the default opener ignores proxy
    settings and validates redirects. Enforce compressed-byte and read-time
    budgets. Return bytes; permanent HTTP absence and transient transport
    failures use distinct fixed Refused codes. Nothing is extracted or run.
    """
    need(ATTACHMENT_URL_PATTERN.fullmatch(url), 'ATTACHMENT_URL')
    safe_download_url(url)
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), DownloadRedirects())
    request = urllib.request.Request(url, headers={'User-Agent': 'ndx12-community-intake/1', 'Accept': 'application/octet-stream'})
    result = bytearray()
    started = time.monotonic()
    try:
        with opener.open(request, timeout=15) as response:
            safe_download_url(response.geturl())
            length = response.headers.get('Content-Length')
            need(length is None or (length.isdigit() and int(length) <= MAX_COMPRESSED), 'COMPRESSED_LIMIT')
            while True:
                need(time.monotonic() - started < 45, 'ATTACHMENT_TIMEOUT')
                block = response.read(min(65536, MAX_COMPRESSED + 1 - len(result)))
                if not block:
                    break
                result.extend(block)
                need(len(result) <= MAX_COMPRESSED, 'COMPRESSED_LIMIT')
    except urllib.error.HTTPError as error:
        raise Refused('ATTACHMENT_GONE' if error.code in (404, 410) else 'ATTACHMENT_UNAVAILABLE') from None
    except (OSError, urllib.error.URLError, ValueError):
        raise Refused('ATTACHMENT_UNAVAILABLE') from None
    return bytes(result)


def octal(raw):
    """Decode a nonempty ASCII octal tar-header field, or raise TAR_NUMBER."""
    value = raw.rstrip(b'\0 ').lstrip(b' ')
    need(bool(value) and re.fullmatch(b'[0-7]+', value), 'TAR_NUMBER')
    return int(value, 8)


def read_share_members(compressed):
    """Read supported JSON/CSV members from a bounded gzip/tar byte string.

    Return a dictionary of allowlisted relative names to bytes. Validate all
    headers, checksums, sizes, member counts and supported mtime-only PAX data;
    reject links, path overrides, duplicate files and malformed trailers.
    Uploaded prose/graphics are ignored. No filesystem extraction or code
    execution occurs, and unsupported input raises a fixed Refused code.
    """
    need(0 < len(compressed) <= MAX_COMPRESSED, 'COMPRESSED_LIMIT')
    try:
        decoder = zlib.decompressobj(31)
        raw = decoder.decompress(compressed, MAX_EXPANDED + 1)
        need(len(raw) <= MAX_EXPANDED and not decoder.unconsumed_tail, 'EXPANDED_LIMIT')
        need(decoder.eof and not decoder.unused_data, 'GZIP_FORMAT')
    except zlib.error:
        raise Refused('GZIP_FORMAT') from None
    need(len(raw) % 512 == 0, 'TAR_TRUNCATED')
    position, count, files, seen = 0, 0, {}, set()
    pending_pax = False
    while position + 512 <= len(raw):
        header = raw[position:position+512]
        if not any(header):
            need(len(raw)-position >= 1024 and not any(raw[position:]) and not pending_pax, 'TAR_TRAILER')
            return files
        count += 1
        need(count <= MAX_MEMBERS, 'MEMBER_COUNT')
        need(octal(header[148:156]) == sum(header[:148]) + 256 + sum(header[156:]), 'TAR_CHECKSUM')
        need(header[257:263] in (b'ustar\0', b'ustar '), 'TAR_FORMAT')
        size = octal(header[124:136])
        need(size <= MAX_MEMBER, 'MEMBER_SIZE')
        position += 512
        end = position + size
        need(end <= len(raw), 'TAR_TRUNCATED')
        content = raw[position:end]
        position += ((size + 511) // 512) * 512
        kind = header[156:157]
        if kind == b'x':
            need(not pending_pax and size <= 1024, 'PAX_LIMIT')
            # Python tar.add emits fractional mtime. Never accept a path/link/size override.
            offset = 0
            while offset < len(content):
                space = content.find(b' ', offset, offset+8)
                need(space > offset and content[offset:space].isdigit(), 'PAX_FORMAT')
                length = int(content[offset:space])
                need(0 < length <= 128 and offset+length <= len(content), 'PAX_LIMIT')
                record = content[space+1:offset+length]
                need(re.fullmatch(b'mtime=[0-9]{1,12}(?:\\.[0-9]{1,9})?\n', record), 'PAX_FIELD')
                offset += length
            pending_pax = True
            continue
        need(kind in (b'0', b'\0', b'5') and not any(header[157:257]), 'TAR_TYPE')
        pending_pax = False
        try:
            name = header[:100].split(b'\0', 1)[0].decode('ascii')
            prefix = header[345:500].split(b'\0', 1)[0].decode('ascii')
        except UnicodeError:
            raise Refused('TAR_PATH') from None
        name = prefix + '/' + name if prefix else name
        if name.startswith('./'):
            name = name[2:]
        if kind == b'5':
            need(name.rstrip('/') in ('ndx12-results', 'ndx12-results/charts') and size == 0, 'TAR_DIRECTORY')
            continue
        need(name.startswith('ndx12-results/'), 'TAR_PATH')
        rel = name[len('ndx12-results/'):]
        need(rel in FILES, 'MEMBER_NOT_ALLOWLISTED')
        need(rel not in seen, 'DUPLICATE_MEMBER')
        seen.add(rel)
        # HTML and uploaded images are intentionally never parsed or copied.
        if rel.endswith('.csv') or rel == 'run.json':
            files[rel] = content
    raise Refused('TAR_TRAILER')


REASONS = frozenset(('OK', 'INPUT_FORMAT', 'ISSUE_FORMAT', 'ISSUE_LIMIT',
    'ISSUE_DUPLICATE_FIELD', 'GPU_UNKNOWN', 'GPU_MISMATCH', 'GPU_PCI_FORMAT',
    'GPU_PCI_UNVERIFIED', 'GPU_PCI_MISMATCH', 'VERSION_UNKNOWN',
    'VERSION_MISMATCH', 'IDENTITY_MISMATCH', 'DRIVER_MISMATCH', 'RUN_CLAIM_MISMATCH',
    'ATTACHMENT_MISSING', 'ATTACHMENT_AMBIGUOUS', 'ATTACHMENT_URL',
    'ATTACHMENT_REDIRECT_LIMIT', 'ATTACHMENT_UNAVAILABLE', 'ATTACHMENT_TIMEOUT', 'ATTACHMENT_GONE',
    'COMPRESSED_LIMIT', 'EXPANDED_LIMIT', 'GZIP_FORMAT', 'MEMBER_COUNT',
    'MEMBER_SIZE', 'TAR_TRUNCATED', 'TAR_TRAILER', 'TAR_CHECKSUM', 'TAR_FORMAT',
    'TAR_NUMBER', 'TAR_PATH', 'TAR_TYPE', 'TAR_DIRECTORY', 'PAX_LIMIT',
    'PAX_FORMAT', 'PAX_FIELD', 'MEMBER_NOT_ALLOWLISTED', 'DUPLICATE_MEMBER',
    'MISSING_DATA', 'JSON_LIMIT', 'JSON_FORMAT', 'JSON_DUPLICATE_KEY',
    'JSON_NUMBER_LIMIT', 'INTEGER_RANGE', 'NUMBER_RANGE', 'ENUM', 'SCHEMA',
    'CSV_FORMAT', 'CSV_HEADER', 'CSV_LIMIT', 'CSV_VALUE', 'PROCESS_SCHEDULE',
    'PROCESS_CONTRADICTION', 'COUNTS_MISMATCH', 'MEASUREMENT_STATUS_MISMATCH',
    'MEASUREMENTS_MISSING', 'UNITS_MISMATCH', 'CLOCK_FORMAT', 'PROPOSAL_SCHEMA'))
WARNINGS = frozenset(('UNVERIFIED_SUBMISSION', 'NO_INDEPENDENT_GPU_RERUN',
    'RAW_READBACKS_NOT_INCLUDED', 'IDENTITY_SELF_REPORTED', 'BACKGROUND_NOT_ASSESSED',
    'REVIEW_ISSUE_CONTEXT', 'CLOCKS_NOT_PROVEN_PER_DISPATCH', 'SEPARATE_TIMING_UNITS',
    'KERNEL_RECORDS_REPORTED', 'KERNEL_RECORDS_NOT_AVAILABLE', 'NONCOMPLETE_RUN'))
PROCESS_COLUMNS = ['suite', 'case', 'variant', 'path', 'repeat', 'submission',
                   'completion', 'correctness', 'timing', 'kernel_records', 'status']
COMPUTE_COLUMNS = ['case', 'attempt', 'work_ticks', 'empty_ticks', 'clock_mode',
                  'requested_core_mhz', 'requested_memory_mhz', 'telemetry', 'series_status']
FRAME_COLUMNS = ['test', 'shape', 'arm', 'round', 'process_median_ticks', 'first_ticks',
                 'warmup_ticks', 'empty_before_ticks', 'empty_after_ticks', 'clock_mode', 'telemetry']


def claims(issue):
    """Return recognized GPU, release, numeric driver and parsed Issue fields.

    Ambiguous/unsupported identities become None; malformed form structure
    raises Refused. Driver descriptions are bounded and never copied as prose.
    """
    fields = issue_fields(issue)
    gpu = gpu_category(first_line(fields.get('GPU model', '')))
    text = first_line(fields.get('Benchmark version', ''))
    # Capture the entire claimed release token: a stable prefix of a prerelease
    # or patch build must not be mistaken for an approved release.
    versions = set(x.lower() for x in re.findall(
        r'\bv[0-9]+\.[0-9]+\.[0-9]+[^\s,;)]*', text, re.I))
    version = versions.pop() if len(versions) == 1 else None
    version = version if version and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', version) else None
    version = version if version in catalog() else None
    driver = first_line(fields.get('GPU driver version', ''))
    stack = r'(?:NVIDIA )?(?:Open|proprietary)(?: kernel module)?'
    match = re.fullmatch(r'([0-9]{3}\.[0-9]{2}\.[0-9]{2})(?:,? (?:'+stack+r'|\('+stack+r'\)))?', driver, re.I)
    return gpu, version, match.group(1) if match else None, fields


def schedule(suite):
    """Return the exact suite/case/variant/path/repeat keys expected for one known suite."""
    cases = ('affine', 'affine515', 'parallel-sort') if suite == 'compute' else (
        ('128x128', '32x512', '16x1024') if suite == 'd4' else ('64x64', '127x65'))
    variants = {'compute': ('',), 'd4': ('B', 'D4'),
                'k': ('root-scalar', 'root-uint4'),
                'kw': ('wave-root-scalar', 'wave-root-uint4')}[suite]
    return {(suite, case, variant, path, repeat)
            for case in cases for path in ('native', 'vulkan')
            for variant in (variants if path == 'native' else ('',))
            for repeat in range(1, 8)}


def csv_rows(raw, columns):
    """Decode a bounded UTF-8 CSV with exact ordered headers and string fields.

    Return row dictionaries. Field-size and row-count limits are enforced;
    malformed CSV, extra/missing cells or unexpected headers raise Refused.
    """
    need(len(raw) <= MAX_MEMBER, 'CSV_LIMIT')
    csv.field_size_limit(4096)
    try:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8'), newline=''), strict=True)
        need(reader.fieldnames == columns, 'CSV_HEADER')
        result = []
        for row in reader:
            need(len(result) < MAX_PROCESSES and set(row) == set(columns) and
                 all(type(value) is str for value in row.values()), 'CSV_LIMIT')
            result.append(row)
        return result
    except (UnicodeError, csv.Error):
        raise Refused('CSV_FORMAT') from None


def csv_int(value, low=0, high=10**15):
    """Parse a bounded unsigned decimal CSV integer and enforce inclusive value limits."""
    need(type(value) is str and re.fullmatch(r'[0-9]{1,16}', value), 'CSV_VALUE')
    return integer(int(value), low, high)


def exact_timing_number(value):
    """Serialize an admitted finite decimal fraction as an int or exact decimal text.

    value comes from bounded timing validation or median arithmetic. Whole
    values remain integers; other values use canonical decimal strings with
    sufficient precision for the admitted inputs and even-sample medians.
    """
    if value.denominator == 1:
        return value.numerator
    with localcontext() as context:
        context.prec = 64  # At most 36 input digits, or 37 for an even-sample median.
        return format(Decimal(value.numerator) / Decimal(value.denominator), 'f').rstrip('0')


def csv_timing(value, halves=False):
    """Parse a bounded frame timing without exponent notation or binary-float conversion.

    halves restricts native medians to whole or half ticks; otherwise accept
    up to 20 fractional digits for Vulkan ns. Return an int or canonical
    decimal string and reject values outside 0..10^15 with Refused.
    """
    pattern = r'[0-9]{1,16}(?:\.(?:0|5))?' if halves else r'[0-9]{1,16}(?:\.[0-9]{1,20})?'
    need(type(value) is str and re.fullmatch(pattern, value), 'CSV_VALUE')
    result = Fraction(value)
    need(0 <= result <= 10**15, 'INTEGER_RANGE')
    return exact_timing_number(result)


def timing_fraction(value, halves=False):
    """Revalidate a typed timing value and return its exact Fraction representation.

    Accept plain bounded ints or canonical decimal strings produced by
    csv_timing; halves applies the native-median rule. Reject bools, floats,
    noncanonical text and malformed values before writer-side API effects.
    """
    if type(value) is int:
        return Fraction(integer(value))
    need(type(value) is str and csv_timing(value, halves) == value, 'PROPOSAL_SCHEMA')
    return Fraction(value)


def process_key(row):
    """Return the suite/case/variant/path/repeat tuple identifying one process."""
    return tuple(row[name] for name in ('suite', 'case', 'variant', 'path', 'repeat'))


def process_rows(raw, requested):
    """Validate a complete requested process schedule and return sorted typed rows.

    raw is processes.csv bytes and requested lists known suites. Enforce unique
    keys, enum/range limits and cross-field status consistency, including
    NOT_RUN versus completed execution and VERIFIED evidence. Raise Refused
    on contradictions. Preparation and writer revalidation share this check.
    """
    expected = set().union(*(schedule(suite) for suite in requested))
    rows, keys = [], set()
    for row in csv_rows(raw, PROCESS_COLUMNS):
        row['repeat'] = csv_int(row['repeat'], 1, 7)
        key = process_key(row)
        need(key in expected and key not in keys, 'PROCESS_SCHEDULE')
        keys.add(key)
        enum(row['status'], STATUSES)
        enum(row['submission'], ('RETURNED', 'NOT_RECORDED', 'UNKNOWN', 'NOT_RUN', 'FAILED', 'HELD'))
        enum(row['completion'], ('CLOSED', 'EXECUTED', 'NOT_RECORDED', 'UNKNOWN', 'NOT_RUN', 'FAILED', 'HELD'))
        enum(row['correctness'], ('BOUNDED_CORRECTNESS_VERIFIED', 'NOT_RECORDED', 'UNKNOWN', 'NOT_RUN', 'FAILED'))
        enum(row['timing'], ('OK', 'NOT_RECORDED', 'UNKNOWN', 'NOT_RUN', 'FAILED'))
        row['kernel_records'] = None if row['kernel_records'] == '' else csv_int(row['kernel_records'], 0, 100000)
        need(row['status'] != 'NOT_RUN' or row['completion'] not in ('CLOSED', 'EXECUTED'),
             'PROCESS_CONTRADICTION')
        if row['status'] == 'VERIFIED':
            need(row['completion'] == ('CLOSED' if row['path'] == 'native' else 'EXECUTED') and
                 row['correctness'] == 'BOUNDED_CORRECTNESS_VERIFIED' and row['timing'] == 'OK' and
                 row['submission'] not in ('FAILED', 'HELD', 'NOT_RUN') and
                 (row['path'] != 'native' or row['submission'] == 'RETURNED'), 'PROCESS_CONTRADICTION')
        rows.append(row)
    need(keys == expected, 'PROCESS_SCHEDULE')
    return sorted(rows, key=process_key)


def counts(rows, reported):
    """Recalculate process status/completion totals and require matching reported ints."""
    need(type(reported) is dict, 'COUNTS_MISMATCH')
    actual = {'expected': len(rows), **{name: sum(r['status'] == status for r in rows)
        for name, status in zip(('verified', 'failed', 'held', 'not_run', 'unknown'), STATUSES)}}
    for name, value in actual.items():
        need(type(reported.get(name)) is int and reported[name] == value, 'COUNTS_MISMATCH')
    actual['completed'] = sum(row['completion'] in ('CLOSED', 'EXECUTED') for row in rows)
    need(type(reported.get('completed')) is int and reported['completed'] == actual['completed'], 'COUNTS_MISMATCH')
    return actual


def measurements(files, processes):
    """Match exported numeric samples exactly to VERIFIED process rows.

    files contains allowlisted CSV bytes and processes contains validated
    schedule rows. Reject missing/duplicate samples, invalid timing text or
    status mismatches. Return sorted sanitized measurements, keeping native
    ticks and Vulkan ns separate and preserving supported frame fractions.
    """
    result, seen = [], set()
    by_key = {process_key(row): row for row in processes}
    names = [('compute', 'native', 'samples.csv'), ('compute', 'vulkan', 'compute-vulkan-samples.csv')]
    for suite, prefix in [('d4', 'test1-d4'), ('k', 'test2-k'), ('kw', 'test3-kw')]:
        names.extend([(suite, 'native', prefix+'-processes.csv'), (suite, 'vulkan', prefix+'-vulkan-processes.csv')])
    for suite, path, name in names:
        if name not in files:
            continue
        native = path == 'native'
        suffix = 'ticks' if native else 'ns'
        if suite == 'compute':
            columns = COMPUTE_COLUMNS if native else [
                'case', 'attempt', 'work_ns', 'empty_ns', 'order', 'clock_mode',
                'requested_core_mhz', 'requested_memory_mhz', 'telemetry', 'series_status']
        else:
            columns = [x.replace('ticks', suffix) for x in FRAME_COLUMNS]
        for row in csv_rows(files[name], columns):
            if suite == 'compute':
                case, variant, repeat = row['case'], '', csv_int(row['attempt'], 1, 7)
                value = csv_int(row['work_'+suffix])
                csv_int(row['empty_'+suffix])
                for key in ('requested_core_mhz', 'requested_memory_mhz'):
                    if row[key] != '':
                        csv_int(row[key], 0, 100000)
                need(row['series_status'] == 'BOUNDED_SERIES_VERIFIED', 'MEASUREMENT_STATUS_MISMATCH')
                if not native:
                    enum(row['order'], ('native-first', 'vulkan-first'))
            else:
                need(row['test'] == suite, 'CSV_VALUE')
                case, variant = row['shape'], row['arm'] if native else ''
                need(native or row['arm'] == 'vulkan', 'CSV_VALUE')
                repeat = csv_int(row['round'], 0, 6) + 1
                value = csv_timing(row['process_median_'+suffix], halves=native)
                for key in ('first_', 'warmup_', 'empty_before_', 'empty_after_'):
                    if native:
                        csv_int(row[key+suffix])
                    else:
                        csv_timing(row[key+suffix])
            item = {'suite': suite, 'case': case, 'variant': variant, 'path': path,
                    'repeat': repeat, 'value': value, 'unit': 'GPU_TICKS' if native else 'NS',
                    'clock_mode': enum(row['clock_mode'], CLOCK_MODES),
                    'telemetry': enum(row['telemetry'], ('LIVE', 'OFF', 'DISABLED', 'NOT_RECORDED'))}
            key = process_key(item)
            need(key not in seen and key in by_key and by_key[key]['status'] == 'VERIFIED', 'MEASUREMENT_STATUS_MISMATCH')
            seen.add(key)
            result.append(item)
    need(seen == {process_key(p) for p in processes if p['status'] == 'VERIFIED'}, 'MEASUREMENTS_MISSING')
    return sorted(result, key=process_key)


def sanitized_run(run, processes):
    """Validate reported run/step counts against processes and return a sanitized summary.

    Check suite completion/not-started claims, negative outcomes, units and
    reported clock envelopes. Preserve bounded caveats and failure presence,
    not raw private error details. Consistency does not qualify GPU execution
    or establish that reported clocks/provenance are independently verified.
    """
    need(type(run) is dict and run.get('schema') == 'ndx12-share.v2', 'SCHEMA')
    need(type(run.get('units')) is dict and type(run.get('run')) is dict, 'SCHEMA')
    need(run.get('units', {}).get('native') == 'GPU_TICKS' and run.get('units', {}).get('vulkan') == 'NS', 'UNITS_MISMATCH')
    meta = run['run']
    overall = enum(meta['overall'], ('COMPLETE', 'PARTIAL', 'STOPPED', 'FAILED', 'HELD', 'INCOMPLETE', 'UNCERTAIN'))
    clocks = enum(meta['clocks'], ('unchanged', 'locked', 'manual', 'not-recorded'))
    total = counts(processes, run['totals'])
    requested = meta['requested']
    completed, not_started = meta['completed'], meta['not_started']
    for suites in (completed, not_started):
        need(type(suites) is list and all(type(x) is str and x in requested for x in suites) and
             len(set(suites)) == len(suites), 'RUN_CLAIM_MISMATCH')
    need(not set(completed).intersection(not_started), 'RUN_CLAIM_MISMATCH')
    failure_reported = meta['failed'] is not None
    steps = []
    need(type(run['steps']) is list and len(run['steps']) <= 4, 'SCHEMA')
    seen = set()
    for step in run['steps']:
        need(type(step) is dict, 'SCHEMA')
        suite = enum(step['suite'], SUITES)
        need(suite not in seen, 'SCHEMA')
        seen.add(suite)
        subset = [p for p in processes if p['suite'] == suite]
        c = counts(subset, step['counts'])
        status = enum(step['status'], ('COMPLETE', 'PARTIAL', 'STOPPED', 'FAILED', 'HELD', 'NOT_RUN', 'INCOMPLETE', 'UNCERTAIN'))
        need((suite in completed) == (status == 'COMPLETE') and
             (suite not in not_started or status == 'NOT_RUN'), 'RUN_CLAIM_MISMATCH')
        if status == 'COMPLETE':
            need(c['verified'] == c['expected'] == c['completed'], 'COUNTS_MISMATCH')
        elif status == 'NOT_RUN':
            need(c['completed'] == c['verified'] == 0 and c['not_run'] == c['expected'], 'COUNTS_MISMATCH')
        clock = step.get('clock_check', {})
        need(type(clock) is dict, 'SCHEMA')
        q = enum(clock.get('status', 'NOT_RECORDED'), ('QUALIFIED', 'NOT_QUALIFIED', 'NOT_RECORDED'))
        envelope = clock.get('envelope_ns_per_tick')
        if envelope is not None:
            need(type(envelope) is list and len(envelope) == 2, 'CLOCK_FORMAT')
            for value in envelope:
                number(value, 0.000001, 1000)
            need(envelope[0] <= envelope[1], 'CLOCK_FORMAT')
        need(q != 'QUALIFIED' or envelope is not None, 'CLOCK_FORMAT')
        steps.append({'suite': suite, 'status': status, 'counts': c,
                      'reported_clock_qualification': q, 'reported_ns_per_tick_envelope': envelope})
    need(seen == set(meta['requested']) and sum(x['counts']['completed'] for x in steps) == total['completed'], 'COUNTS_MISMATCH')
    if overall == 'COMPLETE':
        need(total['verified'] == total['expected'] == total['completed'], 'COUNTS_MISMATCH')
        need(set(completed) == set(requested) and not not_started and not failure_reported,
             'RUN_CLAIM_MISMATCH')
    return {'overall': overall, 'clocks': clocks, 'failure_reported': failure_reported,
            'counts': total, 'steps': sorted(steps, key=lambda x: x['suite'])}


def base_proposal(issue):
    """Seed a manual-review proposal with Issue identity, revision and recognized claims."""
    try:
        gpu, version, _, _ = claims(issue)
    except Refused:
        gpu, version = None, None
    return {'schema': 'ndx12.community-intake.v2', 'issue': integer(issue['number'], 1, 2**31-1),
            'source_revision': issue_fingerprint(issue), 'bundle_sha256': None,
            'claimed_gpu': gpu, 'claimed_version': version, 'archive_gpu': None,
            'archive_version': None, 'driver': None, 'pci': None, 'state': 'MANUAL_REVIEW',
            'reason': 'INPUT_FORMAT', 'run': None, 'processes': [], 'measurements': [],
            'warnings': sorted(WARNINGS - {'KERNEL_RECORDS_REPORTED', 'KERNEL_RECORDS_NOT_AVAILABLE', 'NONCOMPLETE_RUN'})}


def prepare(issue, compressed=None, fetch=download):
    """Build a sanitized proposal from an Issue and an optional share-bundle byte string.

    When compressed is absent, fetch the single supported attachment using
    fetch. Check claimed identities, schedules, counts and selected numeric
    CSV before returning DATA_READY. Permanent data refusals return a
    MANUAL_REVIEW proposal without measurements; transient download failures
    propagate for retry. No files are written and no benchmark is accepted.
    """
    result = base_proposal(issue)
    try:
        gpu, version, driver, fields = claims(issue)
        need(gpu is not None, 'GPU_UNKNOWN')
        need(version is not None, 'VERSION_UNKNOWN')
        data = compressed if compressed is not None else fetch(attachment_url(issue))
        result['bundle_sha256'] = digest(data)
        files = read_share_members(data)
        need('run.json' in files and 'processes.csv' in files, 'MISSING_DATA')
        run = load_json(files['run.json'], MAX_MEMBER)
        need(type(run) is dict and run.get('schema') == 'ndx12-share.v2', 'SCHEMA')
        need(all(type(run.get(field)) is dict for field in ('gpu', 'identity', 'units', 'run')), 'SCHEMA')
        actual_gpu = gpu_category(run.get('gpu', {}).get('model'))
        actual_version = run.get('identity', {}).get('public_version')
        result['archive_gpu'] = actual_gpu
        result['archive_version'] = actual_version if actual_version in catalog() else None
        need(actual_gpu is not None, 'GPU_UNKNOWN')
        need(actual_gpu == gpu, 'GPU_MISMATCH')
        need(run['gpu'].get('status') == 'RECORDED', 'GPU_PCI_UNVERIFIED')
        pci = gpu_pci(actual_gpu, run['gpu'].get('pci'))
        for model_text in (run['gpu']['model'], first_line(fields.get('GPU model', ''))):
            inline = re.search(r' \(PCI ([0-9a-f]{4}:[0-9a-f]{4})\)$', model_text, re.I)
            need(inline is None or inline.group(1).lower() == pci, 'GPU_PCI_MISMATCH')
        need(actual_version == version, 'VERSION_MISMATCH')
        identity = run['identity']
        need(identity.get('schema') == 'ndx12-share.v2' and identity.get('status') == 'VERIFIED', 'IDENTITY_MISMATCH')
        for key, expected in catalog()[version].items():
            need(type(identity.get(key)) is type(expected) and identity[key] == expected, 'IDENTITY_MISMATCH')
        version_text = first_line(fields.get('Benchmark version', ''))
        packages = re.findall(r'\bpackage\s+(v[0-9]+-r[0-9]+)\b', version_text, re.I)
        hashes = re.findall(r'\b[0-9a-fA-F]{64}\b', version_text)
        need(all(x == identity['package_id'] for x in packages) and
             all(x.lower() == identity['archive_sha256'] for x in hashes), 'IDENTITY_MISMATCH')
        need(driver is not None and driver == run['gpu'].get('driver') and
             driver in ('615.78.08', '620.70.06'), 'DRIVER_MISMATCH')
        requested = run.get('run', {}).get('requested')
        need(type(requested) is list and requested and len(requested) <= 4 and
             len(set(requested)) == len(requested) and all(x in SUITES for x in requested), 'SCHEMA')
        processes = process_rows(files['processes.csv'], requested)
        sanitized = sanitized_run(run, processes)
        run_claim = first_line(fields.get('Run status', ''))
        need(run_claim in ('Full test completed', 'Selected tests completed',
            'Stopped or interrupted before completion', 'Failed or refused to start', 'Unsure'), 'RUN_CLAIM_MISMATCH')
        # Completion means every requested process finished execution, not
        # that every process passed correctness or timing verification. Retain
        # the separate reported FAILED/PARTIAL state and successful samples.
        all_executed = sanitized['counts']['completed'] == sanitized['counts']['expected']
        if run_claim in ('Full test completed', 'Selected tests completed'):
            need(all_executed, 'RUN_CLAIM_MISMATCH')
        elif run_claim == 'Stopped or interrupted before completion':
            need(not all_executed, 'RUN_CLAIM_MISMATCH')
        elif run_claim == 'Failed or refused to start':
            need(not all_executed and
                 (sanitized['overall'] == 'FAILED' or sanitized['failure_reported']),
                 'RUN_CLAIM_MISMATCH')
        if run_claim == 'Full test completed':
            need(set(requested) == set(SUITES), 'RUN_CLAIM_MISMATCH')
        values = measurements(files, processes)
        result.update(driver=driver, pci=pci, state='DATA_READY', reason='OK', run=sanitized,
                      processes=processes, measurements=values)
        if any(p['kernel_records'] for p in processes):
            result['warnings'].append('KERNEL_RECORDS_REPORTED')
        if any(p['kernel_records'] is None for p in processes):
            result['warnings'].append('KERNEL_RECORDS_NOT_AVAILABLE')
        if sanitized['overall'] != 'COMPLETE':
            result['warnings'].append('NONCOMPLETE_RUN')
    except Refused as error:
        if str(error) in TRANSIENT_ATTACHMENT:
            raise
        result['reason'] = str(error) if str(error) in REASONS else 'INPUT_FORMAT'
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        result['reason'] = 'INPUT_FORMAT'
    return result


def exact_keys(value, keys):
    """Require a dictionary with exactly the supplied keys, or raise PROPOSAL_SCHEMA."""
    need(type(value) is dict and set(value) == set(keys), 'PROPOSAL_SCHEMA')


def csv_text(rows, columns):
    """Serialize the supplied rows and ordered columns as UTF-8 CSV bytes with LF endings."""
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, columns, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def validate_proposal(value):
    """Revalidate a typed proposal and return the same mapping on success.

    Schema/type decoding failures become PROPOSAL_SCHEMA; explicit integrity
    refusals retain their fixed reason. This is the public writer-side boundary
    used before rendering paths/content or making publisher API requests.
    """
    try:
        return _validate_proposal(value)
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError, RecursionError):
        raise Refused('PROPOSAL_SCHEMA') from None


def _validate_proposal(value):
    """Enforce the complete typed-proposal allowlist without trusting prepared data.

    Validate identities, states, counts, canonical numeric values and warnings;
    rerun shared process/run checks and require measurements for exactly the
    VERIFIED keys. Manual-review records must contain no numeric payload.
    Return value unchanged or raise Refused, without network or file writes.
    """
    exact_keys(value, ('schema', 'issue', 'source_revision', 'bundle_sha256',
        'claimed_gpu', 'claimed_version', 'archive_gpu', 'archive_version', 'driver', 'pci',
        'state', 'reason', 'run', 'processes', 'measurements', 'warnings'))
    need(value['schema'] == 'ndx12.community-intake.v2', 'PROPOSAL_SCHEMA')
    integer(value['issue'], 1, 2**31-1)
    for key in ('source_revision', 'bundle_sha256'):
        need((key == 'bundle_sha256' and value[key] is None) or
             (type(value[key]) is str and re.fullmatch('[0-9a-f]{64}', value[key])), 'PROPOSAL_SCHEMA')
    for key in ('claimed_gpu', 'archive_gpu'):
        need(value[key] is None or value[key] in GPUS, 'PROPOSAL_SCHEMA')
    for key in ('claimed_version', 'archive_version'):
        need(value[key] is None or value[key] in catalog(), 'PROPOSAL_SCHEMA')
    need(value['driver'] in (None, '615.78.08', '620.70.06'), 'PROPOSAL_SCHEMA')
    enum(value['state'], ('DATA_READY', 'MANUAL_REVIEW'))
    enum(value['reason'], REASONS)
    need(type(value['warnings']) is list and len(value['warnings']) <= len(WARNINGS) and
         all(type(x) is str and x in WARNINGS for x in value['warnings']) and
         len(set(value['warnings'])) == len(value['warnings']), 'PROPOSAL_SCHEMA')
    need(type(value['processes']) is list and len(value['processes']) <= MAX_PROCESSES and
         type(value['measurements']) is list and len(value['measurements']) <= MAX_PROCESSES, 'PROPOSAL_SCHEMA')
    expected_warnings = WARNINGS - {'KERNEL_RECORDS_REPORTED', 'KERNEL_RECORDS_NOT_AVAILABLE', 'NONCOMPLETE_RUN'}
    if value['state'] == 'MANUAL_REVIEW':
        need(value['pci'] is None, 'PROPOSAL_SCHEMA')
        need(value['reason'] != 'OK' and value['reason'] not in TRANSIENT_ATTACHMENT and value['run'] is None and
             not value['processes'] and not value['measurements'], 'PROPOSAL_SCHEMA')
    else:
        need(gpu_pci(value['archive_gpu'], value['pci']) == value['pci'], 'PROPOSAL_SCHEMA')
        need(value['reason'] == 'OK' and value['claimed_gpu'] is not None and
             value['claimed_gpu'] == value['archive_gpu'] and value['claimed_version'] is not None and
             value['claimed_version'] == value['archive_version'] and value['driver'] is not None and
             value['bundle_sha256'] is not None, 'PROPOSAL_SCHEMA')
        run = value['run']
        exact_keys(run, ('overall', 'clocks', 'failure_reported', 'counts', 'steps'))
        need(type(run['failure_reported']) is bool, 'PROPOSAL_SCHEMA')
        need(type(run['steps']) is list and 0 < len(run['steps']) <= 4, 'PROPOSAL_SCHEMA')
        for c in [run['counts'], *(step.get('counts') for step in run['steps'])]:
            exact_keys(c, ('expected', 'completed', 'verified', 'failed', 'held', 'not_run', 'unknown'))
            for n in c.values():
                integer(n, 0, MAX_PROCESSES)
        requested = []
        input_steps = []
        for step in run['steps']:
            exact_keys(step, ('suite', 'status', 'counts', 'reported_clock_qualification', 'reported_ns_per_tick_envelope'))
            requested.append(enum(step['suite'], SUITES))
            input_steps.append({'suite': step['suite'], 'status': step['status'], 'counts': step['counts'],
                'clock_check': {'status': step['reported_clock_qualification'],
                                'envelope_ns_per_tick': step['reported_ns_per_tick_envelope']}})
        need(len(set(requested)) == len(requested), 'PROPOSAL_SCHEMA')
        serialized = []
        for row in value['processes']:
            exact_keys(row, PROCESS_COLUMNS)
            integer(row['repeat'], 1, 7)
            if row['kernel_records'] is not None:
                integer(row['kernel_records'], 0, 100000)
            need(all(type(row[k]) is str for k in PROCESS_COLUMNS if k not in ('repeat', 'kernel_records')), 'PROPOSAL_SCHEMA')
            serialized.append({k: '' if v is None else str(v) for k, v in row.items()})
        normalized = process_rows(csv_text(serialized, PROCESS_COLUMNS), requested)
        need(normalized == value['processes'], 'PROPOSAL_SCHEMA')
        again = sanitized_run({'schema': 'ndx12-share.v2', 'units': {'native': 'GPU_TICKS', 'vulkan': 'NS'},
            'run': {'overall': run['overall'], 'clocks': run['clocks'], 'requested': requested,
                    'completed': [x['suite'] for x in input_steps if x['status'] == 'COMPLETE'],
                    'not_started': [x['suite'] for x in input_steps if x['status'] == 'NOT_RUN'],
                    'failed': True if run['failure_reported'] else None},
            'totals': run['counts'], 'steps': input_steps}, normalized)
        need(again == run, 'PROPOSAL_SCHEMA')
        verified = {process_key(p) for p in normalized if p['status'] == 'VERIFIED'}
        seen = set()
        for row in value['measurements']:
            exact_keys(row, ('suite', 'case', 'variant', 'path', 'repeat', 'value', 'unit', 'clock_mode', 'telemetry'))
            integer(row['repeat'], 1, 7)
            if row['suite'] == 'compute':
                integer(row['value'])
            else:
                timing_fraction(row['value'], halves=row['path'] == 'native')
            key = process_key(row)
            need(key in verified and key not in seen and
                 row['unit'] == ('GPU_TICKS' if row['path'] == 'native' else 'NS'), 'PROPOSAL_SCHEMA')
            enum(row['clock_mode'], CLOCK_MODES)
            enum(row['telemetry'], ('LIVE', 'OFF', 'DISABLED', 'NOT_RECORDED'))
            seen.add(key)
        need(seen == verified, 'PROPOSAL_SCHEMA')
        if any(p['kernel_records'] for p in normalized):
            expected_warnings |= {'KERNEL_RECORDS_REPORTED'}
        if any(p['kernel_records'] is None for p in normalized):
            expected_warnings |= {'KERNEL_RECORDS_NOT_AVAILABLE'}
        if run['overall'] != 'COMPLETE':
            expected_warnings |= {'NONCOMPLETE_RUN'}
    need(set(value['warnings']) == set(expected_warnings), 'PROPOSAL_SCHEMA')
    need(len(json_bytes(value)) <= MAX_PROPOSAL, 'PROPOSAL_SCHEMA')
    return value


def record_folder(proposal):
    """Return the fixed GPU/release/Issue directory for a revalidated proposal.

    Unknown or conflicting identities use literal pending/unidentified
    categories. Only catalogue keys and a bounded Issue number form the path;
    no untrusted free-form path is accepted or created here.
    """
    validate_proposal(proposal)
    ambiguous = proposal['reason'] in ('GPU_UNKNOWN', 'GPU_MISMATCH', 'GPU_PCI_FORMAT',
        'GPU_PCI_UNVERIFIED', 'GPU_PCI_MISMATCH', 'VERSION_UNKNOWN', 'VERSION_MISMATCH', 'IDENTITY_MISMATCH')
    gpu = proposal['claimed_gpu'] if not ambiguous else None
    version = proposal['claimed_version']
    return ROOT + (gpu or 'Pending_Classification') + '/' + (version or 'Unidentified_Version') + '/issue-' + str(proposal['issue'])


def summaries(proposal):
    """Group validated measurements and return exact count/median/min/max rows.

    Groups keep suite, case, variant, execution path and unit distinct.
    Fraction arithmetic retains decimal precision; frame aggregates remain
    medians of exported process medians, not independent GPU qualification.
    """
    groups = collections.defaultdict(list)
    for row in proposal['measurements']:
        groups[(row['suite'], row['case'], row['variant'], row['path'], row['unit'])].append(Fraction(row['value']))
    return [{'suite': key[0], 'case': key[1], 'variant': key[2], 'path': key[3], 'unit': key[4],
             'n': len(values), 'median': exact_timing_number(statistics.median(values)),
             'minimum': exact_timing_number(min(values)), 'maximum': exact_timing_number(max(values))}
            for key, values in sorted(groups.items())]


MEMORY_EVIDENCE = {
    'v0.1.4': ('b47a4aab73ca4f54028b7e6c7dd4da0d9015b9fc46274a2a8df802211f671ca1',
               'fbd3fd01968c60ed67cb6c492be63bbc9dbd598f', 111),
    'v0.1.5': ('c448a959d9f08328a0b210f8be58a650e5e906088947856c4dbdf55523c9848e',
               '4a5a6001db6001db508224e4cf16b50289ac5a7a', 113),
}


def memory_backing(proposal):
    """Derive release-documented Native placement for a validated proposal.

    The full catalogue identity must match separately verified release evidence.
    Neither Issue prose nor arbitrary archive fields select placement. This is
    a release-documentation classification, not an observed allocation check;
    unknown/refused identities stay UNKNOWN and Vulkan is never inferred.
    """
    native = {'backing': 'UNKNOWN', 'scope': 'data_buffers', 'basis': 'NOT_RECORDED'}
    version = proposal['archive_version']
    evidence = MEMORY_EVIDENCE.get(version)
    identity = catalog().get(version)
    if proposal['state'] == 'DATA_READY' and evidence and identity and digest(json_bytes(identity)) == evidence[0]:
        native = {'backing': 'SYSMEM', 'scope': 'data_buffers',
                  'basis': 'RELEASE_ARTIFACT_DOCUMENTATION', 'release': version,
                  'release_artifact_sha256': identity['archive_sha256'],
                  'documentation_git_blob': evidence[1],
                  'evidence_url': 'https://github.com/' + REPOSITORY + '/blob/' + version +
                                  '/NDX12_GPU_Benchmark/README.md#L' + str(evidence[2])}
    return {'schema': 'ndx12.community-memory.v1', 'native_dx12': native,
            'vulkan': {'backing': 'NOT_RECORDED', 'basis': 'NOT_INFERRED_FROM_NATIVE'}}


def memory_label(context):
    """Return a fixed Native-only label from derived backing metadata."""
    if context['native_dx12']['backing'] == 'SYSMEM':
        return 'Native DX12 memory backing: SYSMEM (system-memory buffers, not VRAM)'
    return 'Native DX12 memory backing: UNKNOWN (release evidence NOT_RECORDED)'


def chart(proposal, rows):
    """Render fresh UTF-8 SVG bytes from validated proposal and summary rows.

    Use fixed/escaped labels and exact numeric text with separate native/Vulkan
    scales. Only bar geometry uses floating-point scaling. Uploaded graphics
    are never reused; this helper does not write any file.
    """
    context = memory_backing(proposal)
    height = 190 + len(rows) * 25
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="{height}" viewBox="0 0 1280 {height}">',
        '<metadata id="memory-backing">' + html.escape(json_bytes(context).decode()) + '</metadata>',
        '<rect width="100%" height="100%" fill="white"/>',
        '<g font-family="DejaVu Sans, sans-serif" font-size="12" fill="#18222c">',
        f'<text x="16" y="24">UNVERIFIED Issue #{proposal["issue"]}: exported numeric summaries only</text>',
        '<text x="16" y="44">' + memory_label(context) + '</text>',
        '<text x="16" y="64">Vulkan memory backing: NOT_RECORDED (not inferred from Native DX12).</text>',
        '<text x="16" y="84">Separate scales and units; no cross-API speedup or GPU qualification is established.</text>']
    y = 108
    for path, unit in [('native', 'GPU_TICKS'), ('vulkan', 'NS')]:
        subset = [r for r in rows if r['path'] == path]
        parts.append(f'<text x="16" y="{y}">{path}: {unit} — independent scale</text>')
        y += 24
        peak = max([float(r['median']) for r in subset] + [1])
        for row in subset:
            label = html.escape(' '.join([row['suite'], row['case'], row['variant'] or 'default']))
            width = float(row['median']) / peak * 460
            parts.append(f'<text x="16" y="{y+12}">{label}</text><rect x="330" y="{y}" width="{width:.2f}" height="16" fill="#337799"/><text x="800" y="{y+12}">{row["median"]}</text>')
            y += 25
    parts.append('</g></svg>\n')
    return '\n'.join(parts).encode()


def render(proposal):
    """Return fixed output paths and bytes for a revalidated proposal.

    DATA_READY produces seven sanitized files, including derived memory metadata;
    MANUAL_REVIEW produces its record, backing metadata and caveated README. Charts/tables are generated from typed data,
    never uploaded prose or graphics. This function performs no filesystem
    or network writes, and all result claims remain UNVERIFIED.
    """
    validate_proposal(proposal)
    folder = record_folder(proposal)
    context = memory_backing(proposal)
    issue = proposal['issue']
    url = 'https://github.com/' + REPOSITORY + '/issues/' + str(issue)
    lines = [f'# Community submission — Issue #{issue}', '',
        '**UNVERIFIED — draft for maintainer/owner review; no acceptance or performance endorsement.**', '',
        f'Source: [Issue #{issue}]({url})', '',
        '**' + memory_label(context) + '**',
        'Vulkan memory backing: NOT_RECORDED; Native placement is not attributed to the reference.',
        'Backing is classified from documented release identity, not independently observed host allocations.', '',
        '| Field | Intake observation |', '| --- | --- |',
        '| State | ' + proposal['state'] + ' |', '| Reason | ' + proposal['reason'] + ' |',
        '| Claimed GPU | ' + (proposal['claimed_gpu'] or 'Pending classification') + ' |',
        '| Archive GPU | ' + (proposal['archive_gpu'] or 'Not established') + ' |',
        '| Claimed release | ' + (proposal['claimed_version'] or 'Unidentified') + ' |',
        '| Archive release | ' + (proposal['archive_version'] or 'Not established') + ' |',
        '| Driver | ' + (proposal['driver'] or 'Not established') + ' |', '',
        'Model/PCI field consistency is checked against pinned vendor data; this is not hardware authentication.', '',
        'The source Issue and attachment are untrusted reports. Matching catalog fields and recalculated',
        'medians do not authenticate the machine, receipt provenance, GPU readbacks or execution.',
        'Review background contention and all reporter notes in the Issue; they are not copied here.',
        'Actual per-dispatch clocks are not proven. Native GPU ticks and Vulkan nanoseconds stay separate.',
        'A reported 189/189 VERIFIED count is not independent GPU qualification.', '']
    public = {folder+'/record.json': json_bytes(proposal),
              folder+'/memory-backing.json': json_bytes(context)}
    if proposal['state'] == 'DATA_READY':
        lines += ['Reported overall state: `' + proposal['run']['overall'] + '`; failure marker present: `' +
                  str(proposal['run']['failure_reported']).lower() + '`.', '',
                  '## Reported process counts', '', '| Suite | Expected | VERIFIED (reported) | FAIL | HELD | NOT_RUN | UNKNOWN | Reported clock check |',
                  '| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
        for step in proposal['run']['steps']:
            c = step['counts']
            lines.append('| ' + step['suite'] + ' | ' + ' | '.join(str(c[k]) for k in
                ('expected', 'verified', 'failed', 'held', 'not_run', 'unknown')) + ' | ' + step['reported_clock_qualification'] + ' |')
        rows = summaries(proposal)
        lines += ['', '## Recalculated exported measurements', '',
            'Medians below are calculated from exported per-process values, not from uploaded prose or charts.',
            'Frame-suite values are medians of process medians. No uploaded HTML, image or raw log is reused.', '',
            '| Suite | Case | Variant | Path | Unit | n | Median |', '| --- | --- | --- | --- | --- | ---: | ---: |']
        for row in rows:
            lines.append('| ' + ' | '.join(str(row[k]) for k in ('suite', 'case', 'variant', 'path', 'unit', 'n', 'median')) + ' |')
        lines += ['', '[Fresh chart with separate scales](chart.svg). Full sanitized data: [measurements.csv](measurements.csv),',
                  '[summary.csv](summary.csv), [processes.csv](processes.csv).', '']
        public[folder+'/processes.csv'] = csv_text(proposal['processes'], PROCESS_COLUMNS)
        public[folder+'/measurements.csv'] = csv_text(proposal['measurements'],
            ['suite', 'case', 'variant', 'path', 'repeat', 'value', 'unit', 'clock_mode', 'telemetry'])
        public[folder+'/summary.csv'] = csv_text(rows,
            ['suite', 'case', 'variant', 'path', 'unit', 'n', 'median', 'minimum', 'maximum'])
        public[folder+'/chart.svg'] = chart(proposal, rows)
    else:
        lines += ['No numeric result or uploaded chart is proposed while this refusal remains unresolved.',
                  'Inspect and correct the source Issue/attachment, then request a new reviewed intake.', '']
    lines += ['## Mandatory caveats', '', *('- '+warning for warning in sorted(proposal['warnings'])), '',
        'Maintainer review and an explicit owner decision are required before merging.',
        'Intake approval labels authorize processing only; they do not accept these results.', '']
    public[folder+'/README.md'] = '\n'.join(lines).encode()
    return public


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        """Refuse every GitHub API redirect so authorization cannot follow another URL."""
        raise Refused('API_REDIRECT')


class GitHub:
    """Fixed repository/API host; read-only unless explicitly constructed writable."""
    def __init__(self, token, writable=False, opener=None):
        """Create a fixed-repository client with an existing token and optional test opener.

        The default client permits GET only; writable explicitly enables POST.
        The default opener disables proxies/redirects. Client-generated refusals
        do not copy credential text.
        """
        need(type(token) is str and bool(token), 'API_TOKEN_MISSING')
        self.token, self.writable = token, writable
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, method, endpoint, data=None):
        """Send a permitted GET/POST to a validated endpoint in the fixed repository.

        Return bounded decoded JSON. Reject absolute/traversing/encoded endpoint
        forms and disallowed methods before transport; HTTP or transport failures
        raise fixed Refused codes. POST requires a writable client; this method
        does not itself authorize intake or approve a benchmark result.
        """
        need(method == 'GET' or (method == 'POST' and self.writable), 'API_WRITE_DISABLED')
        need(type(endpoint) is str and not endpoint.startswith('/') and
             not any(c in endpoint for c in ('\r', '\n', '#', '\\', '%')), 'API_ENDPOINT')
        parsed = urllib.parse.urlsplit(endpoint)
        need(not parsed.scheme and not parsed.netloc and
             not any(part in ('.', '..') for part in parsed.path.split('/')), 'API_ENDPOINT')
        url = 'https://api.github.com/repos/' + REPOSITORY + '/' + endpoint
        request = urllib.request.Request(url, data=json_bytes(data) if data is not None else None,
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28',
                     'User-Agent': 'ndx12-community-intake/1'}, method=method)
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(MAX_API + 1)
            return load_json(raw, MAX_API)
        except urllib.error.HTTPError as error:
            raise Refused('API_' + str(error.code)) from None
        except (OSError, urllib.error.URLError):
            raise Refused('API_UNAVAILABLE') from None

    def get(self, endpoint):
        """Return the bounded JSON response from a fixed-repository GET endpoint."""
        return self.request('GET', endpoint)

    def post(self, endpoint, data):
        """Send JSON with POST only when this client was explicitly made writable."""
        return self.request('POST', endpoint, data)


def event_issue(event):
    """Return the bounded Issue number and manual-dispatch flag for the workflow event.

    Read the event type from GITHUB_EVENT_NAME; reject unsupported events and
    malformed identifiers. The flag selects eligibility handling, not result
    acceptance or a grant of publication authority.
    """
    if os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch':
        inputs = event.get('inputs', {})
        need(type(inputs) is dict, 'EVENT_TYPE')
        value = inputs.get('issue_number')
        need(type(value) in (int, str) and re.fullmatch('[1-9][0-9]{0,9}', str(value)), 'ISSUE_NUMBER')
        mode = inputs.get('intake_mode', 'manual')
        need(type(mode) is str and mode in ('manual', 'label-reconciled'), 'EVENT_TYPE')
        # A categorizer-triggered retry is NOT a maintainer's manual approval.
        return integer(int(value), 1, 2**31-1), mode == 'manual'
    need(os.environ.get('GITHUB_EVENT_NAME') == 'issues', 'EVENT_TYPE')
    return integer(event.get('issue', {}).get('number'), 1, 2**31-1), False


def write_new(path, data):
    """Write bytes to a new path, refusing existing outputs and detected symlink components.

    Create missing parent directories; never overwrite evidence. Alias checks
    raise OUTPUT_ALIAS and exclusive creation can raise FileExistsError.
    Other filesystem errors propagate to the command boundary.
    """
    path = Path(path)
    need(not any(p.is_symlink() for p in (path, *path.parents)), 'OUTPUT_ALIAS')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as output:
        output.write(data)


def report_intake_skip(issue_number, reason):
    """Expose an expected refusal in the job summary without enabling publication.

    Only fixed text and a bounded integer reach Actions commands/Markdown.
    No submission prose, attachment URLs or private exception messages are used.
    """
    notes = {
        'AWAITING_INTAKE_APPROVAL': (
            'Awaiting maintainer permission to process this outside submission.',
            'Keep the Issue OPEN. A maintainer must apply benchmark:intake-approved '
            'or explicitly dispatch the workflow. This does not validate results.'),
        'NOT_ELIGIBLE': (
            'Not eligible for automatic intake.',
            'The Issue must be OPEN, start with [Results], and carry the '
            'benchmark:submission label. Reopen/correct it before retrying.'),
    }
    title, guidance = notes[reason]
    print(reason)
    print('::warning title=Community benchmark intake::' + reason + ' - ' + title)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as output:
            output.write('### Community benchmark intake — NOT PROCESSED\n\n'
                         + '- Source: Issue #' + str(issue_number) + '\n'
                         + '- Status: `' + reason + '`\n'
                         + '- ' + title + '\n'
                         + '- Next step: ' + guidance + '\n\n'
                         + '**UNVERIFIED:** No benchmark records, charts or draft '
                           'PR were created by this run.\n')


def prepare_main(argv=None):
    """Run preparation for a workflow event or explicit local JSON/archive fixtures.

    Event mode checks the repository, fetches the Issue and enforces eligibility.
    Write one new validated proposal; event mode then appends ready=true to
    GITHUB_OUTPUT. Return zero for success/expected ineligibility; other
    refusals propagate without pretending a ready artifact exists.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--event', type=Path)
    source.add_argument('--issue-json', type=Path, help='local read-only fixture, no GitHub API client')
    parser.add_argument('--bundle', type=Path, help='local archive fixture; never executed/extracted')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.event:
        need(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'REPOSITORY')
        event = load_json(args.event.read_bytes(), MAX_API)
        issue_number, manual = event_issue(event)
        issue = GitHub(os.environ.get('GH_TOKEN')).get('issues/' + str(issue_number))
        try:
            eligible(issue, manual)
        except Refused as error:
            if str(error) not in ('NOT_ELIGIBLE', 'AWAITING_INTAKE_APPROVAL'):
                raise
            report_intake_skip(issue_number, str(error))
            return 0
    else:
        issue = load_json(args.issue_json.read_bytes(), MAX_API)
    compressed = None
    if args.bundle:
        need(args.bundle.stat().st_size <= MAX_COMPRESSED, 'COMPRESSED_LIMIT')
        compressed = args.bundle.read_bytes()
    proposal = validate_proposal(prepare(issue, compressed))
    write_new(args.output, json_bytes(proposal))
    if args.event:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('ready=true\n')
    print(proposal['state'] + ':' + proposal['reason'])
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(prepare_main())
    except (Refused, OSError) as error:
        print('Intake refused: ' + (str(error) if isinstance(error, Refused) else 'LOCAL_IO'))
        raise SystemExit(1)
