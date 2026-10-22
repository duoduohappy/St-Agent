# 账单问题持续跟进（St-Agent）

Python 标准库 + SQLite 的本地模拟实现，采用确定性规则、持久状态与后台调度；未接入大模型、真实银行或通知服务。

## 查看与下载

- [完整最终提交包（6,396,231 字节）](submission/bill-followup-final-20261022T093409806022Z.zip)：点击文件页的 **Download raw file** 下载，或使用 [直接下载链接](https://github.com/duoduohappy/St-Agent/raw/refs/heads/main/submission/bill-followup-final-20261022T093409806022Z.zip)。
- [交付索引](bill-followup/DELIVERY.md)
- [启动与命令说明](bill-followup/README.md)
- [设计与实现假设](bill-followup/DESIGN.md)
- [测试报告](bill-followup/TESTING.md)
- [用户实际执行验收与编码说明](bill-followup/PERSONAL_ACCEPTANCE.md)
- [贡献与验证归属](bill-followup/CONTRIBUTIONS.md)
- [协作记录范围及截止位置](bill-followup/COLLABORATION.md)

下载并解压提交包后，打开 `bill-followup/evidence/demo-20261022T075802548394Z/replay.html`，即可离线播放七分钟实际执行快照回放。GitHub 文件页只显示 HTML 源码。回放不重新执行程序或发送提醒。

## 运行

需要 Python 3.10+，无需安装第三方依赖。具体初始化、示例和验收命令以项目 README 为准。在项目目录中先查看命令帮助：

```powershell
cd bill-followup
python -m followup --help
```

## 验证与归属

用户已亲自执行重复消费、退款100元依次到账60元和40元及事件重放、35项验收和独立进程真实时钟端到端测试；输出与证据按原样保留。回放暂停、章节切换、进度拖动由用户明确报告通过。编码、测试编写、此前 Codex 执行的验证及整理工作与用户贡献分开登记；六道参考回答不作为独立理解核查证明。本次上传未重跑业务测试、未修改业务源码。

## 归档范围

`bill-followup/` 从已校验的最终提交包逐字节解压，原提交包保持不变。包内文档中“未上传 GitHub”等表述描述封存时的状态；此次按用户后续授权将材料上传至本仓库。

协作原始记录的完整性限定于文档所声明的本地来源、可见范围与截止点：**2026-10-22 17:34:06.334（北京时间）**。截止后的封存、核验及本次 GitHub 上传过程不在该原始记录内，不为纳入最后回复循环重新打包。

原提交包 SHA256：

```text
a5c84b41258cfbd8c0df98bb1ce9810a960836a22babe8406ae5d1f7eee2b32c
```
