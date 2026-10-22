from __future__ import annotations

import itertools
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

BJ = timezone(timedelta(hours=8))
DAY = 86400


def stamp(value):
    if type(value) in (int, float):
        return int(value)
    dt = datetime.fromisoformat(value)
    return int((dt if dt.tzinfo else dt.replace(tzinfo=BJ)).timestamp())


def iso(value):
    return datetime.fromtimestamp(value, BJ).isoformat() if value is not None else None


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Engine:
    """All mutations use BEGIN IMMEDIATE, including mock delivery and control commands.

    The mock provider's actual send linearizes at the provider row COMMIT. Real
    network delivery would require an equivalent provider-side cancellation gate;
    this demo deliberately makes no claim about atomicity across real services.
    """

    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS clock(id INTEGER PRIMARY KEY CHECK(id=1), now INTEGER NOT NULL, mode TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS users(user TEXT PRIMARY KEY, mode TEXT NOT NULL DEFAULT 'active');
            CREATE TABLE IF NOT EXISTS inputs(seq INTEGER PRIMARY KEY AUTOINCREMENT,user TEXT NOT NULL,received INTEGER NOT NULL,payload TEXT NOT NULL,result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS facts(user TEXT,kind TEXT,id TEXT,payload TEXT NOT NULL,conflict INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user,kind,id));
            CREATE TABLE IF NOT EXISTS issues(user TEXT,id TEXT,kind TEXT,refs TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',phase TEXT NOT NULL DEFAULT 'awaiting_reply',basis TEXT,created INTEGER NOT NULL,first_sent INTEGER,last_sent INTEGER,extra INTEGER NOT NULL DEFAULT 0,defer_until INTEGER,needs_time INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user,id));
            CREATE UNIQUE INDEX IF NOT EXISTS issue_refs_unique ON issues(user,kind,refs);
            CREATE TABLE IF NOT EXISTS appointments(user TEXT,id TEXT,issue TEXT,due INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',PRIMARY KEY(user,id));
            CREATE TABLE IF NOT EXISTS notices(user TEXT,id TEXT,issue TEXT,kind TEXT,slot TEXT,status TEXT NOT NULL,created INTEGER NOT NULL,submitted INTEGER,sent_at INTEGER,body TEXT NOT NULL,behavior TEXT NOT NULL DEFAULT 'success',attempts INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user,id),UNIQUE(user,issue,kind,slot));
            CREATE TABLE IF NOT EXISTS provider(user TEXT,op TEXT,state TEXT NOT NULL,sent_at INTEGER,body TEXT NOT NULL,PRIMARY KEY(user,op));
            CREATE TABLE IF NOT EXISTS history(seq INTEGER PRIMARY KEY AUTOINCREMENT,user TEXT NOT NULL,issue TEXT,at INTEGER NOT NULL,event TEXT NOT NULL,detail TEXT NOT NULL);
            """)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def tx(self):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise

    def _now(self, c):
        row = c.execute("SELECT * FROM clock WHERE id=1").fetchone()
        if not row:
            raise ValueError("先初始化数据库时钟")
        return int(time.time()) if row['mode'] == 'real' else row['now']

    def _user(self, c, user):
        if not isinstance(user, str) or not user.strip():
            raise ValueError("需要可信入口指定的用户ID")
        c.execute("INSERT OR IGNORE INTO users(user) VALUES(?)", (user,))

    def _audit(self, c, user, issue, event, detail):
        c.execute("INSERT INTO history(user,issue,at,event,detail) VALUES(?,?,?,?,?)",
                  (user, issue, self._now(c), event, packed(detail)))

    def init(self, now, mode='simulated'):
        if mode not in ('simulated', 'real'):
            raise ValueError("未知时钟模式")
        with self.tx() as c:
            if c.execute("SELECT 1 FROM clock").fetchone():
                raise ValueError("已初始化；不能重置已有状态或时钟")
            c.execute("INSERT INTO clock VALUES(1,?,?)", (stamp(now), mode))

    def advance(self, to):
        with self.tx() as c:
            row = c.execute("SELECT * FROM clock WHERE id=1").fetchone()
            if not row or row['mode'] != 'simulated':
                raise ValueError("只有模拟时钟可推进")
            value = stamp(to)
            if value < row['now']:
                raise ValueError("模拟时间不能倒退")
            c.execute("UPDATE clock SET now=? WHERE id=1", (value,))

    def _validate(self, data):
        kind = data.get('type')
        if kind not in ('transaction', 'refund', 'receipt'):
            raise ValueError("只接收交易、退款申请、到账事实；外部文本不作为命令")
        if 'user' in data or 'user_id' in data:
            raise ValueError("外部事实不能指定用户身份")
        if not isinstance(data.get('id'), str) or not data['id'].strip():
            raise ValueError("缺少稳定事件编号，保留待核对")
        result = dict(data)
        for field in ('amount',):
            if field in data and (type(data[field]) is not int or data[field] <= 0):
                raise ValueError("金额必须是正整数分，缺失不得写成零")
        if kind == 'transaction':
            if not isinstance(data.get('merchant'), str) or not data['merchant'] or 'amount' not in data or 'at' not in data:
                raise ValueError("交易缺少商户、金额或时间")
            result['at'] = stamp(data['at'])
        if kind == 'refund' and data.get('confirmed_at') is not None:
            result['confirmed_at'] = stamp(data['confirmed_at'])
        if kind == 'receipt':
            if not isinstance(data.get('refund_id'), str) or not data['refund_id'] or 'amount' not in data or 'at' not in data:
                raise ValueError("到账缺少退款编号、金额或时间")
            result['at'] = stamp(data['at'])
        return result

    def ingest(self, user, data):
        with self.tx() as c:
            self._user(c, user)
            now = self._now(c)
            try:
                value = self._validate(data)
            except (ValueError, TypeError, AttributeError) as exc:
                result = 'pending_review: ' + str(exc)
            else:
                old = c.execute("SELECT * FROM facts WHERE user=? AND kind=? AND id=?", (user, value['type'], value['id'])).fetchone()
                body = packed(value)
                if old and old['payload'] == body:
                    result = 'duplicate'
                elif old:
                    previous = json.loads(old['payload'])
                    # An incomplete request can be enriched, but established
                    # values never change silently. Both raw inputs remain.
                    enrichment = value['type'] == 'refund' and not old['conflict'] and all(
                        previous.get(k) is None or v is None or previous[k] == v for k, v in value.items()
                    )
                    if enrichment:
                        merged = {**previous, **{k: v for k, v in value.items() if v is not None}}
                        c.execute("UPDATE facts SET payload=? WHERE user=? AND kind=? AND id=?", (packed(merged), user, value['type'], value['id']))
                        result = 'enriched'
                    else:
                        c.execute("UPDATE facts SET conflict=1 WHERE user=? AND kind=? AND id=?", (user, value['type'], value['id']))
                        result = 'conflict_pending_review'
                else:
                    c.execute("INSERT INTO facts(user,kind,id,payload) VALUES(?,?,?,?)", (user, value['type'], value['id'], body))
                    result = 'accepted'
            c.execute("INSERT INTO inputs(user,received,payload,result) VALUES(?,?,?,?)", (user, now, packed(data), result))
            self._audit(c, user, None, 'fact_received', {'result': result, 'payload': data})
            return result

    def _facts(self, c, user, kind):
        return [(json.loads(r['payload']), bool(r['conflict'])) for r in c.execute("SELECT * FROM facts WHERE user=? AND kind=? ORDER BY id", (user, kind))]

    def _refund(self, c, user, rid):
        request = c.execute("SELECT * FROM facts WHERE user=? AND kind='refund' AND id=?", (user, rid)).fetchone()
        payload = json.loads(request['payload']) if request else {}
        receipts = [(p, conflict) for p, conflict in self._facts(c, user, 'receipt') if p['refund_id'] == rid]
        # Raw receipts without a trustworthy ID cannot be silently treated as zero.
        unresolved = []
        competing_association = False
        for raw in c.execute("SELECT seq,payload,result FROM inputs WHERE user=? AND (result LIKE 'pending_review:%' OR result='conflict_pending_review')", (user,)):
            p = json.loads(raw['payload'])
            if isinstance(p, dict) and p.get('type') == 'receipt' and p.get('refund_id') == rid:
                unresolved.append(raw['seq'])
                competing_association = competing_association or raw['result'] == 'conflict_pending_review'
        conflict = bool(request and request['conflict']) or any(bad for _, bad in receipts) or competing_association
        complete = bool(payload.get('amount') and payload.get('confirmed_at') is not None)
        trusted_total = sum(p['amount'] for p, bad in receipts if not bad)
        reliable = complete and not conflict and not unresolved
        return {'refund_id': rid, 'expected': payload.get('amount'), 'confirmed_at': payload.get('confirmed_at'),
                'trusted_received': trusted_total, 'received_total': trusted_total if not conflict and not unresolved else None,
                'remaining': max(0, payload['amount'] - trusted_total) if reliable else None,
                'complete': complete, 'conflict': conflict, 'pending_input_ids': unresolved, 'reliable': reliable,
                'receipt_ids': [p['id'] for p, _ in receipts], 'verified_full': reliable and trusted_total >= payload['amount']}

    def _eligible_issue(self, c, issue):
        if issue['kind'] == 'refund':
            r = self._refund(c, issue['user'], json.loads(issue['refs'])[0])
            return r['reliable'] and not r['verified_full'] and self._now(c) >= r['confirmed_at'] + 3 * DAY
        for tid in json.loads(issue['refs']):
            row = c.execute("SELECT conflict FROM facts WHERE user=? AND kind='transaction' AND id=?", (issue['user'], tid)).fetchone()
            if not row or row['conflict']:
                return False
        return True

    def _cancel(self, c, user, issue=None, reason='control'):
        clause, args = (" AND issue=?", (user, issue)) if issue else ("", (user,))
        c.execute("UPDATE notices SET status='cancelled' WHERE user=? AND status='queued'" + clause, args)
        self._audit(c, user, issue, 'queued_notices_cancelled', {'reason': reason})

    def _new_issue(self, c, user, iid, kind, refs, now, status='open', basis=None):
        cur = c.execute("INSERT OR IGNORE INTO issues(user,id,kind,refs,created,status,basis) VALUES(?,?,?,?,?,?,?)", (user, iid, kind, packed(refs), now, status, basis))
        if cur.rowcount:
            self._audit(c, user, iid, 'issue_created', {'kind': kind, 'refs': refs, 'status': status, 'basis': basis})

    def _plan(self, c, user):
        now = self._now(c)
        transactions = [p for p, conflict in self._facts(c, user, 'transaction') if not conflict]
        for a, b in itertools.combinations(transactions, 2):
            if a['merchant'] == b['merchant'] and a['amount'] == b['amount'] and abs(a['at'] - b['at']) <= 600:
                refs = sorted([a['id'], b['id']])
                self._new_issue(c, user, 'dup:' + uuid.uuid5(uuid.NAMESPACE_URL, packed(refs)).hex, 'duplicate', refs, now)
        for p, conflict in self._facts(c, user, 'refund'):
            info = self._refund(c, user, p['id'])
            if info['verified_full']:
                self._new_issue(c, user, 'refund:' + p['id'], 'refund', [p['id']], now, 'resolved', 'verified_receipts')
            elif info['reliable'] and now >= info['confirmed_at'] + 3 * DAY:
                self._new_issue(c, user, 'refund:' + p['id'], 'refund', [p['id']], now)
        for issue in c.execute("SELECT * FROM issues WHERE user=? ORDER BY id", (user,)).fetchall():
            if issue['status'] != 'open':
                continue
            iid = issue['id']
            if issue['kind'] == 'refund' and self._refund(c, user, json.loads(issue['refs'])[0])['verified_full']:
                c.execute("UPDATE issues SET status='resolved',basis='verified_receipts' WHERE user=? AND id=?", (user, iid))
                self._cancel(c, user, iid, 'verified_full_refund')
                c.execute("UPDATE appointments SET status='cancelled' WHERE user=? AND issue=? AND status='pending'", (user, iid))
                self._audit(c, user, iid, 'resolved', {'basis': 'verified_receipts'})
                continue
            if not self._eligible_issue(c, issue) or issue['needs_time']:
                continue
            if c.execute("SELECT 1 FROM notices WHERE user=? AND issue=? AND status IN ('queued','unknown')", (user, iid)).fetchone():
                continue
            if issue['defer_until'] is not None and now < issue['defer_until']:
                continue
            if issue['phase'] == 'confirmed_problem':
                appointment = c.execute("SELECT * FROM appointments WHERE user=? AND issue=? AND status='pending' AND due<=? ORDER BY due,id LIMIT 1", (user, iid, now)).fetchone()
                if appointment:
                    self._queue(c, issue, 'appointment', appointment['id'])
            elif issue['first_sent'] is None:
                self._queue(c, issue, 'initial', '0')
            elif issue['extra'] < 2 and now >= issue['last_sent'] + DAY:
                self._queue(c, issue, 'additional', str(issue['extra'] + 1))

    def _body(self, c, issue):
        refs = json.loads(issue['refs'])
        if issue['kind'] == 'duplicate':
            return packed({'message': '疑似重复消费，请确认是否为两次正常购买；尚未证实错扣', 'transaction_ids': refs})
        return packed({'message': '退款满72小时仍未全额到账', **self._refund(c, issue['user'], refs[0])})

    def _queue(self, c, issue, kind, slot):
        existing = c.execute("SELECT * FROM notices WHERE user=? AND issue=? AND kind=? AND slot=?", (issue['user'], issue['id'], kind, slot)).fetchone()
        if existing:
            if existing['status'] == 'cancelled':
                c.execute("UPDATE notices SET status='queued',body=? WHERE user=? AND id=?", (self._body(c, issue), issue['user'], existing['id']))
            return
        nid = uuid.uuid4().hex
        c.execute("INSERT INTO notices(user,id,issue,kind,slot,status,created,body) VALUES(?,?,?,?,?,'queued',?,?)", (issue['user'], nid, issue['id'], kind, slot, self._now(c), self._body(c, issue)))
        self._audit(c, issue['user'], issue['id'], 'notice_queued', {'operation_id': nid, 'kind': kind, 'slot': slot})

    def check(self, user=None):
        with self.tx() as c:
            if user:
                self._user(c, user)
            users = c.execute("SELECT * FROM users" + (" WHERE user=?" if user else ""), (user,) if user else ()).fetchall()
            for u in users:
                if u['mode'] == 'active':
                    self._plan(c, u['user'])

    def _can_send(self, c, n):
        u = c.execute("SELECT mode FROM users WHERE user=?", (n['user'],)).fetchone()
        i = c.execute("SELECT * FROM issues WHERE user=? AND id=?", (n['user'], n['issue'])).fetchone()
        now = self._now(c)
        if not u or u['mode'] != 'active' or not i or i['status'] != 'open' or i['needs_time']:
            return False
        if not self._eligible_issue(c, i) or (i['defer_until'] is not None and now < i['defer_until']):
            return False
        if n['kind'] == 'appointment':
            a = c.execute("SELECT * FROM appointments WHERE user=? AND id=?", (n['user'], n['slot'])).fetchone()
            return i['phase'] == 'confirmed_problem' and a and a['status'] == 'pending' and a['due'] <= now
        if i['phase'] != 'awaiting_reply':
            return False
        if n['kind'] == 'initial':
            return i['first_sent'] is None
        return i['extra'] < 2 and str(i['extra'] + 1) == n['slot'] and i['last_sent'] is not None and now >= i['last_sent'] + DAY

    def dispatch(self, user, nid, behavior=None, before_gate=None, after_effect=None):
        if behavior is not None and behavior not in ('success', 'fail', 'unknown_sent', 'unknown_pending'):
            raise ValueError("未知模拟结果")
        with self.tx() as c:
            n = c.execute("SELECT * FROM notices WHERE user=? AND id=?", (user, nid)).fetchone()
            if not n:
                raise ValueError("当前用户无此通知")
            if n['status'] != 'queued':
                return n['status']
            if not self._can_send(c, n):
                c.execute("UPDATE notices SET status='cancelled' WHERE user=? AND id=?", (user, nid))
                return 'cancelled'
            c.execute("UPDATE notices SET status='unknown',submitted=?,attempts=attempts+1,behavior=? WHERE user=? AND id=?", (self._now(c), behavior or n['behavior'], user, nid))
            self._audit(c, user, n['issue'], 'send_submitted', {'operation_id': nid, 'simulated_behavior': behavior or n['behavior']})
        if before_gate:
            before_gate()
        with self.tx() as c:
            n = c.execute("SELECT * FROM notices WHERE user=? AND id=?", (user, nid)).fetchone()
            old = c.execute("SELECT * FROM provider WHERE user=? AND op=?", (user, nid)).fetchone()
            if old and old['state'] == 'sent':
                result = 'sent'
            elif old and old['state'] == 'pending':
                return 'unknown'
            elif not self._can_send(c, n):
                c.execute("INSERT OR REPLACE INTO provider VALUES(?,?,'not_sent',NULL,?)", (user, nid, n['body']))
                c.execute("UPDATE notices SET status='cancelled' WHERE user=? AND id=?", (user, nid))
                self._audit(c, user, n['issue'], 'send_gate_cancelled', {'operation_id': nid})
                return 'cancelled'
            else:
                issue = c.execute("SELECT * FROM issues WHERE user=? AND id=?", (user, n['issue'])).fetchone()
                body = self._body(c, issue)
                c.execute("UPDATE notices SET body=? WHERE user=? AND id=?", (body, user, nid))
                result = {'success': 'sent', 'unknown_sent': 'sent', 'fail': 'not_sent', 'unknown_pending': 'pending'}[n['behavior']]
                c.execute("INSERT OR REPLACE INTO provider VALUES(?,?,?,?,?)", (user, nid, result, self._now(c) if result == 'sent' else None, body))
                self._audit(c, user, n['issue'], 'mock_provider_effect', {'operation_id': nid, 'state': result})
        if after_effect:
            after_effect()
        if n['behavior'] in ('unknown_sent', 'unknown_pending'):
            return 'unknown'
        return self.reconcile(user, nid)

    def reconcile(self, user, nid):
        # Explicit query is allowed even while closed; never submits a send.
        with self.tx() as c:
            n = c.execute("SELECT * FROM notices WHERE user=? AND id=?", (user, nid)).fetchone()
            if not n:
                raise ValueError("当前用户无此通知")
            if n['status'] != 'unknown':
                return n['status']
            p = c.execute("SELECT * FROM provider WHERE user=? AND op=?", (user, nid)).fetchone()
            if not p or p['state'] == 'pending':
                self._audit(c, user, n['issue'], 'reconcile_unknown', {'operation_id': nid})
                return 'unknown'
            if p['state'] == 'not_sent':
                c.execute("UPDATE notices SET status='failed' WHERE user=? AND id=?", (user, nid))
                self._audit(c, user, n['issue'], 'reconcile_not_sent', {'operation_id': nid})
                return 'failed'
            c.execute("UPDATE notices SET status='sent',sent_at=? WHERE user=? AND id=?", (p['sent_at'], user, nid))
            if n['kind'] == 'initial':
                c.execute("UPDATE issues SET first_sent=?,last_sent=? WHERE user=? AND id=?", (p['sent_at'], p['sent_at'], user, n['issue']))
            elif n['kind'] == 'additional':
                c.execute("UPDATE issues SET extra=extra+1,last_sent=? WHERE user=? AND id=?", (p['sent_at'], user, n['issue']))
            else:
                c.execute("UPDATE appointments SET status='sent' WHERE user=? AND id=?", (user, n['slot']))
            self._audit(c, user, n['issue'], 'send_confirmed', {'operation_id': nid, 'sent_at': p['sent_at'], 'kind': n['kind']})
            return 'sent'

    def settle_not_sent(self, user, nid):
        """Simulator-only: provider explicitly reports a pending operation never sent."""
        with self.tx() as c:
            p = c.execute("SELECT * FROM provider WHERE user=? AND op=?", (user, nid)).fetchone()
            if not p or p['state'] != 'pending':
                raise ValueError("只能将模拟的pending结果核实为未发送")
            c.execute("UPDATE provider SET state='not_sent' WHERE user=? AND op=?", (user, nid))
            self._audit(c, user, None, 'simulator_settled_not_sent', {'operation_id': nid})

    def retry(self, user, nid):
        with self.tx() as c:
            n = c.execute("SELECT * FROM notices WHERE user=? AND id=?", (user, nid)).fetchone()
            p = c.execute("SELECT * FROM provider WHERE user=? AND op=?", (user, nid)).fetchone()
            if not n or n['status'] != 'failed' or not p or p['state'] != 'not_sent':
                raise ValueError("只能重试已核实未发送的失败操作；未知不能重试")
            if not self._can_send(c, n):
                raise ValueError("当前设置或问题状态不允许发送")
            # Failure injection is per attempt, not a permanent property of the
            # business reminder. Keep prior settings in send_submitted history.
            c.execute("UPDATE notices SET status='queued',behavior='success' WHERE user=? AND id=?", (user, nid))
            self._audit(c, user, n['issue'], 'manual_retry_authorized', {'operation_id': nid})

    def control(self, user, action):
        with self.tx() as c:
            self._user(c, user)
            mode = c.execute("SELECT mode FROM users WHERE user=?", (user,)).fetchone()['mode']
            if action == 'pause':
                if mode == 'closed':
                    raise ValueError("自动跟进已关闭，暂停不能改变关闭状态")
                new = 'paused'
            elif action == 'resume':
                if mode != 'paused':
                    raise ValueError("恢复只适用于暂停；已关闭须明确reopen")
                new = 'active'
            elif action == 'close':
                new = 'closed'
            elif action == 'reopen':
                new = 'active'
            else:
                raise ValueError("未知用户开关动作")
            c.execute("UPDATE users SET mode=? WHERE user=?", (new, user))
            if new != 'active':
                self._cancel(c, user, reason='user_' + new)
            self._audit(c, user, None, 'control_accepted', {'action': action, 'mode': new})

    def act(self, user, iid, action, at=None):
        with self.tx() as c:
            self._user(c, user)
            i = c.execute("SELECT * FROM issues WHERE user=? AND id=?", (user, iid)).fetchone()
            if not i:
                raise ValueError("当前用户无此问题")
            if i['status'] != 'open':
                raise ValueError("问题已结案或关闭，不自动重开")
            now = self._now(c)
            if action in ('normal', 'resolved', 'close'):
                if action == 'normal' and i['kind'] != 'duplicate':
                    raise ValueError("正常两次购买只适用于重复消费")
                status = {'normal': 'normal', 'resolved': 'resolved', 'close': 'closed'}[action]
                basis = {'normal': 'user_normal_purchase', 'resolved': 'user_confirmed', 'close': 'user_closed'}[action]
                c.execute("UPDATE issues SET status=?,basis=? WHERE user=? AND id=?", (status, basis, user, iid))
                self._cancel(c, user, iid, action)
                c.execute("UPDATE appointments SET status='cancelled' WHERE user=? AND issue=? AND status='pending'", (user, iid))
            elif action == 'confirm':
                c.execute("UPDATE issues SET phase='confirmed_problem' WHERE user=? AND id=?", (user, iid))
                self._cancel(c, user, iid, 'confirmed_problem')
            elif action in ('tomorrow', 'schedule'):
                if action == 'schedule' and (not isinstance(at, str) or ('T' not in at and ' ' not in at)):
                    c.execute("UPDATE issues SET needs_time=1 WHERE user=? AND id=?", (user, iid))
                    self._cancel(c, user, iid, 'clarify_time')
                    self._audit(c, user, iid, 'clarification_required', {'date': at, 'message': '请明确北京时间几点提醒'})
                    return 'clarification_required'
                existing = i['defer_until'] or now
                if i['phase'] == 'confirmed_problem':
                    old = c.execute("SELECT MAX(due) FROM appointments WHERE user=? AND issue=? AND status='pending'", (user, iid)).fetchone()[0]
                    existing = max(existing, old or now)
                elif i['last_sent'] is not None:
                    existing = max(existing, i['last_sent'] + DAY)
                due = max(now + DAY, existing) if action == 'tomorrow' else stamp(at)
                if due <= now:
                    raise ValueError("明确约定须为未来时间")
                self._cancel(c, user, iid, 'rescheduled')
                c.execute("UPDATE issues SET defer_until=?,needs_time=0 WHERE user=? AND id=?", (due, user, iid))
                if i['phase'] == 'confirmed_problem':
                    c.execute("UPDATE appointments SET status='superseded' WHERE user=? AND issue=? AND status='pending'", (user, iid))
                    c.execute("INSERT INTO appointments VALUES(?,?,?,?,'pending')", (user, uuid.uuid4().hex, iid, due))
            else:
                raise ValueError("未知问题动作")
            self._audit(c, user, iid, 'user_action', {'action': action, 'at': at})
            return 'accepted'

    def cycle(self, user=None, behavior='success'):
        self.check(user)
        with self.db() as c:
            rows = c.execute("SELECT n.user,n.id FROM notices n JOIN users u ON n.user=u.user WHERE n.status='queued' AND u.mode='active'" + (" AND n.user=?" if user else "") + " ORDER BY n.created,n.id", (user,) if user else ()).fetchall()
        return [{'user': r['user'], 'operation_id': r['id'], 'result': self.dispatch(r['user'], r['id'], behavior)} for r in rows]

    def snapshot(self, user):
        # Query is read-only: never evaluates or creates issues, even in active mode.
        with self.db() as c:
            u = c.execute("SELECT * FROM users WHERE user=?", (user,)).fetchone()
            issues = [dict(r) for r in c.execute("SELECT * FROM issues WHERE user=? ORDER BY id", (user,))]
            for i in issues:
                i['refs'] = json.loads(i['refs'])
                if i['kind'] == 'refund':
                    i['latest_facts'] = self._refund(c, user, i['refs'][0])
                i['next_unanswered_at'] = None
                if i['status'] == 'open' and i['phase'] == 'awaiting_reply' and not i['needs_time'] and (i['first_sent'] is None or i['extra'] < 2):
                    i['next_unanswered_at'] = max(i['last_sent'] + DAY if i['last_sent'] is not None else i['created'], i['defer_until'] or i['created'])
                if i['status'] == 'open' and i['phase'] == 'awaiting_reply' and i['extra'] == 2:
                    i['phase_display'] = 'unanswered_limit_reached'
            result = {'now': self._now(c), 'now_beijing': iso(self._now(c)), 'user': user, 'mode': u['mode'] if u else None, 'issues': issues}
            for key, table in [('facts', 'facts'), ('inputs', 'inputs'), ('notices', 'notices'), ('appointments', 'appointments'), ('history', 'history')]:
                result[key] = [dict(r) for r in c.execute(f"SELECT * FROM {table} WHERE user=? ORDER BY rowid", (user,))]
            for i in issues:
                pending = [n['id'] for n in result['notices'] if n['issue'] == i['id'] and n['status'] == 'unknown']
                i['pending_reconciliation'] = pending
                i['automatic_reminders_enabled'] = bool(u and u['mode'] == 'active' and i['status'] == 'open' and not i['needs_time'] and not pending)
                if pending:
                    i['next_unanswered_at'] = None
            result['refund_facts'] = [self._refund(c, user, p['id']) for p, _ in self._facts(c, user, 'refund')]
            return result
