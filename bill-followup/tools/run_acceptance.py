import json
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

root = Path(__file__).resolve().parents[1]
run = root / 'evidence' / ('acceptance-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
run.mkdir(parents=True)
env = dict(os.environ, FOLLOWUP_EVIDENCE=str(run), PYTHONUTF8='1')
cmd = [sys.executable, 'tools/suite.py']
source_hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('followup', 'tests', 'tools') for p in (root / folder).rglob('*.py')}
done = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, encoding='utf-8')
(run / 'stdout.txt').write_text(done.stdout, encoding='utf-8')
(run / 'stderr.txt').write_text(done.stderr, encoding='utf-8')
(run / 'invocation.json').write_text(json.dumps({'argv': cmd, 'cwd': str(root), 'exit_code': done.returncode, 'source_sha256': source_hashes, 'environment_overrides': {'PYTHONUTF8': '1', 'FOLLOWUP_EVIDENCE': str(run)}}, ensure_ascii=False, indent=2), encoding='utf-8')
print(done.stdout, end='')
print(done.stderr, end='')
print('Evidence:', run)
sys.exit(done.returncode)
