"""Read-only evidence/integrity gate. Not a visual or engineering validator."""
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

CHECKS = ('content_inventory', 'dimensions_symbols', 'tables', 'materials_notes',
          'technical_fields', 'visual_legibility', 'no_clipping_overlap', 'page_mapping')
ROLES = {'source', 'output', 'config', 'code', 'evidence'}
KINDS = {'view', 'pcb', 'table', 'specification', 'technical_titleblock', 'other'}


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def validate(data, base):
    errors = []
    def require(condition, message):
        if not condition:
            errors.append(message)
    def integer(value):
        return type(value) is int and value > 0
    def label(value):
        return isinstance(value, str) and bool(value.strip())
    def array(value, name):
        if not isinstance(value, list) or not value:
            errors.append(name + ': nonempty array required')
            return []
        return value
    if not isinstance(data, dict):
        return ['manifest must be an object']
    require(type(data.get('schema_version')) is int and data['schema_version'] == 1,
            'schema_version must be 1')
    artifacts = {}
    for item in array(data.get('artifacts'), 'artifacts'):
        if not isinstance(item, dict):
            errors.append('artifact must be object'); continue
        key = item.get('id')
        if not label(key):
            errors.append('artifact id required'); continue
        require(key not in artifacts, 'duplicate artifact ' + key)
        artifacts[key] = item
        require(item.get('role') in ROLES, 'invalid role ' + key)
        digest = item.get('sha256')
        require(isinstance(digest, str) and len(digest) == 64 and
                all(c in '0123456789abcdef' for c in digest), 'invalid sha256 ' + key)
        try:
            if not label(item.get('path')):
                raise ValueError('path required')
            path = (base / item['path']).resolve()
            require(sha256(path) == digest, 'hash mismatch ' + key)
        except (OSError, ValueError) as exc:
            errors.append('unreadable artifact ' + key + ': ' + str(exc))
    require(ROLES <= {a.get('role') for a in artifacts.values()}, 'all artifact roles required')
    page_counts = {}
    for section, role in [('sources', 'source'), ('outputs', 'output')]:
        seen = set()
        for item in array(data.get(section), section):
            if not isinstance(item, dict):
                errors.append(section + ': object required'); continue
            key = item.get('artifact')
            if not label(key):
                errors.append(section + ': artifact id required'); continue
            require(key not in seen, 'duplicate page inventory ' + key); seen.add(key)
            require(artifacts.get(key, {}).get('role') == role, 'wrong page artifact ' + key)
            n = item.get('page_count')
            if not integer(n):
                errors.append('invalid page count ' + key); continue
            page_counts[key] = n
            pages = item.get('reviewed_pages')
            require(isinstance(pages, list) and all(integer(p) for p in pages) and
                    sorted(pages) == list(range(1, n + 1)), 'incomplete reviewed pages ' + key)
        require(seen == {k for k, v in artifacts.items() if v.get('role') == role},
                section + ': all artifacts need page inventory')
    def valid_page(key, page, role):
        return label(key) and artifacts.get(key, {}).get('role') == role and integer(page) and page <= page_counts.get(key, 0)
    seen_groups, source_pages, output_pages = set(), set(), set()
    for group in array(data.get('groups'), 'groups'):
        if not isinstance(group, dict):
            errors.append('group must be object'); continue
        key = group.get('id')
        if not label(key):
            errors.append('group id required'); continue
        require(key not in seen_groups, 'duplicate group ' + key); seen_groups.add(key)
        src, page = group.get('source'), group.get('source_page')
        valid = valid_page(src, page, 'source')
        require(valid, 'invalid group source page ' + key)
        if valid: source_pages.add((src, page))
        require(group.get('kind') in KINDS, 'invalid group kind ' + key)
        placements = set()
        for placement in array(group.get('placements'), 'placements ' + key):
            if not isinstance(placement, dict):
                errors.append('placement must be object'); continue
            out, op = placement.get('output'), placement.get('page')
            valid = valid_page(out, op, 'output')
            require(valid, 'invalid target page ' + key)
            if valid:
                require((out, op) not in placements, 'duplicate placement ' + key)
                placements.add((out, op)); output_pages.add((out, op))
        if group.get('kind') == 'table':
            for axis in ('rows', 'columns'):
                a, b = group.get('source_' + axis), group.get('verified_' + axis)
                require(integer(a) and integer(b) and a == b, 'table ' + axis + ' mismatch ' + key)
            require(group.get('cells_verified') is True, 'table cells unverified ' + key)
    for key, n in page_counts.items():
        role = artifacts.get(key, {}).get('role')
        covered = source_pages if role == 'source' else output_pages
        require(all((key, p) in covered for p in range(1, n + 1)), 'unmapped page ' + key)
    checks = data.get('checks')
    if not isinstance(checks, dict): checks = {}
    for name in CHECKS:
        check = checks.get(name)
        if not isinstance(check, dict):
            errors.append('missing check ' + name); continue
        require(check.get('status') == 'pass', 'not passed ' + name)
        require(label(check.get('reviewer')), 'reviewer required ' + name)
        try:
            when = dt.datetime.fromisoformat(check['reviewed_at'].replace('Z', '+00:00'))
            require(when.tzinfo is not None and when <= dt.datetime.now(dt.timezone.utc),
                    'invalid review date ' + name)
        except (KeyError, TypeError, ValueError, AttributeError):
            errors.append('invalid review date ' + name)
        for eid in array(check.get('evidence'), 'evidence ' + name):
            require(label(eid) and artifacts.get(eid, {}).get('role') == 'evidence',
                    'unknown evidence ' + name)
    return errors


def main():
    try:
        path = Path(sys.argv[1]).resolve()
        errors = validate(json.loads(path.read_text(encoding='utf-8')), path.parent)
    except (IndexError, OSError, ValueError, TypeError) as exc:
        errors = [str(exc)]
    print(json.dumps({'ready_for_release_review': not errors, 'errors': errors,
                      'notice': 'Integrity/evidence gate only; no upload or engineering certification.'}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
