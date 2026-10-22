"""Package only this standalone project, with source and evidence hashes."""
import hashlib
import json
import sys
import subprocess
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from delivery_files import delivery_files

sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).resolve().parents[1]
delivery = root / 'delivery'
delivery.mkdir(exist_ok=True)
name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
acceptance = sorted((root / 'evidence').glob('acceptance-*/results.json'))
latest_test = acceptance[-1] if acceptance else None
latest_demo = sorted((root / 'evidence').glob('demo-*/replay.html'))[-1]
latest_core = sorted((root / 'evidence').glob('stage-one-*/summary.json'))[-1]
latest_export = sorted((root / 'evidence').glob('collaboration/*-manifest.json'))[-1]
clean = sorted((root / 'evidence').glob('clean-*/clean-report.json'))
test = json.loads(latest_test.read_text(encoding='utf-8')) if latest_test else {}
realtime_reports = sorted((root / 'evidence').glob('realtime-e2e-*/report.json'))
realtime_report = realtime_reports[-1] if realtime_reports else None
realtime = json.loads(realtime_report.read_text(encoding='utf-8')) if realtime_report else None
manifest = json.loads(latest_export.read_text(encoding='utf-8'))
personal = root / 'evidence' / 'personal-review-20261022-164553-252'
personal_suite = personal / 'acceptance-20261022T084553401827Z'
personal_real = personal / 'realtime-e2e-20261022T084559992884Z'
personal_test = json.loads((personal_suite / 'results.json').read_text(encoding='utf-8'))
personal_rt = json.loads((personal_real / 'report.json').read_text(encoding='utf-8'))
review_path = root / 'evidence' / ('final-content-review-' + name + '.json')
index = ['# 交付索引', '', '仅包含独立bill-followup项目；未向外部发送。', '',
         '- [启动与操作说明](README.md)', '- [设计与用户确认的实现假设](DESIGN.md)',
         '- [测试、失败修复与缺口](TESTING.md)', '- [最终贡献归属](CONTRIBUTIONS.md)', '- [协作完整记录的实际范围](COLLABORATION.md)', '',
         '- [本人实际执行验收、证据与编码说明](PERSONAL_ACCEPTANCE.md)',
         f"- 本人35项实际验收：{personal_test['tests_run']}项，successful={personal_test['successful']}；[逐项报告]({personal_suite.relative_to(root).as_posix()}/REPORT.md)、[正常UTF-8原始stderr]({personal_suite.relative_to(root).as_posix()}/stderr.txt)",
         f"- 本人真实时钟端到端：{personal_rt['outcome']}；[报告]({personal_real.relative_to(root).as_posix()}/REPORT.md)、[启动/输出/发送/数据库完整证据]({personal_real.relative_to(root).as_posix()}/report.json)",
         f"- 此前Codex执行的历史验收：{test.get('tests_run')}项，successful={test.get('successful')}；[历史报告]({latest_test.parent.relative_to(root).as_posix()}/REPORT.md)",
         f'- [7分钟实际执行快照回放]({latest_demo.relative_to(root).as_posix()})',
         f'- [真实CLI核心案例结果]({latest_core.relative_to(root).as_posix()})',
         f'- [协作完整原始记录（限定范围）索引]({latest_export.relative_to(root).as_posix()})',
         f"- [协作原文]({latest_export.parent.relative_to(root).as_posix()}/{manifest['export_file']})；截止北京时间：{manifest['cutoff_beijing']}；来源第{manifest['source_line_range'][0]}至{manifest['source_line_range'][1]}行，提供{manifest['selected_original_lines']}条；截止内未配对调用：{len(manifest['unpaired_call_ids_at_snapshot'])}。",
         f'- [交付内容审查与文件哈希]({review_path.relative_to(root).as_posix()})']
if clean:
    index.append(f'- [本机无pip新虚拟环境启动与完整验收]({clean[-1].relative_to(root).as_posix()})')
if realtime_report:
    index.append(f"- 此前Codex独立补充真实时钟验证：{realtime['outcome']}；[历史报告]({realtime_report.parent.relative_to(root).as_posix()}/REPORT.md)。与本人随后执行的运行分开保存。")
index.extend(['', '六道参考回答不作为独立理解核查证明。本人回放交互依据用户最终明确报告与截图登记，不外推为独立编码贡献。', '',
              '历史失败、原始乱码副本、旧文档及过去协作快照全部保留；最终整理未重跑业务测试、未修改生产逻辑。证据内绝对路径为运行时元数据，解压后按相对目录查看。', '',
              '压缩包排除解释器虚拟环境、浏览器profile、重复源码、无关缓存、运行目录及旧压缩包自身。协作记录完整性只针对所声明的本地来源、可见内容范围与截止点；截止后的封存、打包、核验和最后回复不再补入，不循环打包。未证明平台全量完整，不推测范围外记录的缺失原因。', ''])
(root / 'DELIVERY.md').write_text('\n'.join(index), encoding='utf-8')


# Review only deliverable files; this is content verification, not a test rerun.
audit = subprocess.run([sys.executable, 'tools/audit_delivery.py', '--out', str(review_path)], cwd=root,
                       env=dict(os.environ, PYTHONUTF8='1'), capture_output=True, text=True, encoding='utf-8')
if audit.returncode:
    raise RuntimeError('交付内容审查未通过，停止打包：' + audit.stdout + audit.stderr)
review = json.loads(review_path.read_text(encoding='utf-8'))
files = delivery_files(root)
hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
for path, digest in review['content_sha256'].items():
    if hashes.get(path) != digest:
        raise RuntimeError('内容审查后文件变化，停止打包：' + path)
# Compare the unchanged application against the last delivered source hashes.
previous = delivery / 'bill-followup-20261022T081314409756Z.zip'
with zipfile.ZipFile(previous) as prior:
    old_hashes = json.loads(prior.read('bill-followup/FILE_SHA256.json'))
for path in ('followup/engine.py', 'followup/__main__.py', 'followup/__init__.py'):
    if hashes[path] != old_hashes[path]:
        raise RuntimeError('生产源码发生变化：' + path)
archive = delivery / ('bill-followup-final-' + name + '.zip')
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for p in files:
        z.write(p, 'bill-followup/' + p.relative_to(root).as_posix())
    z.writestr('bill-followup/FILE_SHA256.json', json.dumps(hashes, ensure_ascii=False, indent=2))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for path, expected in hashes.items():
        assert hashlib.sha256(z.read('bill-followup/' + path)).hexdigest() == expected
report = {'archive': str(archive), 'bytes': archive.stat().st_size, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'files': len(files), 'zip_crc_and_each_file_hash_verified': True, 'latest_tests': test.get('tests_run'), 'tests_successful': test.get('successful')}
if realtime:
    report['supplemental_realtime_e2e'] = {'outcome': realtime['outcome'], 'evidence': realtime_report.relative_to(root).as_posix(), 'production_source_unchanged': realtime['production_source_unchanged'], 'previous_35_tests_not_rerun': True}
report.update({'personal_verification': {'suite_tests': personal_test['tests_run'], 'suite_successful': personal_test['successful'], 'realtime_outcome': personal_rt['outcome'], 'evidence': personal.relative_to(root).as_posix()},
               'content_review': review_path.relative_to(root).as_posix(), 'content_review_passed': review['passed'],
               'production_source_unchanged_from_previous_delivery': True, 'business_tests_rerun_during_finalization': 0,
               'collaboration_cutoff_beijing': manifest['cutoff_beijing'], 'collaboration_records': manifest['selected_original_lines'],
               'collaboration_unpaired_calls_within_cutoff': manifest['unpaired_call_ids_at_snapshot']})
(delivery / (name + '-package-report.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
