"""Verify a fresh no-pip venv and an isolated copy; do not claim a fresh OS."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).resolve().parents[1]
dest = root / 'evidence' / ('clean-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
dest.mkdir(parents=True)
workspace = dest / 'workspace'
workspace.mkdir()
for directory in ('followup', 'tests', 'tools', 'fixtures'):
    shutil.copytree(root / directory, workspace / directory, ignore=shutil.ignore_patterns('__pycache__'))
for name in ('requirements.txt', 'config.example.json', 'README.md', 'DESIGN.md', 'TESTING.md', 'CONTRIBUTIONS.md', 'COLLABORATION.md'):
    shutil.copy2(root / name, workspace / name)
commands = []


def run(argv, cwd):
    done = subprocess.run([str(a) for a in argv], cwd=cwd, env=dict(os.environ, PYTHONUTF8='1'), capture_output=True, text=True, encoding='utf-8')
    commands.append({'argv': [str(a) for a in argv], 'cwd': str(cwd), 'exit_code': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr})
    if done.returncode:
        raise RuntimeError(done.stderr)
    return done.stdout


try:
    run([sys.executable, '-m', 'venv', '--without-pip', dest / 'venv'], root)
    python = dest / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    environment = json.loads(run([python, '-c', "import sys,importlib.util,json,sqlite3; print(json.dumps({'python':sys.version,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'pip_present':importlib.util.find_spec('pip') is not None,'sqlite':sqlite3.sqlite_version}))"], workspace))
    assert environment['prefix'] != environment['base_prefix']
    assert not environment['pip_present']
    run([python, '-m', 'followup', '--db', 'smoke.sqlite', '--user', 'clean', 'init'], workspace)
    run([python, '-m', 'followup', '--db', 'smoke.sqlite', '--user', 'clean', 'ingest', 'fixtures/duplicate.json'], workspace)
    snapshot = json.loads(run([python, '-m', 'followup', '--db', 'smoke.sqlite', '--user', 'clean', 'show'], workspace))
    assert len(snapshot['issues']) == 1 and snapshot['notices'][0]['status'] == 'sent'
    run([python, 'tools/run_acceptance.py'], workspace)
    test_result = sorted((workspace / 'evidence').glob('acceptance-*/results.json'))[-1]
    results = json.loads(test_result.read_text(encoding='utf-8'))
    assert results['successful'] and results['tests_run'] == 35
    shutil.copy2(test_result, dest / 'clean-test-results.json')
    report = {'scope': '本机新建无pip虚拟环境及隔离源码副本；不是全新操作系统', 'environment': environment, 'startup_successful': True, 'smoke_issues': len(snapshot['issues']), 'smoke_notice_status': snapshot['notices'][0]['status'], 'tests_run': results['tests_run'], 'tests_successful': results['successful'], 'evidence': str(dest)}
    (dest / 'clean-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
finally:
    (dest / 'raw-commands.json').write_text(json.dumps(commands, ensure_ascii=False, indent=2), encoding='utf-8')
