#!/usr/bin/env python3
"""Index immediate child repositories' skills without copying their contents."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.index-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def discover(root):
    """Read only explicit skill entrypoints in immediate child Git repositories."""
    found = {}
    for repo in sorted(root.iterdir()):
        if repo.name.startswith('.') or repo.is_symlink() or not repo.is_dir():
            continue
        if not (repo / '.git').exists():
            continue
        entry = repo / '.agents' / 'skills'
        if not entry.is_dir():
            continue
        for skill in sorted(entry.iterdir()):
            manifest = skill / 'SKILL.md'
            if skill.name.startswith('.') or not manifest.is_file():
                continue
            canonical = skill.resolve(strict=True)
            try:
                canonical.relative_to(repo.resolve())
            except ValueError:
                raise ValueError(f'Skill target escapes its repository: {skill}')
            text = manifest.read_text(encoding='utf-8')
            if not text.startswith('---\n') or '\n---' not in text[4:]:
                raise ValueError(f'Missing skill frontmatter: {manifest}')
            front = text[4:].split('\n---', 1)[0]
            match = re.search(r'^name:\s*[\'\"]?([a-z0-9-]+)[\'\"]?\s*$', front, re.M)
            if not match or match.group(1) != skill.name:
                raise ValueError(f'Skill name must match its directory: {manifest}')
            name = match.group(1)
            if name in found and found[name] != str(canonical):
                raise ValueError(f'Duplicate skill name: {name}; {found[name]}; {canonical}')
            found[name] = str(canonical)
    return found


def synchronize(root):
    root = Path(root).resolve(strict=True)
    # Repository-scoped sessions already discover their own skills. Never rewrite
    # their entrypoint with a workspace index.
    if (root / '.git').exists():
        return []
    desired = discover(root)  # Detect all source conflicts before changing links.
    agents = root / '.agents'
    if agents.is_symlink():
        raise ValueError(f'Refusing a symlinked workspace metadata directory: {agents}')
    if not desired and not (agents / 'project-skills-index.json').exists():
        return []
    agents.mkdir(exist_ok=True)
    lock = agents / 'project-skills-index.lock'
    if lock.is_symlink():
        raise ValueError(f'Refusing a symlinked lock file: {lock}')
    with lock.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        # Re-read after locking, since another session may have just synchronized.
        desired = discover(root)
        state_path = agents / 'project-skills-index.json'
        if state_path.is_symlink():
            raise ValueError(f'Refusing a symlinked index manifest: {state_path}')
        state = json.loads(state_path.read_text()) if state_path.exists() else {'version': 1, 'links': {}}
        if state.get('version') != 1 or not isinstance(state.get('links'), dict):
            raise ValueError('Unsupported project skills index manifest')
        old = state['links']
        for name, target in old.items():
            if not re.fullmatch(r'[a-z0-9-]+', name) or not isinstance(target, str) or not Path(target).is_absolute():
                raise ValueError('Invalid managed link record')
        index = agents / 'skills'
        if index.is_symlink():
            raise ValueError(f'Refusing a symlinked workspace index directory: {index}')
        index.mkdir(exist_ok=True)
        # Never replace an unmanaged link or directory, even if a source vanished.
        for name in desired:
            link = index / name
            if not link.exists() and not link.is_symlink():
                continue
            current = str(link.resolve()) if link.is_symlink() else None
            if not link.is_symlink() or (current != desired[name] and current != old.get(name)):
                raise ValueError(f'Index conflict; existing entry was preserved: {link}')
        changed = []
        managed = {}
        for name, target in desired.items():
            link = index / name
            if link.is_symlink() and str(link.resolve()) == target:
                managed[name] = target  # Adopt matching pre-existing links.
                continue
            if link.is_symlink():
                link.unlink()
            link.symlink_to(os.path.relpath(target, index), target_is_directory=True)
            managed[name] = target
            changed.append(f'updated {name}' if name in old else f'added {name}')
        for name, target in old.items():
            if name in desired:
                continue
            link = index / name
            if link.is_symlink() and str(link.resolve()) == target:
                link.unlink()
                changed.append(f'removed {name}')
            # Unmanaged replacements are left untouched and released from ownership.
        new = {'version': 1, 'links': managed}
        if state != new or not state_path.exists():
            atomic_json(state_path, new)
        return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, help='Workspace root; defaults to hook input cwd')
    args = parser.parse_args()
    try:
        event = {} if args.root else json.load(sys.stdin)
        if event.get('source') not in (None, 'startup', 'resume', 'clear', 'fork'):
            return 0
        root = args.root or Path(event['cwd'])
        changed = synchronize(root)
        if changed:
            print(json.dumps({'systemMessage': 'Project skills index updated: '
                + ', '.join(changed)
                + '. Restart this Codex session to ensure the updated skills are loaded.'}))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'systemMessage': f'Project skills index could not be updated: {error}'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
