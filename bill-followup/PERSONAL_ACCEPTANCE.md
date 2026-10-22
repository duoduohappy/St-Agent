# 本人本轮实际验收与编码问题

执行者：用户本人。Codex仅事后只读核查、按原字节收集副本和整理说明，没有代替用户执行本轮验证。

证据总索引：[collection-manifest.json](evidence/personal-review-20261022-164553-252/collection-manifest.json)。104个来源文件均已核对副本与来源字节相同，记录来源、目标、大小、SHA256；未覆盖原件。本地路径和系统账号名为运行元数据，业务记录均为合成数据。

## 实际结果与证据

| 本人执行项目 | 实际结果 | 证据 |
|---|---|---|
| 重复消费 | 两笔交易、一个open疑似问题、一次首次提醒、extra=0 | [数据库内容](evidence/personal-review-20261022-164553-252/manual-cases/database-contents.json)、[原库副本](evidence/personal-review-20261022-164553-252/manual-cases/review.sqlite)及用户报告 |
| 退款部分到账 | 累计6000分、差4000分、open、extra=0、无结案依据 | [本人截图](evidence/personal-review-20261022-164553-252/screenshots/refund-partial.png) |
| 全额到账与重放 | 累计10000分、差额0、resolved、verified_receipts、提醒仍1条；重放duplicate | [本人截图](evidence/personal-review-20261022-164553-252/screenshots/refund-full-and-replay.png)、[原库副本](evidence/personal-review-20261022-164553-252/manual-cases/refund-review.sqlite) |
| 35项验收 | tests_run=35、successful=true、退出码0 | [逐项报告](evidence/personal-review-20261022-164553-252/acceptance-20261022T084553401827Z/REPORT.md)、[结果](evidence/personal-review-20261022-164553-252/acceptance-20261022T084553401827Z/results.json)、[原始stderr](evidence/personal-review-20261022-164553-252/acceptance-20261022T084553401827Z/stderr.txt) |
| 真实时钟后台到期 | PASS、生产源码未改、退出码0 | [报告入口](evidence/personal-review-20261022-164553-252/realtime-e2e-20261022T084559992884Z/REPORT.md)、[完整报告](evidence/personal-review-20261022-164553-252/realtime-e2e-20261022T084559992884Z/report.json)；同目录含命令、时间、进程输出、发送记录、最终数据库 |
| 两项退出码 | 均为0 | [原始汇总（UTF-16）](evidence/personal-review-20261022-164553-252/personal-acceptance-20261022-164553-252/execution-summary.json)、[本人截图](evidence/personal-review-20261022-164553-252/screenshots/personal-exit-codes.png) |
| 回放交互 | 用户明确报告暂停、章节切换、进度拖动均通过 | [末章](evidence/personal-review-20261022-164553-252/screenshots/replay-last-chapter.png)、[控件](evidence/personal-review-20261022-164553-252/screenshots/replay-control.png)、[定位](evidence/personal-review-20261022-164553-252/screenshots/replay-seek.png)及协作原始消息 |

## 编码问题

1. 外层Tee-Object的suite-output.txt、realtime-output.txt以UTF-16保存，但其中中文写入前已误解码。更换读取编码不能完整恢复，乱码原件保留，不声称它们中文正常。
2. 程序直写results.json、REPORT.md、stderr.txt和真实时钟report.json是正常UTF-8；35项中文预期与源码逐项相同，45份JSON/JSONL可正常读取。没有因显示问题重跑业务测试或修改业务逻辑。
3. 当前表现符合UTF-8进程输出在PowerShell转接时误解码后保存；没有用户当时会话编码设置的完整快照，不将具体代码页推测当成已证实原因。
4. 用户按指导设置当前会话编码，明确报告中文正常。正常证据与乱码副本同时保留，不以重新生成文本冒充原始输出。

详情：[编码检查及哈希](evidence/personal-review-20261022-164553-252/encoding-findings.json)。在项目根目录正确查看：

```powershell
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
Get-Content -LiteralPath '.\evidence\personal-review-20261022-164553-252\acceptance-20261022T084553401827Z\REPORT.md' -Encoding UTF8
```

## 归属与限制

根目录原有acceptance-*、realtime-e2e-*是此前Codex执行历史，不挪作用户证据；本目录收集用户新运行。六道参考回答不作为独立理解核查或独立编码能力证明。

手工案例和界面操作没有完整终端录屏；依据是用户报告、截图、输入文件及数据库结果，不编造未保存的输出。原库直接只读打开曾返回unable to open database file，原因未证实；后续按字节复制到工作区并读取副本成功，来源与副本哈希相同，源库未修改。

本人真实时钟目录中原始realtime.sqlite的配套WAL/SHM也按字节保留，属于相关取证材料；推荐查看该目录内一致性备份final-state.sqlite和final-database-state.json，避免数据库工具打开后改变原始现场副本。
