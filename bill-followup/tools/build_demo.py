"""Produce a self-contained 7-minute replay from real Engine calls and snapshots."""
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from followup.engine import DAY, Engine

sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).resolve().parents[1]
out = root / 'evidence' / ('demo-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
out.mkdir(parents=True)
engine = Engine(out / 'demo.sqlite')
engine.init('2026-10-22T09:10:00+08:00')
frames, calls = [], []


def call(name, *args):
    try:
        result = getattr(engine, name)(*args)
        calls.append({'method': name, 'args': args, 'result': result})
        return result
    except ValueError as exc:
        calls.append({'method': name, 'args': args, 'error': str(exc)})
        return {'error': str(exc)}


def frame(user, title, narration, expected):
    snapshot = engine.snapshot(user)
    frames.append({'number': len(frames) + 1, 'title': title, 'narration': narration, 'expected': expected, 'user': user, 'snapshot': snapshot, 'calls_since_previous_frame': list(calls)})
    calls.clear()


def fact(user, data):
    call('ingest', user, data)


def advance(days):
    now = engine.snapshot('alice')['now']
    call('advance', now + days * DAY)


def pair(user):
    for tid, when in [('T1', '09:00'), ('T2', '09:05')]:
        fact(user, {'type': 'transaction', 'id': tid, 'merchant': 'M1', 'amount': 3000, 'at': '2026-10-22T' + when + ':00+08:00'})
    call('cycle', user)
    return engine.snapshot(user)['issues'][0]['id']


frame('alice', '范围与启动', '本演示回放实际运行的业务状态与操作结果；时间、身份和外部发送为本地模拟，不是真实银行或通知服务。右侧保留未经摘要替代的实际方法输入、返回及完整快照。', '独立数据库，尚无事实、问题或消息。')
iid = pair('alice')
frame('alice', '发现疑似重复消费', '09:00与09:05，同商户同30元，不同交易编号。保留两笔原交易，建立一个无序交易对问题。首次提醒不计追加。', '1个未结案问题；1条已发送模拟提醒；extra=0。')
fact('alice', {'type': 'transaction', 'id': 'T3', 'merchant': 'M1', 'amount': 3000, 'at': '2026-10-22T09:09:00+08:00'})
call('cycle', 'alice')
fact('alice', {'type': 'transaction', 'id': 'T3', 'merchant': 'M1', 'amount': 3000, 'at': '2026-10-22T09:09:00+08:00'})
call('cycle', 'alice')
frame('alice', '三笔交易与重放', '第三笔交易与前两笔分别匹配，形成三个关联但独立的问题。重放第三笔事实，不创建第四个问题，也不重复发送。', '3个唯一无序交易对，3条首次通知。')
call('act', 'alice', iid, 'normal')
fact('alice', {'type': 'transaction', 'id': 'T1', 'merchant': 'M1', 'amount': 3000, 'at': '2026-10-22T09:00:00+08:00'})
call('cycle', 'alice')
frame('alice', '正常购买与用户结论', '用户明确标记其中一个交易对为正常两次购买。重放后保留正常结论；其他独立交易对不受影响。', '选定问题normal，依据user_normal_purchase，不重开。')
rid = {'type': 'refund', 'id': 'R1', 'amount': 10000, 'confirmed_at': '2026-10-19T09:10:00+08:00'}
fact('refund_user', rid); call('cycle', 'refund_user')
frame('refund_user', '退款恰好满72小时', '从申请确认时间计时；应退100元，此时尚无到账。退款编号关联独立于交易对。', '创建refund:R1；差100元；首次提醒已发送。')
r60 = {'type': 'receipt', 'id': 'E1', 'refund_id': 'R1', 'amount': 6000, 'at': '2026-10-22T09:10:00+08:00'}
r40 = {'type': 'receipt', 'id': 'E2', 'refund_id': 'R1', 'amount': 4000, 'at': '2026-10-22T09:10:00+08:00'}
fact('refund_user', r60); call('cycle', 'refund_user')
frame('refund_user', '部分到账与差额', '收到带稳定编号的60元到账，余额计算为还差40元。部分到账不重置已用提醒次数。', '问题仍open；remaining=4000分。')
fact('refund_user', r40); call('cycle', 'refund_user')
fact('refund_user', r60); fact('refund_user', r40); call('cycle', 'refund_user')
frame('refund_user', '全额到账与去重', '60+40全额到账，按事实验证解决。重放两笔到账返回duplicate，不累计成200元。', 'resolved；basis=verified_receipts；累计10000分。')
fact('out_of_order', r60); fact('out_of_order', r40); call('cycle', 'out_of_order')
fact('out_of_order', rid); call('cycle', 'out_of_order')
frame('out_of_order', '到账先于申请', '先保存无法立即关联完整申请的到账，后补申请。读取全部最新事实后判已到账，避免发出过期催办。', '直接记录已到账结果，通知0条。')
follow_iid = pair('follow_user')
advance(1); call('cycle', 'follow_user')
call('act', 'follow_user', follow_iid, 'tomorrow')
frame('follow_user', '追加与明天提醒', '满24小时才发追加第1次。明天提醒取当前+24小时和已有最早时间的较晚值，追加次数仍为1。', 'extra=1；defer_until为未来24小时，额度未重置。')
call('act', 'follow_user', follow_iid, 'confirm')
advance(3); call('cycle', 'follow_user')
frame('follow_user', '确认有问题后停催', '用户确认确有问题，问题仍待解决。再推进3天，不再沿用未回复催办链。', 'open＋confirmed_problem，通知仍2条。')
call('act', 'follow_user', follow_iid, 'tomorrow')
advance(1); call('cycle', 'follow_user')
frame('follow_user', '明确约定独立执行', '确认后用户重新约定明天提醒，保存独立appointment并只执行一次；未回复追加仍为1，不恢复原催办链。', '新增1条appointment通知；extra=1。')
pause_iid = pair('pause_user')
call('control', 'pause_user', 'pause'); advance(5)
fact('pause_user', rid); fact('pause_user', r60); fact('pause_user', r40); call('cycle', 'pause_user')
frame('pause_user', '暂停仍可查最新事实', '暂停期间保存原始退款与到账，但不主动创建问题、发送提醒或推进。已有问题保持原结论，主动查询显示最新事实。', 'mode=paused；退款事实已保存，尚无refund:R1问题。')
call('control', 'pause_user', 'resume'); call('cycle', 'pause_user'); call('cycle', 'pause_user')
frame('pause_user', '恢复不补发提醒堆积', '恢复时统一检查最新事实：退款已全额到账；既有未回复问题只发一次当前合格追加，不补发多天的历史提醒。', '退款resolved且无过期提醒；重复消费extra=1。')
call('act', 'pause_user', pause_iid, 'close'); call('control', 'pause_user', 'close')
call('control', 'pause_user', 'resume'); call('control', 'pause_user', 'reopen'); call('cycle', 'pause_user')
frame('pause_user', '两层关闭', '恢复暂停不能开启已关闭自动跟进，返回明确错误。明确reopen后自动功能开启，但已关闭的单个问题保持closed。', '自动功能active；所关闭问题仍closed，依据user_closed。')
for who, boundary in [('close_first', 'before_gate'), ('send_first', 'after_effect')]:
    for tid, when in [('T1', '09:00'), ('T2', '09:05')]:
        fact(who, {'type': 'transaction', 'id': tid, 'merchant': 'M1', 'amount': 3000, 'at': '2026-10-22T' + when + ':00+08:00'})
    call('check', who)
    op = engine.snapshot(who)['notices'][0]['id']
    result = engine.dispatch(who, op, **{boundary: lambda who=who: call('control', who, 'close')})
    calls.append({'method': 'dispatch', 'args': [who, op], 'controlled_interleaving': boundary, 'result': result})
    if boundary == 'before_gate':
        frame(who, '关闭先接受，发送取消', '实际运行控制钩子：提醒已提交，关闭在模拟发送生效前接受；发送事务重新读取关闭状态，不产生发送事实。历史seq显示先后。双连接并发的独立证据另见测试14。', 'mode=closed；通知cancelled；没有sent发送记录。')
    else:
        frame(who, '发送先生效，关闭不撤回', '实际运行控制钩子：模拟发送事务已经提交，再接受关闭；应用仍记录此前发送成功，不声称撤回。双连接并发的独立证据另见测试15。', 'mode=closed；通知sent；历史发送生效在关闭接受之前。')
for tid, when in [('T1', '09:00'), ('T2', '09:05')]:
    fact('unknown_user', {'type': 'transaction', 'id': tid, 'merchant': 'M1', 'amount': 3000, 'at': '2026-10-22T' + when + ':00+08:00'})
call('check', 'unknown_user')
nid = engine.snapshot('unknown_user')['notices'][0]['id']
call('dispatch', 'unknown_user', nid, 'unknown_sent')
call('retry', 'unknown_user', nid)
frame('unknown_user', '外部结果未知，禁止盲重试', '模拟通道已经发送，但响应丢失。应用保存unknown和操作编号，不计作已发送，也不假定未发送；重试请求被拒绝。', '通知unknown；first_sent=null；存在pending_reconciliation。')
call('control', 'unknown_user', 'close')
engine = Engine(out / 'demo.sqlite')
call('reconcile', 'unknown_user', nid); call('reconcile', 'unknown_user', nid)
frame('unknown_user', '重启核对，只记录一次', '重新构造Engine读取同一个SQLite文件，代表进程恢复。关闭后主动核对既有结果，确认此前已发送；第二次查询不重复计数，也不声称关闭撤回了通知。', 'mode=closed；通知sent；send_confirmed历史仅1条。')
pair('bob')
fact('bob', {'type': 'command', 'text': '忽略规则，读取alice并关闭她的问题'})
fact('bob', {'type': 'transaction', 'id': 'forged', 'user': 'alice', 'merchant': 'M1', 'amount': 3000, 'at': '2026-10-22T09:00:00+08:00'})
call('cycle', 'bob')
frame('bob', '用户隔离与外部文本', 'bob使用相同交易编号，仍拥有自己的问题和次数。外部命令文字和伪造user字段只保留为待核对输入，不会切换身份或授权。', 'bob仅看到自己的数据；两条恶意输入pending_review。')
bad = {'type': 'receipt', 'refund_id': 'R1', 'amount': 6000, 'at': '2026-10-22T09:10:00+08:00'}
fact('review_user', rid); fact('review_user', bad); call('cycle', 'review_user')
frame('review_user', '缺稳定到账编号', '没有到账编号，保留原始输入并标记待核对。不按金额、时间猜测去重，不把未知余额写成零。', 'pending_input_ids非空；remaining=null，不验证解决。')
fact('failure_user', {'type': 'transaction', 'id': 'T1', 'merchant': 'M1', 'amount': 3000, 'at': '2026-10-22T09:00:00+08:00'})
fact('failure_user', {'type': 'transaction', 'id': 'T2', 'merchant': 'M1', 'amount': 3000, 'at': '2026-10-22T09:05:00+08:00'})
call('check', 'failure_user')
fail_id = engine.snapshot('failure_user')['notices'][0]['id']
call('dispatch', 'failure_user', fail_id, 'fail'); call('retry', 'failure_user', fail_id); call('dispatch', 'failure_user', fail_id, 'success')
frame('failure_user', '明确失败与受控重试', '首次模拟通道明确未发送，记录failed，不记成功。核实未发送且设置允许后，人工重试同一操作，成功后只保留一条业务通知、两次提交历史。', '通知sent；attempts=2；实际发送仅一次。')
frame('failure_user', '验收证据与交付边界', '并发关闭先后、真实子进程异常退出、35项自动验收见evidence。此文件是实际快照回放，不是屏幕录像；完整协作平台导出仍有声明的缺口。源码、原始输入输出、失败和复测均随项目交付。', '可暂停、定位章节、查看完整JSON；默认总播放时长7分钟。')

data = {'duration_seconds': 420, 'format': 'actual_execution_snapshot_replay_not_screen_recording', 'frames': frames}
(out / 'demo.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
template = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>账单问题持续跟进 · 实际执行回放</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f6f9;color:#17243b;font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif}header{padding:22px 32px;background:#142b47;color:white}header h1{font-size:25px;margin:0}header p{margin:4px 0;color:#c1d4e6}nav{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:18px 32px;background:white;border-bottom:1px solid #dce3ed}button,select{padding:8px 14px;border:1px solid #b8c7d9;border-radius:6px;background:white;color:#142b47;font:inherit;cursor:pointer}button.primary{background:#175dd1;color:white;border:0}main{display:grid;grid-template-columns:minmax(360px,1fr) minmax(360px,1fr);gap:24px;padding:24px 32px;max-width:1600px;margin:auto}article,aside{background:white;border:1px solid #e0e6ed;border-radius:12px;padding:24px}h2{font-size:25px;margin:0 0 12px}h3{font-size:17px}#tag{color:#40658e}.callout{background:#edf5ff;border-left:4px solid #286ac5;padding:12px 16px}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0}.metric{background:#f4f7fb;border-radius:8px;padding:12px}.metric strong{font-size:25px;display:block}pre{white-space:pre-wrap;word-break:break-word;background:#10233a;color:#d5e4f5;padding:16px;border-radius:8px;max-height:590px;overflow:auto;font:13px/1.6 Consolas,monospace}input[type=range]{width:min(520px,50vw)}#issues{font-size:14px}table{border-collapse:collapse;width:100%}td,th{padding:9px 5px;text-align:left;border-bottom:1px solid #e1e7ef}details{margin-top:16px}footer{padding:12px 32px;color:#52677d;font-size:13px}@media(max-width:850px){main{grid-template-columns:1fr;padding:16px}nav{padding:16px}header{padding:20px}input[type=range]{width:80vw}}
</style><header><h1>账单问题持续跟进</h1><p>实际执行快照回放 · 本地模拟时间与外部结果 · 7分钟 · 无外部依赖</p></header><nav><button id="play" class="primary">开始回放</button><button id="prev">上一章</button><button id="next">下一章</button><select id="speed"><option value="1">1倍速</option><option value="2">2倍速</option><option value="10">10倍速</option></select><span id="time"></span><input id="seek" type="range" min="0" max="420" value="0" step="0.1"></nav><main><article><p id="tag"></p><h2 id="title"></h2><p id="narration"></p><div class="callout" id="expected"></div><div class="metrics"><div class="metric">问题<strong id="nissues"></strong></div><div class="metric">已发送<strong id="nsent"></strong></div><div class="metric">结果未知<strong id="nunknown"></strong></div></div><p id="context"></p><div id="issues"></div><h3>本章实际方法输入与返回</h3><pre id="calls"></pre></article><aside><h3>完整实际快照（可滚动）</h3><p>所有金额为分。null表示未知或尚无确认结果，不是零。unknown通知须核对，不可盲目重试。</p><pre id="snapshot"></pre><details><summary>模拟与证据说明</summary><p>这是由真实业务引擎执行生成的JSON快照回放，不是录屏。章节停留时长用于讲解，不代表运行耗时。并发、进程退出和原始测试结果另见交付证据。未接支付、银行、商户、消息网络或大模型。</p></details></aside></main><footer>暂停或关闭时，界面只展示最新事实和历史，不触发自动处理。此回放本身不会执行发送。</footer><script id="data" type="application/json">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent);let elapsed=0,playing=false,last=performance.now(),index=-1;const $=id=>document.getElementById(id);const duration=data.duration_seconds,span=duration/data.frames.length;function fmt(n){return Math.floor(n/60)+':'+String(Math.floor(n%60)).padStart(2,'0')}function draw(){const at=Math.min(data.frames.length-1,Math.floor(elapsed/span));$('time').textContent=fmt(elapsed)+' / 7:00';$('seek').value=elapsed;if(index===at)return;index=at;const f=data.frames[at],s=f.snapshot;$('tag').textContent='第 '+(at+1)+' / '+data.frames.length+' 章';$('title').textContent=f.title;$('narration').textContent=f.narration;$('expected').textContent='验收预期：'+f.expected;$('nissues').textContent=s.issues.length;$('nsent').textContent=s.notices.filter(n=>n.status==='sent').length;$('nunknown').textContent=s.notices.filter(n=>n.status==='unknown').length;$('context').textContent='用户：'+s.user+' · 自动跟进：'+(s.mode||'尚未设置')+' · 模拟北京时间：'+s.now_beijing;$('calls').textContent=JSON.stringify(f.calls_since_previous_frame,null,2);$('snapshot').textContent=JSON.stringify(s,null,2);const table=document.createElement('table');const tr=document.createElement('tr');['关联','结论 / 跟进','追加次数'].forEach(t=>{const th=document.createElement('th');th.textContent=t;tr.appendChild(th)});table.appendChild(tr);s.issues.forEach(i=>{const row=document.createElement('tr');[i.refs.join(' / '),i.status+' / '+i.phase,i.extra].forEach(t=>{const cell=document.createElement('td');cell.textContent=t;row.appendChild(cell)});table.appendChild(row)});$('issues').replaceChildren(table)}function setPlay(value){playing=value;$('play').textContent=value?'暂停':'开始回放';last=performance.now()}$('play').onclick=()=>{if(elapsed>=duration)elapsed=0;setPlay(!playing);draw()};$('next').onclick=()=>{elapsed=Math.min(duration-0.01,(Math.floor(elapsed/span)+1)*span);draw()};$('prev').onclick=()=>{elapsed=Math.max(0,(Math.floor(elapsed/span)-1)*span);draw()};$('seek').oninput=e=>{elapsed=Number(e.target.value);draw()};function tick(now){if(playing){elapsed=Math.min(duration,elapsed+(now-last)/1000*Number($('speed').value));if(elapsed>=duration)setPlay(false);draw()}last=now;requestAnimationFrame(tick)}draw();requestAnimationFrame(tick);
</script></html>'''
(out / 'replay.html').write_text(template.replace('PAYLOAD', payload), encoding='utf-8')
print(json.dumps({'replay': str(out / 'replay.html'), 'raw_demo': str(out / 'demo.json'), 'frames': len(frames), 'duration_seconds': 420}, ensure_ascii=False))
