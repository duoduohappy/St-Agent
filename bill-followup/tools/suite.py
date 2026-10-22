import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows.append({'id': test.id(), 'expected': test._testMethodDoc, 'outcome': 'PASS', 'evidence': test._testMethodName + '/evidence.json'})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows.append({'id': test.id(), 'expected': test._testMethodDoc, 'outcome': 'FAIL', 'traceback': self._exc_info_to_string(err, test), 'evidence': test._testMethodName + '/evidence.json'})

    def addError(self, test, err):
        super().addError(test, err)
        self.rows.append({'id': test.id(), 'expected': test._testMethodDoc, 'outcome': 'ERROR', 'traceback': self._exc_info_to_string(err, test), 'evidence': test._testMethodName + '/evidence.json'})


suite = unittest.defaultTestLoader.discover('tests')
result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
destination = Path(os.environ['FOLLOWUP_EVIDENCE'])
(destination / 'results.json').write_text(json.dumps({'tests_run': result.testsRun, 'successful': result.wasSuccessful(), 'cases': result.rows}, ensure_ascii=False, indent=2), encoding='utf-8')
rows = ['# 实际验收结果', '', f'本次执行 {result.testsRun} 项；整体成功：{result.wasSuccessful()}。', '', '每项实际状态、输入、步骤快照及历史见所链接JSON；断言见对应测试源码。', '', '| 用例 | 预期 | 实际 | 证据 |', '|---|---|---|---|']
for row in result.rows:
    rows.append(f"| {row['id'].split('.')[-1]} | {row['expected']} | {row['outcome']} | [原始执行证据]({row['evidence']}) |")
(destination / 'REPORT.md').write_text('\n'.join(rows) + '\n', encoding='utf-8')
sys.exit(0 if result.wasSuccessful() else 1)
