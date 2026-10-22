import argparse
import json
import sys
import time
from pathlib import Path

from .engine import Engine, packed


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description='账单问题持续跟进：本地模拟，不连接银行或商户')
    p.add_argument('--db', default='data/followup.sqlite')
    p.add_argument('--user', default='demo')
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('init'); s.add_argument('--at', default='2026-10-22T09:10:00+08:00'); s.add_argument('--mode', choices=['simulated', 'real'], default='simulated')
    s = sub.add_parser('ingest'); s.add_argument('file', help='JSON数组或单个事实文件')
    s = sub.add_parser('advance'); s.add_argument('to')
    s = sub.add_parser('control'); s.add_argument('action', choices=['pause', 'resume', 'close', 'reopen'])
    s = sub.add_parser('act'); s.add_argument('issue'); s.add_argument('action', choices=['normal', 'resolved', 'close', 'confirm', 'tomorrow', 'schedule']); s.add_argument('--at')
    s = sub.add_parser('tick'); s.add_argument('--behavior', default='success', choices=['success', 'fail', 'unknown_sent', 'unknown_pending'])
    sub.add_parser('plan')
    s = sub.add_parser('dispatch'); s.add_argument('operation'); s.add_argument('--behavior', default='success', choices=['success', 'fail', 'unknown_sent', 'unknown_pending'])
    for name in ('reconcile', 'retry', 'settle-not-sent'):
        s = sub.add_parser(name); s.add_argument('operation')
    sub.add_parser('show')
    s = sub.add_parser('run'); s.add_argument('--interval', type=float, default=1); s.add_argument('--cycles', type=int, default=0)
    a = p.parse_args()
    e = Engine(a.db)
    try:
        if a.command == 'init':
            e.init(a.at, a.mode); result = {'initialized': a.db, 'clock': a.mode}
        elif a.command == 'ingest':
            data = json.loads(Path(a.file).read_text(encoding='utf-8-sig'))
            result = {'ingest': [e.ingest(a.user, item) for item in (data if isinstance(data, list) else [data])], 'notifications': e.cycle(a.user)}
        elif a.command == 'advance':
            e.advance(a.to); result = {'notifications': e.cycle()}
        elif a.command == 'control':
            e.control(a.user, a.action); result = {'notifications': e.cycle(a.user)}
        elif a.command == 'act':
            result = {'action': e.act(a.user, a.issue, a.action, a.at), 'notifications': e.cycle(a.user)}
        elif a.command == 'tick':
            result = e.cycle(a.user, a.behavior)
        elif a.command == 'plan':
            e.check(a.user); result = e.snapshot(a.user)
        elif a.command == 'dispatch':
            result = e.dispatch(a.user, a.operation, a.behavior)
        elif a.command == 'reconcile':
            result = e.reconcile(a.user, a.operation)
        elif a.command == 'retry':
            e.retry(a.user, a.operation); result = {'queued': a.operation}
        elif a.command == 'settle-not-sent':
            e.settle_not_sent(a.user, a.operation); result = {'simulated_provider': 'not_sent'}
        elif a.command == 'show':
            result = e.snapshot(a.user)
        else:
            count = 0
            while True:
                print(packed({'cycle': count + 1, 'notifications': e.cycle()}), flush=True)
                count += 1
                if a.cycles and count >= a.cycles:
                    break
                time.sleep(max(0.05, a.interval))
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
