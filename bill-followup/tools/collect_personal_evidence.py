"""Copy only this user's expressly reported review artifacts, without rerunning tests."""
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
parser = argparse.ArgumentParser()
parser.add_argument('review_project', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
review = args.review_project.resolve()
destination = root / 'evidence' / 'personal-review-20261022-164553-252'
destination.mkdir(exist_ok=False)
manifest = {'collected_at_utc': datetime.now(timezone.utc).isoformat(), 'executor': '用户本人执行；Codex仅收集核查材料',
            'source_project': str(review), 'tests_rerun_during_collection': 0, 'copied_files': [], 'screenshots_not_found': [],
            'independent_understanding_evidence': False, 'understanding_note': '六道参考回答及问答不作为独立理解核查或独立完成编码的证明。'}


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    target.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise RuntimeError('副本校验失败：' + str(target))
    manifest['copied_files'].append({'source': str(source), 'destination': target.relative_to(root).as_posix(), 'bytes': len(data), 'sha256': digest, 'byte_identical': True})


for name in ('acceptance-20261022T084553401827Z', 'realtime-e2e-20261022T084559992884Z', 'personal-acceptance-20261022-164553-252'):
    source = review / 'evidence' / name
    for p in sorted(source.rglob('*')):
        if p.is_file():
            if p.suffix == '.pyc' or '__pycache__' in p.parts:
                raise RuntimeError('验收目录中出现非预期缓存：' + str(p))
            copy(p, destination / name / p.relative_to(source))

manual = destination / 'manual-cases'
for p in sorted((review / 'data').iterdir()):
    if p.name in ('review.sqlite', 'refund-review.sqlite', 'refund-request.json', 'refund-receipt60.json', 'refund-receipt40.json'):
        if p.suffix == '.sqlite' and (Path(str(p) + '-wal').exists() or Path(str(p) + '-shm').exists()):
            raise RuntimeError('源数据库存在WAL/SHM，需要先单独核实一致性，不能只复制主库：' + str(p))
        copy(p, manual / p.name)
manual_states = {}
for p in manual.glob('*.sqlite'):
    c = sqlite3.connect(p.as_uri() + '?mode=ro&immutable=1', uri=True)
    c.row_factory = sqlite3.Row
    tables = ('clock', 'users', 'inputs', 'facts', 'issues', 'appointments', 'notices', 'provider', 'history')
    manual_states[p.name] = {table: [dict(row) for row in c.execute('SELECT * FROM ' + table + ' ORDER BY rowid')] for table in tables}
    c.close()
(manual / 'database-contents.json').write_text(json.dumps(manual_states, ensure_ascii=False, indent=2), encoding='utf-8')

screenshots = {
    'codex-clipboard-60e89d72-cc73-4a1a-abcd-96426ece920e.png': 'replay-last-chapter.png',
    'codex-clipboard-d40457e3-8709-4f17-8138-12f2ce494800.png': 'replay-control.png',
    'codex-clipboard-f7ce04f6-14fe-4d6a-88c0-572f206103f3.png': 'replay-seek.png',
    'codex-clipboard-6546df13-1bbe-4288-8fd4-41cb93f80c66.png': 'refund-full-and-replay.png',
    'codex-clipboard-4f623ab5-8f7b-4d3e-98a2-6db8b50f6915.png': 'refund-partial.png',
    'codex-clipboard-f0010d83-e1dc-4b23-842b-d2ae0d28edc7.png': 'personal-exit-codes.png',
}
for source_name, target_name in screenshots.items():
    p = Path.home() / 'AppData' / 'Local' / 'Temp' / source_name
    if p.is_file():
        copy(p, destination / 'screenshots' / target_name)
    else:
        manifest['screenshots_not_found'].append(source_name)

suite = json.loads((destination / 'acceptance-20261022T084553401827Z' / 'results.json').read_text(encoding='utf-8'))
real = json.loads((destination / 'realtime-e2e-20261022T084559992884Z' / 'report.json').read_text(encoding='utf-8'))
outer = destination / 'personal-acceptance-20261022-164553-252'
encoding = {}
for name in ('suite-output.txt', 'realtime-output.txt', 'execution-summary.json'):
    data = (outer / name).read_bytes()
    enc = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    text = data.decode(enc)
    encoding[name] = {'file_encoding': enc, 'preserved_original': True,
                      'finding': '中文在外层转存前已误解码，保留乱码原件' if name != 'execution-summary.json' else '中文正常，两个退出码均为0',
                      'sha256': hashlib.sha256(data).hexdigest()}
for p in (destination / 'acceptance-20261022T084553401827Z' / 'results.json', destination / 'acceptance-20261022T084553401827Z' / 'stderr.txt', destination / 'realtime-e2e-20261022T084559992884Z' / 'report.json'):
    p.read_text(encoding='utf-8', errors='strict')
    encoding[str(p.relative_to(destination))] = {'file_encoding': 'UTF-8', 'finding': '中文正常；直接写入的原始证据', 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
(destination / 'encoding-findings.json').write_text(json.dumps(encoding, ensure_ascii=False, indent=2), encoding='utf-8')
manifest['results'] = {'suite_tests_run': suite['tests_run'], 'suite_successful': suite['successful'], 'realtime_outcome': real['outcome'],
                       'manual_duplicate': '用户明确报告通过，数据库副本佐证', 'manual_refund_and_replay': '用户明确报告通过，截图与数据库副本佐证',
                       'replay_interactions': '用户明确报告暂停、章节切换、进度拖动均通过；属于用户报告及截图，不冒充Codex代执行'}
(destination / 'collection-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'destination': str(destination), 'copied_files': len(manifest['copied_files']), 'byte_identical': True, 'screenshots_not_found': manifest['screenshots_not_found'], 'results': manifest['results'], 'manual_counts': {name: {k: len(v) for k,v in state.items()} for name,state in manual_states.items()}}, ensure_ascii=False, indent=2))
