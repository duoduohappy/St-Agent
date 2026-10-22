"""Run real CLI subprocesses, retaining their exact decoded input/output."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).resolve().parents[1]
folder = root / 'evidence' / ('stage-one-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
folder.mkdir(parents=True)
db = folder / 'core.sqlite'
events = {
    'request.json': [{'type': 'refund', 'id': 'R1', 'amount': 10000, 'confirmed_at': '2026-10-19T09:10:00+08:00'}],
    'receive60.json': [{'type': 'receipt', 'id': 'E1', 'refund_id': 'R1', 'amount': 6000, 'at': '2026-10-22T09:15:00+08:00'}],
    'receive40.json': [{'type': 'receipt', 'id': 'E2', 'refund_id': 'R1', 'amount': 4000, 'at': '2026-10-22T09:20:00+08:00'}],
}
for name, data in events.items():
    (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
calls = []


def cli(*arguments):
    argv = [sys.executable, '-m', 'followup', '--db', str(db), '--user', 'alice', *arguments]
    done = subprocess.run(argv, cwd=root, env=dict(os.environ, PYTHONUTF8='1'), capture_output=True, text=True, encoding='utf-8')
    calls.append({'argv': argv, 'exit_code': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr})
    if done.returncode:
        raise RuntimeError(done.stderr)
    return json.loads(done.stdout)


try:
    initialized = cli('init')
    cli('ingest', str(folder / 'request.json'))
    initial = cli('show')
    cli('advance', '2026-10-22T09:15:00+08:00')
    cli('ingest', str(folder / 'receive60.json'))
    partial = cli('show')
    cli('advance', '2026-10-22T09:20:00+08:00')
    cli('ingest', str(folder / 'receive40.json'))
    full = cli('show')
    cli('ingest', str(folder / 'receive60.json'))
    cli('ingest', str(folder / 'receive40.json'))
    restarted = cli('show')
    assert partial['issues'][0]['latest_facts']['remaining'] == 4000
    assert full['issues'][0]['status'] == 'resolved'
    assert restarted['issues'][0]['latest_facts']['trusted_received'] == 10000
    summary = {'startup': initialized, 'first': {'status': initial['issues'][0]['status'], 'notices': len(initial['notices']), 'send_status': initial['notices'][0]['status']},
               'after60': {'status': partial['issues'][0]['status'], 'remaining_fen': partial['issues'][0]['latest_facts']['remaining']},
               'after40': {'status': full['issues'][0]['status'], 'basis': full['issues'][0]['basis']},
               'after_replay_and_process_restart': {'received_fen': restarted['issues'][0]['latest_facts']['trusted_received'], 'notices': len(restarted['notices']), 'extra': restarted['issues'][0]['extra']},
               'evidence': str(folder)}
    (folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
finally:
    (folder / 'cli-raw-input-output.json').write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding='utf-8')
