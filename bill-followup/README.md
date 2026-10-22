# 发现账单问题后继续跟进

可运行的本地实现，只检查疑似重复消费与退款逾期。Python标准库＋SQLite，无需安装第三方依赖、联网、付费资源或大模型。所有金额输入为整数分，时刻默认北京时间。不会真实扣款、退款、联系商户或发送网络消息。

## 从零运行

要求：Python 3.10以上（实际验证版本见evidence中的环境证据）。解压后在本目录打开终端。没有Python的环境需要先自行安装Python；交付包不包含解释器。

```powershell
python --version
python -m followup --db data/first.sqlite --user alice init
python -m followup --db data/first.sqlite --user alice ingest fixtures/duplicate.json
python -m followup --db data/first.sqlite --user alice show
```

首次运行生成一个疑似问题及一条模拟首次提醒。`init`拒绝覆盖已初始化数据库；要独立演示请换数据库文件名，不清空原库。

一键实际执行退款核心案例（每次新建独立数据库，保存每次CLI进程的完整参数、stdout、stderr、退出码）：

```powershell
python tools/stage_one.py
```

一键验收（每次独立初始化、保留所有历史运行，包括失败）：

```powershell
python tools/run_acceptance.py
```

输出本次证据目录，其中`REPORT.md`列出输入预期、实际PASS/FAIL及每个证据位置；`results.json`是结构化测试结果；`stdout.txt`、`stderr.txt`是子进程原始输出；各场景`evidence.json`包含输入、步骤快照、最终事实/状态/提醒/历史；`state.sqlite`保留场景数据库。`invocation.json`保存调用参数、退出码与当前源码SHA256。

最终补充的真实时钟端到端验证单独运行，不重跑以上35项：

```powershell
python tests/realtime_e2e.py
```

它通过正式接口在独立真实时钟库中建立问题、完成首次提醒、确认有问题，然后安排8秒后到期的明确约定；没有缩短24小时/72小时规则。独立进程运行默认1秒轮询的`run`入口，安排完成后测试端只读观察，到期前不发送、到期后自动发送、继续等待至少3.2秒不重复；超时25秒并有界清理进程。每次生成独立`evidence/realtime-e2e-*`，保留启动命令/时刻、原始进程输出、只读观察序列、发送记录、最终数据库和断言报告。

## 输入与操作

所有全局参数放在子命令前。`--user`由本地操作者模拟可信身份，不从外部事实文字中获取身份。`show`中复制所需问题的`id`或通知的`id`。问题ID为稳定不含空格的字符串。

```powershell
python -m followup --db data/first.sqlite --user alice advance 2026-10-23T09:10:00+08:00
python -m followup --db data/first.sqlite --user alice act <问题ID> tomorrow
python -m followup --db data/first.sqlite --user alice act <问题ID> confirm
python -m followup --db data/first.sqlite --user alice act <问题ID> schedule --at 2026-10-25T10:00:00+08:00
python -m followup --db data/first.sqlite --user alice act <问题ID> resolved
```

`<问题ID>`为需替换的说明，不应把尖括号原样输入终端。支持动作：`normal`正常两次购买、`confirm`确有问题、`tomorrow`明天提醒、`schedule`明确约定、`resolved`用户确认已解决、`close`关闭此问题。日期缺少时刻返回`clarification_required`，需要再次提供完整时刻，不猜测几点。

```powershell
python -m followup --db data/first.sqlite --user alice control pause
python -m followup --db data/first.sqlite --user alice control resume
python -m followup --db data/first.sqlite --user alice control close
python -m followup --db data/first.sqlite --user alice control reopen
```

`control close`表示关闭自动跟进；`act ... close`表示关闭此问题。恢复暂停不能重新开启已关闭功能；重新开启功能不重开问题。

`ingest`接收单个JSON对象或JSON数组，数组作为一次输入批次，先保存全部事实，再检查，避免同批已到账仍发逾期通知。事件示例：

```json
[
  {"type":"refund","id":"R1","amount":10000,"confirmed_at":"2026-10-19T09:10:00+08:00"},
  {"type":"receipt","id":"E1","refund_id":"R1","amount":6000,"at":"2026-10-22T09:15:00+08:00"}
]
```

交易示例见`fixtures/duplicate.json`。退款申请允许资料尚未齐全，后续同编号可补齐缺失值；已经确定的值变化会进入冲突核对。到账缺稳定编号、同编号内容冲突均保留原始输入，不按金额和时间猜测去重，也不静默覆盖。

## 持续运行与模拟时间

`ingest`和`advance`在事件到达或模拟时间推进后立即触发检查，不需再次聊天。持续运行入口会轮询最新事实与到期时间：

```powershell
python -m followup --db data/first.sqlite run
```

另一个终端可输入事件、推进模拟时钟、暂停或关闭；Ctrl+C停止进程，数据库保留。停进程与关闭自动跟进不是同一个动作，题面中的关闭需用`control close`。

要使用真实时间轮询，另建数据库：

```powershell
python -m followup --db data/realtime.sqlite init --mode real
python -m followup --db data/realtime.sqlite run
```

真实模式读取系统时间，不允许`advance`。模拟时钟属于演示环境而非用户设置，持久化且不能倒退。一次跨多天推进或恢复只发送当前一次合格提醒，下一次从实际发送时间计24小时，不突发补历史消息。

## 结果未知、失败与核对

正常`ingest`默认模拟发送成功；演示失败时先`plan`只生成队列，再指定结果：

```powershell
python -m followup --db data/first.sqlite --user alice plan
python -m followup --db data/first.sqlite --user alice dispatch <通知ID> --behavior unknown_sent
python -m followup --db data/first.sqlite --user alice show
python -m followup --db data/first.sqlite --user alice reconcile <通知ID>
```

模拟结果：`success`成功、`fail`明确未发送、`unknown_sent`已发送但响应丢失、`unknown_pending`核对仍未知。应用unknown不计为sent；它阻止该问题后续发送，不盲目重试。`reconcile`只查询，不提交发送，可在关闭后由用户主动执行；没有自动核对轮询。

准确边界：`reconcile <通知ID>`没有指定结果的参数。它按当前用户和操作ID读取本地模拟通道`provider`表中已经持久化的`state/sent_at`，据此更新应用通知、计数与核对历史；不改写通道结果、不提交发送。发送时的`--behavior`是模拟故障/结果夹具，会在`dispatch`阶段写通道结果；`settle-not-sent`则是独立的模拟器操作，人工将pending核实为not_sent。两者不能描述为真实外部查询，或描述成`reconcile`参数直接指定成功。

`unknown_pending`可一直保持未知；模拟器通过`settle-not-sent <通知ID>`明确核实未发送，再执行`reconcile`才变为failed。仅failed且通道确认not_sent、当前规则仍允许时，`retry <通知ID>`才重新入队，随后`dispatch`。重试沿用操作ID，不增加业务提醒数量；本次可重新选择模拟结果。

## 演示与证据

```powershell
python tools/build_demo.py
```

打开输出目录中的`replay.html`。自包含、离线、22章节，默认7分钟，可暂停、拖动、加速。它是实际业务引擎调用与数据库快照的可回放讲解，**不是录屏**；停留时长是讲解时间，不代表执行耗时。`demo.json`保存对应方法输入、返回和完整状态。并发先后与真实进程异常退出的证明以自动测试证据为准。

设计和已确认实现假设见`DESIGN.md`；测试、失败修复与缺口见`TESTING.md`；复用和贡献见`CONTRIBUTIONS.md`；可见协作原始记录导出范围见`COLLABORATION.md`。交付总索引由`tools/package_delivery.py`生成。

## 已知范围

没有真实登录认证、银行/支付/通知接口、自然语言理解、网页业务界面、自动安装服务或生产部署。操作者可通过CLI选择任意模拟用户，不能据此声称已实现对恶意本机操作者的安全隔离。模拟服务的发送与关闭事务边界只在本地模拟通道中成立，不能直接推广为真实网络通道保证。缺编号/冲突到账保留待人工核对，尚无事实人工裁决界面。所有数据均为合成示例。

最终本人验收材料见PERSONAL_ACCEPTANCE.md：包含用户在新解压目录执行的35项验收、真实时钟端到端、手工重复消费/退款重放、回放交互及编码问题。此前Codex执行历史单独保留；六道参考回答不作为独立理解核查证明。
