import json
import os
import subprocess
import sys
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from followup.engine import DAY, Engine, stamp

ROOT = Path(os.environ.get('FOLLOWUP_EVIDENCE', 'evidence/manual-test-run'))
T0 = '2026-10-22T09:10:00+08:00'


def transaction(tid, at, merchant='M1', amount=3000):
    return {'type': 'transaction', 'id': tid, 'merchant': merchant, 'amount': amount, 'at': '2026-10-22T' + at + ':00+08:00'}


def refund(rid='R1', amount=10000, confirmed='2026-10-19T09:10:00+08:00'):
    return {'type': 'refund', 'id': rid, 'amount': amount, 'confirmed_at': confirmed}


def receipt(eid, amount, rid='R1'):
    return {'type': 'receipt', 'id': eid, 'refund_id': rid, 'amount': amount, 'at': T0}


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / self._testMethodName
        self.directory.mkdir(parents=True, exist_ok=True)
        self.e = Engine(self.directory / 'state.sqlite')
        self.e.init(T0)
        self.u = 'alice'
        self.evidence = {'test': self._testMethodName, 'expectation': self._testMethodDoc, 'steps': []}
        self.addCleanup(self.save)

    def save(self):
        self.evidence['final_alice'] = self.e.snapshot('alice')
        self.evidence['final_bob'] = self.e.snapshot('bob')
        (self.directory / 'evidence.json').write_text(json.dumps(self.evidence, ensure_ascii=False, indent=2), encoding='utf-8')

    def snap(self, label):
        value = self.e.snapshot(self.u)
        self.evidence['steps'].append({'label': label, 'snapshot': value})
        return value

    def feed(self, *facts):
        values = [self.e.ingest(self.u, f) for f in facts]
        self.evidence['steps'].append({'input_facts': facts, 'ingest_results': values})
        return values

    def pair(self, send=True):
        self.feed(transaction('T1', '09:00'), transaction('T2', '09:05'))
        if send:
            self.e.cycle(self.u)
        else:
            self.e.check(self.u)
        return self.snap('pair_created')['issues'][0]['id']

    def move(self, seconds):
        now = self.e.snapshot(self.u)['now']
        self.e.advance(now + seconds)
        self.evidence['steps'].append({'advance_seconds': seconds})

    def test_01_duplicate_pair(self):
        """题面1：两笔同商户同30元交易产生一个疑似问题；原交易不删除。"""
        self.pair()
        s = self.snap('sent_initial')
        self.assertEqual(len(s['issues']), 1)
        self.assertEqual(len(s['facts']), 2)
        self.assertEqual(s['issues'][0]['status'], 'open')
        self.assertIn('尚未证实错扣', s['notices'][0]['body'])

    def test_02_normal_replay(self):
        """题面2：标正常后反向重放，正常结论保留，不重开不再发送。"""
        iid = self.pair()
        self.e.act(self.u, iid, 'normal')
        self.feed(transaction('T2', '09:05'), transaction('T1', '09:00'))
        self.move(10 * DAY); self.e.cycle(self.u)
        s = self.snap('normal_preserved')
        self.assertEqual(s['issues'][0]['status'], 'normal')
        self.assertEqual(len(s['issues']), 1)
        self.assertEqual(len(s['notices']), 1)

    def test_03_three_pairs(self):
        """题面3：三笔交易形成3个唯一无序交易对，乱序重放无新增。"""
        facts = [transaction('T1', '09:00'), transaction('T2', '09:05'), transaction('T3', '09:09')]
        self.feed(*facts); self.e.cycle(self.u)
        self.feed(*reversed(facts)); self.e.cycle(self.u)
        s = self.snap('three_unique_pairs')
        self.assertEqual(len(s['issues']), 3)
        self.assertEqual({tuple(i['refs']) for i in s['issues']}, {('T1', 'T2'), ('T1', 'T3'), ('T2', 'T3')})
        self.assertEqual(len(s['notices']), 3)

    def test_04_partial_full_replay(self):
        """题面4：退款100，满72小时提醒；60后差40，40后验证解决；重放不累计。"""
        self.feed(refund()); self.e.cycle(self.u)
        self.assertEqual(len(self.snap('72h_initial')['notices']), 1)
        self.feed(receipt('E1', 6000)); self.e.cycle(self.u)
        self.assertEqual(self.snap('partial_60')['issues'][0]['latest_facts']['remaining'], 4000)
        self.feed(receipt('E2', 4000)); self.e.cycle(self.u)
        self.feed(receipt('E1', 6000), receipt('E2', 4000)); self.e.cycle(self.u)
        i = self.snap('verified_resolved')['issues'][0]
        self.assertEqual(i['status'], 'resolved')
        self.assertEqual(i['basis'], 'verified_receipts')
        self.assertEqual(i['latest_facts']['trusted_received'], 10000)

    def test_05_receipt_before_request(self):
        """题面5：全额到账先于申请，资料齐全后已到账，不发送过期提醒。"""
        self.feed(receipt('E1', 10000)); self.e.cycle(self.u)
        self.assertEqual(self.snap('orphan_receipt')['issues'], [])
        self.feed(refund()); self.e.cycle(self.u)
        s = self.snap('request_arrived')
        self.assertEqual(s['issues'][0]['status'], 'resolved')
        self.assertEqual(s['notices'], [])

    def test_06_unanswered_limit(self):
        """题面6：24/48小时前不追加，恰好边界可追加，总共3次后停止。"""
        self.pair()
        self.move(DAY - 1); self.e.cycle(self.u)
        self.assertEqual(len(self.snap('before24')['notices']), 1)
        self.move(1); self.e.cycle(self.u)
        self.assertEqual(self.snap('at24')['issues'][0]['extra'], 1)
        self.move(DAY - 1); self.e.cycle(self.u)
        self.assertEqual(len(self.snap('before48')['notices']), 2)
        self.move(1); self.e.cycle(self.u)
        self.move(20 * DAY); self.e.cycle(self.u)
        s = self.snap('limit_reached')
        self.assertEqual(s['issues'][0]['extra'], 2)
        self.assertEqual(len(s['notices']), 3)
        self.assertEqual(s['issues'][0]['status'], 'open')

    def test_07_tomorrow_preserves_quota(self):
        """题面7：明天=max(当前+24h,已有最早时间)，追加次数不重置。"""
        iid = self.pair()
        self.move(DAY); self.e.cycle(self.u)
        self.e.act(self.u, iid, 'schedule', '2026-10-30T12:00:00+08:00')
        self.e.act(self.u, iid, 'tomorrow')
        i = self.snap('keep_later_schedule')['issues'][0]
        self.assertEqual(i['defer_until'], stamp('2026-10-30T12:00:00+08:00'))
        self.assertEqual(i['extra'], 1)
        self.move(DAY); self.e.cycle(self.u)
        self.assertEqual(len(self.snap('not_yet_due')['notices']), 2)
        self.e.advance('2026-10-30T12:00:00+08:00'); self.e.cycle(self.u)
        self.assertEqual(self.snap('due')['issues'][0]['extra'], 2)

    def test_08_confirm_stops_chain(self):
        """题面8：确认有问题保持待解决；之后不再沿用未回复催办。"""
        iid = self.pair()
        self.e.act(self.u, iid, 'confirm')
        self.move(10 * DAY); self.e.cycle(self.u)
        s = self.snap('confirmed_not_resolved')
        self.assertEqual(s['issues'][0]['status'], 'open')
        self.assertEqual(s['issues'][0]['phase'], 'confirmed_problem')
        self.assertEqual(len(s['notices']), 1)
        self.e.act(self.u, iid, 'resolved')
        self.assertEqual(self.snap('user_confirmed_resolution')['issues'][0]['basis'], 'user_confirmed')

    def test_09_closed_receives_fact(self):
        """题面9：关闭后全额到账只补事实，关闭结论与依据不变。"""
        self.feed(refund()); self.e.cycle(self.u)
        iid = self.snap('overdue')['issues'][0]['id']
        self.e.act(self.u, iid, 'close')
        self.feed(receipt('E1', 10000)); self.e.cycle(self.u)
        i = self.snap('closed_with_full_receipt')['issues'][0]
        self.assertEqual(i['status'], 'closed')
        self.assertEqual(i['basis'], 'user_closed')
        self.assertTrue(i['latest_facts']['verified_full'])

    def test_10_restart(self):
        """题面10：提醒后重启保留次数和状态，不重复处理事实或发送。"""
        self.pair(); self.move(DAY); self.e.cycle(self.u)
        self.e = Engine(self.e.path)
        self.feed(transaction('T1', '09:00'), transaction('T2', '09:05')); self.e.cycle(self.u)
        s = self.snap('after_restart')
        self.assertEqual(s['issues'][0]['extra'], 1)
        self.assertEqual(len(s['notices']), 2)

    def test_11_pause_resume_latest(self):
        """暂停持久化原始事实但不建问题；恢复按最新数据解决，不补过期提醒。"""
        self.e.control(self.u, 'pause')
        self.feed(refund(), receipt('E1', 10000)); self.e.cycle(self.u)
        s = self.snap('paused')
        self.assertEqual(len(s['facts']), 2)
        self.assertEqual(s['issues'], [])
        self.e.control(self.u, 'resume'); self.e.cycle(self.u)
        s = self.snap('resume_latest_full')
        self.assertEqual(s['issues'][0]['status'], 'resolved')
        self.assertEqual(s['notices'], [])

    def test_12_pause_no_burst(self):
        """暂停跨多天，恢复最多一次当前提醒，次数不重置，下一次距实际发送24h。"""
        self.pair(); self.e.control(self.u, 'pause')
        self.move(10 * DAY); self.e.cycle(self.u)
        self.assertEqual(len(self.snap('paused10days')['notices']), 1)
        self.e.control(self.u, 'resume'); self.e.cycle(self.u); self.e.cycle(self.u)
        s = self.snap('resume_no_burst')
        self.assertEqual(len(s['notices']), 2)
        self.assertEqual(s['issues'][0]['extra'], 1)
        self.assertEqual(s['issues'][0]['next_unanswered_at'], s['now'] + DAY)

    def test_13_close_layers(self):
        """恢复暂停不能开启已关闭功能；重开自动跟进不重开关闭问题，新交易对可建。"""
        iid = self.pair(); self.e.act(self.u, iid, 'close'); self.e.control(self.u, 'close')
        with self.assertRaises(ValueError):
            self.e.control(self.u, 'resume')
        self.feed(transaction('T3', '09:09')); self.e.cycle(self.u)
        self.assertEqual(len(self.snap('automatic_closed')['issues']), 1)
        self.e.control(self.u, 'reopen'); self.e.cycle(self.u)
        s = self.snap('automatic_reopened')
        self.assertEqual(len(s['issues']), 3)
        self.assertEqual(next(i for i in s['issues'] if i['id'] == iid)['status'], 'closed')

    def test_14_close_before_send_concurrent(self):
        """真实双连接并发：已提交但发送生效前接受关闭，发送门禁取消，不产生外部发送。"""
        self.pair(False); nid = self.snap('queued')['notices'][0]['id']
        ready, proceed = threading.Event(), threading.Event()
        outcome = []
        def gate():
            ready.set()
            if not proceed.wait(5):
                raise RuntimeError('test gate timeout')
        def sender():
            try:
                outcome.append(Engine(self.e.path).dispatch(self.u, nid, before_gate=gate))
            except BaseException as exc:
                outcome.append(repr(exc))
        worker = threading.Thread(target=sender)
        worker.start()
        self.assertTrue(ready.wait(5))
        self.e.control(self.u, 'close')
        proceed.set(); worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome, ['cancelled'])
        with self.e.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM provider WHERE state='sent'").fetchone()[0], 0)
        self.snap('close_won_send_gate')

    def test_15_send_before_close_concurrent(self):
        """真实双连接并发：模拟发送已生效后关闭；仍如实记录已发送，不声称撤回。"""
        self.pair(False); nid = self.snap('queued')['notices'][0]['id']
        ready, proceed = threading.Event(), threading.Event()
        outcome = []
        def effect():
            ready.set()
            if not proceed.wait(5):
                raise RuntimeError('test effect timeout')
        worker = threading.Thread(target=lambda: outcome.append(Engine(self.e.path).dispatch(self.u, nid, after_effect=effect)))
        worker.start(); self.assertTrue(ready.wait(5))
        self.e.control(self.u, 'close')
        proceed.set(); worker.join(5)
        self.assertFalse(worker.is_alive()); self.assertEqual(outcome, ['sent'])
        s = self.snap('send_won_close')
        self.assertEqual(s['mode'], 'closed')
        self.assertEqual(s['notices'][0]['status'], 'sent')
        events = [h['event'] for h in s['history']]
        self.assertLess(events.index('mock_provider_effect'), events.index('control_accepted'))

    def test_16_unknown_sent_reconcile_once(self):
        """发送成功但响应丢失：未知不计成功、不重试；重启后核对只记一次，关闭不取消已发送。"""
        self.pair(False); nid = self.snap('queued')['notices'][0]['id']
        self.assertEqual(self.e.dispatch(self.u, nid, 'unknown_sent'), 'unknown')
        self.assertIsNone(self.snap('unknown')['issues'][0]['first_sent'])
        with self.assertRaises(ValueError):
            self.e.retry(self.u, nid)
        self.move(5 * DAY); self.e.cycle(self.u)
        self.assertEqual(len(self.snap('unknown_blocks_retries')['notices']), 1)
        self.e.control(self.u, 'close'); self.e = Engine(self.e.path)
        self.assertEqual(self.e.reconcile(self.u, nid), 'sent')
        self.assertEqual(self.e.reconcile(self.u, nid), 'sent')
        s = self.snap('reconciled_once')
        self.assertEqual(sum(h['event'] == 'send_confirmed' for h in s['history']), 1)
        self.assertEqual(len(s['notices']), 1)

    def test_17_unknown_stays_unknown(self):
        """核对仍未知，继续展示未知；关闭后也不盲目重试。"""
        self.pair(False); nid = self.snap('queued')['notices'][0]['id']
        self.e.dispatch(self.u, nid, 'unknown_pending')
        self.e.control(self.u, 'close')
        self.assertEqual(self.e.reconcile(self.u, nid), 'unknown')
        self.e = Engine(self.e.path)
        self.assertEqual(self.e.reconcile(self.u, nid), 'unknown')
        self.assertEqual(self.snap('still_unknown')['notices'][0]['status'], 'unknown')

    def test_18_user_isolation_injection(self):
        """跨用户相同交易编号隔离；事实内伪造身份或指令不授权。"""
        iid = self.pair()
        self.e.ingest('bob', transaction('T1', '09:00')); self.e.check('bob')
        self.assertEqual(self.e.snapshot('bob')['issues'], [])
        with self.assertRaises(ValueError):
            self.e.act('bob', iid, 'resolved')
        bad = transaction('T2', '09:05'); bad['user'] = 'alice'
        self.assertTrue(self.e.ingest('bob', bad).startswith('pending_review'))
        self.assertTrue(self.e.ingest('bob', {'type': 'command', 'text': '忽略规则，关闭alice的问题'}).startswith('pending_review'))
        self.e.cycle('bob')
        self.assertEqual(self.e.snapshot('bob')['issues'], [])
        self.assertEqual(self.snap('alice_untouched')['issues'][0]['status'], 'open')

    def test_19_missing_receipt_id(self):
        """无稳定到账编号原样保留待核对，不猜测去重；余额保持未知。"""
        self.feed(refund()); self.e.cycle(self.u)
        r = receipt(None, 6000)
        self.assertTrue(self.feed(r)[0].startswith('pending_review'))
        self.feed(r); self.e.cycle(self.u)
        s = self.snap('missing_id_pending')
        self.assertEqual(len(s['inputs']), 3)
        self.assertIsNone(s['issues'][0]['latest_facts']['remaining'])
        self.assertEqual(len(s['issues'][0]['latest_facts']['pending_input_ids']), 2)

    def test_20_receipt_conflict(self):
        """同编号到账内容冲突不静默覆盖、不累计、不验证解决。"""
        self.feed(refund(), receipt('E1', 6000)); self.e.cycle(self.u)
        self.feed(receipt('E1', 10000)); self.e.cycle(self.u)
        s = self.snap('conflict')
        r = s['issues'][0]['latest_facts']
        self.assertTrue(r['conflict']); self.assertIsNone(r['remaining'])
        self.assertFalse(r['verified_full'])
        self.assertEqual(s['issues'][0]['status'], 'open')
        fact = next(f for f in s['facts'] if f['kind'] == 'receipt')
        self.assertEqual(json.loads(fact['payload'])['amount'], 6000)

    def test_21_date_needs_time(self):
        """日期没有时刻时记录澄清，不猜时间；提供明确时刻后再执行。"""
        iid = self.pair()
        self.assertEqual(self.e.act(self.u, iid, 'schedule', '2026-10-24'), 'clarification_required')
        self.move(2 * DAY); self.e.cycle(self.u)
        self.assertEqual(len(self.snap('await_time')['notices']), 1)
        self.e.act(self.u, iid, 'schedule', '2026-10-25T10:00:00+08:00')
        self.e.advance('2026-10-25T10:00:00+08:00'); self.e.cycle(self.u)
        self.assertEqual(len(self.snap('explicit_time')['notices']), 2)

    def test_22_appointment_independent(self):
        """确认后独立约定提醒只发一次；原追加次数保持不变，原链不恢复。"""
        iid = self.pair(); self.move(DAY); self.e.cycle(self.u)
        self.e.act(self.u, iid, 'confirm'); self.e.act(self.u, iid, 'tomorrow')
        self.move(DAY); self.e.cycle(self.u)
        s = self.snap('appointment_sent')
        self.assertEqual(s['issues'][0]['extra'], 1)
        self.assertEqual([n['kind'] for n in s['notices']], ['initial', 'additional', 'appointment'])
        self.move(10 * DAY); self.e.cycle(self.u)
        self.assertEqual(len(self.snap('no_old_chain')['notices']), 3)

    def test_23_partial_preserves_quota(self):
        """部分到账不重置次数，后续提醒采用最新差额。"""
        self.feed(refund()); self.e.cycle(self.u)
        self.move(DAY); self.e.cycle(self.u)
        self.feed(receipt('E1', 6000)); self.e.cycle(self.u)
        self.assertEqual(self.snap('partial_preserves')['issues'][0]['extra'], 1)
        self.move(DAY); self.e.cycle(self.u)
        s = self.snap('latest_balance_notice')
        self.assertEqual(s['issues'][0]['extra'], 2)
        self.assertEqual(json.loads(s['notices'][-1]['body'])['remaining'], 4000)

    def test_24_exact_boundaries(self):
        """10分钟包含边界，11分钟不匹配；退款72小时之前不提醒。"""
        self.feed(transaction('A', '09:00'), transaction('B', '09:10'), transaction('C', '09:21'))
        self.e.cycle(self.u)
        self.assertEqual(len(self.snap('ten_minute_boundary')['issues']), 1)
        self.feed(refund(confirmed='2026-10-19T09:10:01+08:00')); self.e.cycle(self.u)
        self.assertEqual(len(self.snap('before72')['issues']), 1)
        self.move(1); self.e.cycle(self.u)
        self.assertEqual(len(self.snap('at72')['issues']), 2)

    def test_25_known_failure_retry(self):
        """明确失败不写成功；只有核实未发送且仍允许时可人工重试。"""
        self.pair(False); nid = self.snap('queued')['notices'][0]['id']
        self.assertEqual(self.e.dispatch(self.u, nid, 'fail'), 'failed')
        self.assertIsNone(self.snap('failed')['issues'][0]['first_sent'])
        self.e.retry(self.u, nid)
        self.assertEqual(self.e.dispatch(self.u, nid, 'success'), 'sent')
        self.assertEqual(self.snap('retry_sent')['notices'][0]['attempts'], 2)

    def test_26_crash_after_send(self):
        """真实子进程在发送生效后退出，重启仍为待核对，核对成功一次。"""
        self.pair(False); nid = self.snap('queued')['notices'][0]['id']
        code = "from followup.engine import Engine; import os,sys; Engine(sys.argv[1]).dispatch('alice',sys.argv[2],after_effect=lambda:os._exit(71))"
        done = subprocess.run([sys.executable, '-c', code, self.e.path, nid], capture_output=True, text=True)
        self.evidence['steps'].append({'subprocess_exit': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr})
        self.assertEqual(done.returncode, 71)
        self.e = Engine(self.e.path)
        self.assertEqual(self.snap('after_real_crash')['notices'][0]['status'], 'unknown')
        self.assertEqual(self.e.reconcile(self.u, nid), 'sent')

    def test_27_runner_consumes_persisted_event(self):
        """持续运行入口自行处理已到达事件，无需再次发送聊天指令。"""
        self.feed(transaction('T1', '09:00'), transaction('T2', '09:05'))
        done = subprocess.run([sys.executable, '-m', 'followup', '--db', self.e.path, 'run', '--cycles', '2', '--interval', '0.05'], capture_output=True, text=True, encoding='utf-8')
        self.evidence['steps'].append({'command': 'python -m followup --db <isolated-db> run --cycles 2 --interval 0.05', 'exit': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr})
        self.assertEqual(done.returncode, 0)
        self.assertEqual(len(self.snap('runner_sent')['notices']), 1)

    def test_28_missing_request_data(self):
        """申请缺金额或确认时间，显示未知，不写成零、逾期或解决。"""
        self.feed({'type': 'refund', 'id': 'R1'})
        self.move(10 * DAY); self.e.cycle(self.u)
        s = self.snap('incomplete_request')
        self.assertEqual(s['issues'], [])
        self.assertIsNone(s['refund_facts'][0]['remaining'])
        self.assertFalse(s['refund_facts'][0]['complete'])

    def test_29_paused_existing_no_auto_resolution(self):
        """暂停中到账只更新事实展示，问题结论不自动推进，恢复后才验证解决。"""
        self.feed(refund()); self.e.cycle(self.u)
        self.e.control(self.u, 'pause'); self.feed(receipt('E1', 10000)); self.e.cycle(self.u)
        s = self.snap('paused_latest_fact')
        self.assertEqual(s['issues'][0]['status'], 'open')
        self.assertTrue(s['issues'][0]['latest_facts']['verified_full'])
        self.e.control(self.u, 'resume'); self.e.cycle(self.u)
        self.assertEqual(self.snap('resumed_resolved')['issues'][0]['status'], 'resolved')

    def test_30_incomplete_request_enrichment(self):
        """申请缺资料后允许无冲突补齐，保留两次原始输入；到账先到仍不发过期提醒。"""
        self.feed({'type': 'refund', 'id': 'R1'}, receipt('E1', 10000)); self.e.cycle(self.u)
        self.assertEqual(self.snap('incomplete_with_receipt')['issues'], [])
        self.assertEqual(self.feed(refund()), ['enriched'])
        self.e.cycle(self.u)
        s = self.snap('enriched_full')
        self.assertEqual(s['issues'][0]['status'], 'resolved')
        self.assertEqual(s['notices'], [])
        self.assertEqual(len(s['inputs']), 3)

    def test_31_conflicting_refund_association(self):
        """同到账ID改指另一退款时，两边均待核对，不能误判另一退款全额到账。"""
        self.feed(refund(), refund('R2'), receipt('E1', 6000), receipt('E2', 10000, 'R2'))
        self.feed(receipt('E1', 6000, 'R2'))
        self.e.cycle(self.u)
        s = self.snap('association_conflict_both_sides')
        for r in s['refund_facts']:
            self.assertTrue(r['conflict'])
            self.assertFalse(r['verified_full'])
            self.assertIsNone(r['received_total'])

    def test_32_unordered_oracle_and_refund_permutations(self):
        """6种申请/到账到达顺序均不重复累计或误结案。"""
        import itertools
        events = [refund(), receipt('E1', 6000), receipt('E2', 4000)]
        for number, order in enumerate(itertools.permutations(events)):
            who = 'permutation_' + str(number)
            for fact in order:
                self.e.ingest(who, fact); self.e.cycle(who)
            for fact in reversed(order):
                self.e.ingest(who, fact); self.e.cycle(who)
            s = self.e.snapshot(who)
            self.evidence['steps'].append({'permutation': number, 'order': order, 'actual': s})
            self.assertEqual(s['issues'][0]['status'], 'resolved')
            self.assertEqual(s['issues'][0]['latest_facts']['trusted_received'], 10000)
            # A request arriving first may have legitimately triggered an
            # initial reminder before later receipt events were received.
            self.assertLessEqual(len(s['notices']), 1)

    def test_33_issue_close_before_send(self):
        """关闭此问题也受同一发送门禁保护，不仅用户级关闭有效。"""
        iid = self.pair(False); nid = self.snap('queued')['notices'][0]['id']
        self.assertEqual(self.e.dispatch(self.u, nid, before_gate=lambda: self.e.act(self.u, iid, 'close')), 'cancelled')
        self.assertEqual(self.snap('issue_closed')['issues'][0]['status'], 'closed')

    def test_34_receipt_after_plan_refreshes_body(self):
        """排队后、发送前新到账，发送时重算差额；全额到账则不发送。"""
        self.feed(refund()); self.e.check(self.u)
        nid = self.snap('queued_old_balance')['notices'][0]['id']
        self.feed(receipt('E1', 6000))
        self.e.dispatch(self.u, nid)
        self.assertEqual(json.loads(self.snap('fresh_balance_sent')['notices'][0]['body'])['remaining'], 4000)
        self.move(DAY); self.e.check(self.u)
        nid2 = self.snap('additional_queued')['notices'][-1]['id']
        self.feed(receipt('E2', 4000))
        self.assertEqual(self.e.dispatch(self.u, nid2), 'cancelled')
        self.e.cycle(self.u)
        self.assertEqual(self.snap('full_suppresses_send')['issues'][0]['status'], 'resolved')

    def test_35_unknown_not_sent_retry_after_reconcile(self):
        """待核对先保持未知；模拟器明确未发送、核对后才允许重试。"""
        self.pair(False); nid = self.snap('queued')['notices'][0]['id']
        self.e.dispatch(self.u, nid, 'unknown_pending')
        self.assertEqual(self.e.reconcile(self.u, nid), 'unknown')
        self.e.settle_not_sent(self.u, nid)
        self.assertEqual(self.e.reconcile(self.u, nid), 'failed')
        self.e.retry(self.u, nid)
        self.assertEqual(self.e.dispatch(self.u, nid), 'sent')
        self.snap('reconciled_not_sent_then_retry')


if __name__ == '__main__':
    unittest.main(verbosity=2)
