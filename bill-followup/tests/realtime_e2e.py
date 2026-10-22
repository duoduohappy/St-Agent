"""One supplemental E2E test; uses the real clock and the unmodified runner.

Run directly: python tests/realtime_e2e.py
It is intentionally separate from the existing 35-case suite, so this final
supplement can be verified without rerunning unrelated checks.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from followup.engine import BJ, DAY, Engine, iso


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def now_record():
    return {'epoch_seconds': time.time(), 'beijing': datetime.now(BJ).isoformat(), 'monotonic_seconds': time.monotonic()}


def run():
    folder = ROOT / 'evidence' / ('realtime-e2e-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    folder.mkdir(parents=True)
    db = folder / 'realtime.sqlite'
    user = 'realtime_e2e_user'
    fixture_calls = []
    observations = folder / 'observations.jsonl'
    report = {'test': 'realtime_e2e_background_appointment', 'outcome': 'RUNNING', 'started': now_record(),
              'timeout_seconds': 25, 'post_send_observation_seconds': 3.2, 'assertions': [],
              'scope': '真实时钟、独立SQLite库、独立持续运行进程、本地模拟通知通道。安排后父进程只读观察，不再输入事件或调用advance/check/cycle。'}
    files = [ROOT / 'followup' / 'engine.py', ROOT / 'followup' / '__main__.py']
    report['production_source_sha256_before'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    proc = None
    stdout = stderr = None

    def require(value, message):
        report['assertions'].append({'description': message, 'passed': bool(value), 'at': now_record()})
        if not value:
            raise AssertionError(message)

    def readonly():
        c = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=2)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA query_only=ON')
        c.execute('BEGIN')
        return c

    def observe():
        c = readonly()
        try:
            notices = [dict(r) for r in c.execute("SELECT * FROM notices WHERE user=? AND kind='appointment'", (user,))]
            providers = [dict(r) for r in c.execute("SELECT p.* FROM provider p JOIN notices n ON n.user=p.user AND n.id=p.op WHERE p.user=? AND n.kind='appointment'", (user,))]
            history = [dict(r) for r in c.execute("SELECT * FROM history WHERE user=? AND seq>? ORDER BY seq", (user, baseline_seq))]
            appointments = [dict(r) for r in c.execute('SELECT * FROM appointments WHERE user=?', (user,))]
        finally:
            c.close()
        return {'observed_at': now_record(), 'appointment_notices': notices, 'appointment_provider': providers, 'new_history': history, 'appointments': appointments}

    try:
        engine = Engine(db)

        def fixture(method, *args):
            result = getattr(engine, method)(*args)
            fixture_calls.append({'at': now_record(), 'method': method, 'args': args, 'result': result})
            return result

        fixture('init', datetime.now(BJ).isoformat(), 'real')
        current = int(time.time())
        # Both transactions already occurred. Their separation is four minutes.
        for tid, offset in [('RT1', 300), ('RT2', 60)]:
            fixture('ingest', user, {'type': 'transaction', 'id': tid, 'merchant': 'REALTIME_FIXTURE', 'amount': 3000, 'at': iso(current - offset)})
        fixture('cycle', user)
        initial = engine.snapshot(user)
        iid = initial['issues'][0]['id']
        require(len(initial['notices']) == 1 and initial['notices'][0]['status'] == 'sent', '夹具中首次提醒已完成，后续仅观察独立约定提醒')
        fixture('act', user, iid, 'confirm')
        due = int(time.time()) + 8
        fixture('act', user, iid, 'schedule', iso(due))
        arranged = engine.snapshot(user)
        require(arranged['issues'][0]['phase'] == 'confirmed_problem' and arranged['appointments'][0]['due'] == due,
                '通过正式用户动作创建有效明确约定，不缩短未回复24小时或退款72小时规则')
        require(DAY == 86400, '生产DAY常量仍为86400秒')
        baseline_seq = arranged['history'][-1]['seq']
        baseline_inputs = len(arranged['inputs'])
        baseline_facts = len(arranged['facts'])
        fixture_finished = now_record()
        report.update({'due_epoch_seconds': due, 'due_beijing': iso(due), 'fixture_finished': fixture_finished,
                       'initial_notification_count': 1, 'baseline_history_seq': baseline_seq,
                       'baseline_input_count': baseline_inputs, 'baseline_fact_count': baseline_facts,
                       'fixture': 'tests/realtime_e2e.py：正式Engine接口创建重复问题→首次提醒→确认有问题→明确约定8秒后提醒'})
        write_json(folder / 'fixture-input-output.json', fixture_calls)
        write_json(folder / 'fixture-final-snapshot.json', arranged)
        # No Engine method is called after this boundary, including snapshot.
        del engine
        argv = [sys.executable, '-u', '-m', 'followup', '--db', str(db), 'run']
        stdout = (folder / 'process-stdout.txt').open('wb')
        stderr = (folder / 'process-stderr.txt').open('wb')
        started = now_record()
        proc = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                env=dict(os.environ, PYTHONUTF8='1'),
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        report['process'] = {'argv': argv, 'cwd': str(ROOT), 'pid': proc.pid, 'started': started,
                             'stdin': 'DEVNULL', 'environment_overrides': {'PYTHONUTF8': '1'}, 'poll_interval': '生产默认1秒'}
        write_json(folder / 'startup-command.json', report['process'])
        require(time.time() < due - 2, '独立进程在到期前至少2秒启动，具有提前发送观察窗口')
        hard_deadline = time.monotonic() + 25
        first_confirmed_mono = None
        pre_due_samples = 0
        last = None
        with observations.open('w', encoding='utf-8') as stream:
            while True:
                require_alive = proc.poll() is None
                if not require_alive:
                    raise AssertionError('持续运行进程意外退出，见process-stderr.txt')
                sample = observe()
                stream.write(json.dumps(sample, ensure_ascii=False) + '\n')
                stream.flush()
                last = sample
                when = sample['observed_at']['epoch_seconds']
                notices = sample['appointment_notices']
                providers = sample['appointment_provider']
                if when < due:
                    pre_due_samples += 1
                    if notices or providers:
                        raise AssertionError('到期前产生了约定通知或发送事实')
                for entry in notices + providers:
                    if entry.get('sent_at') is not None and entry['sent_at'] < due:
                        raise AssertionError('记录的发送时刻早于约定')
                sent = [n for n in notices if n['status'] == 'sent']
                if len(notices) > 1 or len(providers) > 1:
                    raise AssertionError('产生重复业务通知或通道发送记录')
                if sent and first_confirmed_mono is None:
                    first_confirmed_mono = time.monotonic()
                    report['first_sent_observed'] = sample['observed_at']
                    report['recorded_sent_at_beijing'] = iso(sent[0]['sent_at'])
                if first_confirmed_mono is not None and time.monotonic() - first_confirmed_mono >= 3.2:
                    break
                if time.monotonic() >= hard_deadline or (first_confirmed_mono is None and when > due + 8):
                    raise AssertionError('后台未在合理超时内自行发送，或观察超时')
                time.sleep(0.05)
        write_json(folder / 'last-observation.json', last)
        require(pre_due_samples >= 3, '到期前多次只读观察，约定通知与通道记录均为零')
        require(first_confirmed_mono is not None, '到期后后台独立进程自行发送，无新输入/advance/手动检查')
        require(len(last['appointment_notices']) == 1 and last['appointment_notices'][0]['status'] == 'sent', '继续等待至少3.2秒后仍只有1条约定通知')
        require(len(last['appointment_provider']) == 1 and last['appointment_provider'][0]['state'] == 'sent', '模拟通道只产生1条实际发送记录')
        require(sum(h['event'] == 'send_submitted' for h in last['new_history']) == 1 and sum(h['event'] == 'send_confirmed' for h in last['new_history']) == 1,
                '等待期间提交与确认各一次，没有重复发送尝试')
        report['pre_due_readonly_samples'] = pre_due_samples
        report['post_send_observed_seconds'] = time.monotonic() - first_confirmed_mono
        report['outcome'] = 'PASS'
    except BaseException:
        report['outcome'] = 'FAIL'
        report['failure_traceback'] = traceback.format_exc()
    finally:
        # Bounded cleanup on success, assertion failure, interrupt or timeout.
        if proc is not None:
            cleanup = {'requested_at': now_record(), 'alive_before_cleanup': proc.poll() is None}
            try:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                    cleanup['method'] = 'terminate_then_wait' if cleanup['alive_before_cleanup'] else 'already_exited'
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                    cleanup['method'] = 'kill_fallback_then_wait'
                cleanup.update({'exit_code': proc.returncode, 'finished_at': now_record(), 'process_still_running': proc.poll() is None})
            except BaseException:
                report['outcome'] = 'FAIL'
                cleanup['error'] = traceback.format_exc()
            report['process_cleanup'] = cleanup
        for handle in (stdout, stderr):
            if handle:
                handle.close()
        write_json(folder / 'fixture-input-output.json', fixture_calls)
        if db.exists():
            try:
                c = readonly()
                tables = ('clock', 'users', 'inputs', 'facts', 'issues', 'appointments', 'notices', 'provider', 'history')
                final = {table: [dict(r) for r in c.execute('SELECT * FROM ' + table + ' ORDER BY rowid')] for table in tables}
                c.rollback()
                target = sqlite3.connect(folder / 'final-state.sqlite')
                c.backup(target)
                target.close()
                c.close()
                write_json(folder / 'final-database-state.json', final)
                write_json(folder / 'sending-records.json', {'notices': final['notices'], 'provider': final['provider'], 'history': final['history']})
                if report['outcome'] == 'PASS':
                    require(len(final['inputs']) == baseline_inputs and len(final['facts']) == baseline_facts,
                            '夹具安排后原始输入与事实数量不变，证明无新事件输入')
                    require(final['issues'][0]['extra'] == 0, '独立约定未改变未回复追加次数')
                    require(not report['process_cleanup']['process_still_running'], '测试进程已在有界清理内停止')
            except BaseException:
                report['outcome'] = 'FAIL'
                report['final_state_error'] = traceback.format_exc()
        report['production_source_sha256_after'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        report['production_source_unchanged'] = report['production_source_sha256_before'] == report['production_source_sha256_after']
        if not report['production_source_unchanged']:
            report['outcome'] = 'FAIL'
        report['finished'] = now_record()
        report['evidence_directory'] = str(folder)
        write_json(folder / 'report.json', report)
        lines = ['# 真实时钟后台约定端到端补充验证', '', '测试：realtime_e2e_background_appointment', '',
                 '**实际结果：' + report['outcome'] + '**', '',
                 '- [完整报告与断言](report.json)', '- [启动命令和时间](startup-command.json)',
                 '- [夹具输入输出](fixture-input-output.json)', '- [安排完成时快照](fixture-final-snapshot.json)',
                 '- [只读时间序列观察](observations.jsonl)', '- [进程原始stdout](process-stdout.txt)',
                 '- [进程原始stderr](process-stderr.txt)', '- [发送记录](sending-records.json)',
                 '- [最终数据库内容](final-database-state.json)', '- [最终独立数据库备份](final-state.sqlite)', '',
                 '本项单独执行，未重跑已有35项。真实时钟/真实独立进程，本地模拟发送通道。测试夹具使用正式接口安排确认后的明确约定；没有修改24小时/72小时规则。', '']
        (folder / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    return report


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['outcome'] == 'PASS' else 1)
