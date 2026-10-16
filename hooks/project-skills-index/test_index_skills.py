"""Regression tests for workspace skill discovery and hook output."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('index_skills', Path(__file__).with_name('index_skills.py'))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def skill(self, repo='repo', name='example', target=None):
        project = self.root / repo
        (project / '.git').mkdir(parents=True, exist_ok=True)
        skill = project / '.agents/skills' / name
        skill.parent.mkdir(parents=True, exist_ok=True)
        if target:
            skill.symlink_to(target, target_is_directory=True)
        else:
            skill.mkdir()
            (skill / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: Example test skill.\n---\nTest.\n')
        return skill

    def invoke(self):
        return subprocess.run([sys.executable, str(Path(MODULE.__file__))],
            input=json.dumps({'cwd': str(self.root), 'source': 'startup'}),
            capture_output=True, text=True)

    def test_create_warn_then_silent_restart(self):
        source = self.skill()
        first = self.invoke()
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertIn('Restart this Codex session', json.loads(first.stdout)['systemMessage'])
        link = self.root / '.agents/skills/example'
        self.assertEqual(link.resolve(), source)
        second = self.invoke()
        self.assertEqual(second.returncode, 0)
        self.assertEqual(second.stdout, '')

    def test_content_edit_does_not_recreate_links_or_warn(self):
        source = self.skill()
        MODULE.synchronize(self.root)
        with (source / 'SKILL.md').open('a') as stream:
            stream.write('New instructions.\n')
        self.assertEqual(MODULE.synchronize(self.root), [])

    def test_adopt_matching_existing_link(self):
        source = self.skill()
        link = self.root / '.agents/skills/example'
        link.parent.mkdir(parents=True)
        link.symlink_to(source)
        self.assertEqual(MODULE.synchronize(self.root), [])
        state = json.loads((self.root / '.agents/project-skills-index.json').read_text())
        self.assertEqual(state['links']['example'], str(source))

    def test_remove_only_owned_stale_link(self):
        source = self.skill()
        MODULE.synchronize(self.root)
        (source / 'SKILL.md').unlink()
        self.assertEqual(MODULE.synchronize(self.root), ['removed example'])
        self.assertFalse((self.root / '.agents/skills/example').is_symlink())
        self.assertTrue(source.is_dir())

    def test_unmanaged_replacement_is_preserved(self):
        source = self.skill()
        MODULE.synchronize(self.root)
        (source / 'SKILL.md').unlink()
        link = self.root / '.agents/skills/example'
        link.unlink()
        link.mkdir()
        self.assertEqual(MODULE.synchronize(self.root), [])
        self.assertTrue(link.is_dir())

    def test_duplicate_name_aborts_before_creating_index(self):
        self.skill('one')
        self.skill('two')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            MODULE.synchronize(self.root)
        self.assertFalse((self.root / '.agents').exists())

    def test_unmanaged_directory_conflict_prevents_partial_link_changes(self):
        self.skill(name='aaa')
        self.skill(name='zzz')
        (self.root / '.agents/skills/zzz').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            MODULE.synchronize(self.root)
        self.assertFalse((self.root / '.agents/skills/aaa').exists())

    def test_repository_entrypoint_symlink_is_followed(self):
        source = self.skill()
        project = source.parents[2]
        canonical = project / 'skills/example'
        canonical.parent.mkdir()
        source.rename(canonical)
        source.symlink_to('../../skills/example')
        MODULE.synchronize(self.root)
        self.assertEqual((self.root / '.agents/skills/example').resolve(), canonical)

    def test_repo_scoped_session_does_not_rewrite_repo_skills(self):
        source = self.skill()
        self.assertEqual(MODULE.synchronize(source.parents[2]), [])
        self.assertTrue((source / 'SKILL.md').is_file())

    def test_non_git_directory_is_not_discovered(self):
        source = self.skill()
        (source.parents[2] / '.git').rmdir()
        self.assertEqual(MODULE.synchronize(self.root), [])
        self.assertFalse((self.root / '.agents').exists())

    def test_git_worktree_file_is_supported(self):
        source = self.skill()
        git = source.parents[2] / '.git'
        git.rmdir()
        git.write_text('gitdir: /unneeded-for-discovery\n')
        self.assertEqual(MODULE.synchronize(self.root), ['added example'])

    def test_target_outside_repo_is_rejected(self):
        external = self.root / 'external'
        external.mkdir()
        (external / 'SKILL.md').write_text('---\nname: example\n---\n')
        self.skill(target=external)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            MODULE.synchronize(self.root)

    def test_retarget_and_preserve_unmanaged_links(self):
        source = self.skill('one')
        MODULE.synchronize(self.root)
        (source / 'SKILL.md').unlink()
        new = self.skill('two')
        self.assertEqual(MODULE.synchronize(self.root), ['updated example'])
        self.assertEqual((self.root / '.agents/skills/example').resolve(), new)

    def test_errors_are_visible_hook_messages(self):
        self.skill('one')
        self.skill('two')
        result = self.invoke()
        self.assertEqual(result.returncode, 1)
        self.assertIn('Duplicate', json.loads(result.stdout)['systemMessage'])


if __name__ == '__main__':
    unittest.main()
