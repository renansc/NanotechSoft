"""Exercise canonical scripts with isolated dotenv files and simulated services."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DeployCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(ROOT / 'deploy', self.root / 'deploy', ignore=shutil.ignore_patterns('__pycache__', 'tmp'))
        for name in ('up.sh', 'down.sh', 'update.sh', 'git-safe-push.sh'):
            shutil.copy2(ROOT / name, self.root / name)
        source = self.root / 'apps/demo/source'
        source.mkdir(parents=True)
        (source.parent / 'app.json').write_text(json.dumps({'app_key': 'demo', 'source_dir': 'apps/demo/source'}))
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'commands.jsonl'
        docker = self.bin / 'docker'
        docker.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['COMMAND_LOG'], 'a') as f: f.write(json.dumps(args)+'\\n')
if args[0] == 'inspect':
    print(json.dumps(['CLIENTE_DEPLOY_ID='+os.environ.get('FAKE_CLIENT','rio-branco')]))
elif 'ps' in args and '-q' in args and os.environ.get('FAKE_CLIENT'):
    print('existing-portal')
elif 'config' in args and '--format' in args:
    print(json.dumps({'services': {'riob-app': {'volumes': [{'type':'bind','source':os.environ['IMPORT_DIR'],'target':'/imports/vendas-diario/txt'}]}}}))
''')
        docker.chmod(0o755)
        curl = self.bin / 'curl'
        curl.write_text('#!/bin/sh\nexit 0\n')
        curl.chmod(0o755)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith(('NANOTECH_', 'CLIENTE_', 'NS_', 'RENDER', 'COMPOSE_'))}
        self.env.update(PATH=str(self.bin)+os.pathsep+os.environ['PATH'], COMMAND_LOG=str(self.log), IMPORT_DIR=str(source))

    def run_script(self, script, *args, **environ):
        return subprocess.run(['bash', str(self.root / script), *args], cwd='/tmp', env={**self.env, **environ}, text=True, capture_output=True)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_profiles_use_local_environment_and_preserve_database_operations(self):
        for profile in ('rio-branco', 'nanotech', 'senhor', 'laboratorio'):
            for script in ('up.sh', 'down.sh', 'update.sh'):
                with self.subTest(profile=profile, script=script):
                    (self.root / '.env').write_text(f'NANOTECH_DEPLOY_PROFILE={profile}\nCLIENTE_DEPLOY_ID={profile}\n')
                    self.log.unlink(missing_ok=True)
                    result = self.run_script(script, FAKE_CLIENT=profile)
                    self.assertEqual(0, result.returncode, result.stdout+result.stderr)
                    commands = self.commands()
                    compose = [c for c in commands if c[0] == 'compose' and 'version' not in c]
                    self.assertTrue(all('--env-file' in c and str(self.root / '.env') in c for c in compose))
                    self.assertTrue(all('--project-directory' in c for c in compose))
                    operations = [c for c in compose if any(op in c for op in ('up','stop','build'))]
                    self.assertFalse(any('down' in c or '-v' in c for c in operations))
                    database = [c for c in operations if 'mysql' in c]
                    self.assertEqual(script == 'up.sh', bool(database))
                    if database: self.assertIn('--no-recreate', database[0])
                    builds = [c for c in operations if 'build' in c]
                    if builds: self.assertEqual(profile in ('rio-branco','nanotech'), 'riob-app' in builds[0])

    def test_explicit_file_and_env_local_fallback(self):
        (self.root / '.env_local').write_text('NANOTECH_DEPLOY_PROFILE=senhor\nCLIENTE_DEPLOY_ID=senhor\n')
        result = self.run_script('down.sh', FAKE_CLIENT='senhor')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(str(self.root / '.env_local') in c for c in self.commands()))
        (self.root / '.env').write_text('NANOTECH_DEPLOY_PROFILE=rio-branco\n')
        (self.root / 'custom.env').write_text('NANOTECH_DEPLOY_PROFILE=laboratorio\nCLIENTE_DEPLOY_ID=laboratorio\n')
        result = self.run_script('down.sh', NANOTECH_ENV_FILE='custom.env', FAKE_CLIENT='laboratorio')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(str(self.root / 'custom.env') in c for c in self.commands()))

    def test_mismatching_client_mode_or_existing_container_fails_before_mutation(self):
        for variables in ({'CLIENTE_DEPLOY_ID':'senhor'}, {'NS_DEPLOY_MODE':'cloud-readonly'}, {'FAKE_CLIENT':'nanotech'}):
            for script in ('up.sh','down.sh','update.sh'):
                with self.subTest(variables=variables, script=script):
                    self.log.unlink(missing_ok=True)
                    result = self.run_script(script, NANOTECH_DEPLOY_PROFILE='rio-branco', **variables)
                    self.assertNotEqual(0, result.returncode)
                    self.assertFalse(any(any(op in c for op in ('up','stop','build','restart')) for c in self.commands()))

    def test_render_never_operates_local_compose(self):
        for script in ('up.sh', 'down.sh', 'update.sh'):
            with self.subTest(script=script):
                result = self.run_script(script, CLIENTE_DEPLOY_ID='cloud')
                self.assertNotEqual(0, result.returncode)
                self.assertIn('Blueprint', result.stderr+result.stdout)
                self.assertEqual([], self.commands())

    def test_dotenv_does_not_execute_shell_or_export_credentials(self):
        marker = self.root / 'executed'
        (self.root / '.env').write_text(f"NANOTECH_DEPLOY_PROFILE=$(touch {marker})\nNS_DB_PASSWORD=secret-sentinel\n")
        result = self.run_script('down.sh')
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(marker.exists())
        self.assertNotIn('secret-sentinel', result.stdout+result.stderr)

    def test_missing_explicit_file_does_not_fall_back_to_default_client(self):
        result = self.run_script('down.sh', NANOTECH_ENV_FILE='missing.env')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual([], self.commands())

    def test_git_safe_only_directory_blocks_nested_runtime_and_preserves_scope(self):
        def git(*args):
            return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, text=True).stdout
        git('init', '-b', 'main')
        git('config', 'user.name', 'Deployment test')
        git('config', 'user.email', 'deploy-test@example.invalid')
        (self.root / 'app.py').write_text('')
        # The fixture tests real Git operations without starting applications.
        with (self.root / 'deploy/lib/common.sh').open('a') as f:
            f.write('\nvalidate_client_contracts() { :; }\nvalidate_portal_integrations() { :; }\n')
        git('add', 'deploy', 'app.py', 'apps/demo/app.json')
        git('commit', '-m', 'Fixture')
        source = self.root / 'apps/demo/source'
        for name in ('uploads/operation.pdf', '.env', 'runtime.db', 'backup.sql', 'certs/private.key'):
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('runtime sentinel')
        (source / 'guide.md').write_text('Safe documentation\n')
        (self.root / 'unrelated.txt').write_text('unrelated with trailing whitespace   \n')
        git('add', 'apps/demo/source/runtime.db', 'unrelated.txt')
        result = self.run_script('git-safe-push.sh', '-y', '--no-push', '--skip-compose',
                                 '--only', 'apps/demo', '-m', 'Scoped publication')
        self.assertEqual(0, result.returncode, result.stdout+result.stderr)
        changed = git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').splitlines()
        self.assertEqual(['apps/demo/source/guide.md'], changed)
        self.assertEqual('', git('diff', '--cached', '--name-only'))
        self.assertTrue((source / 'runtime.db').exists())
        self.assertTrue((self.root / 'unrelated.txt').exists())


if __name__ == '__main__':
    unittest.main()
