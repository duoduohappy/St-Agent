# 交付索引

仅包含独立bill-followup项目；未向外部发送。

- [启动与操作说明](README.md)
- [设计与用户确认的实现假设](DESIGN.md)
- [测试、失败修复与缺口](TESTING.md)
- [复用与贡献](CONTRIBUTIONS.md)
- [原始协作记录与导出缺口](COLLABORATION.md)

- 最新实际验收：35项，successful=True；[报告](evidence/acceptance-20261022T075854313605Z/REPORT.md)、[原始stderr](evidence/acceptance-20261022T075854313605Z/stderr.txt)
- [7分钟实际执行快照回放](evidence/demo-20261022T075802548394Z/replay.html)
- [真实CLI核心案例结果](evidence/stage-one-20261022T074433064001Z/summary.json)
- [最新可见协作原始记录索引和缺口](evidence/collaboration/20261022T081314227813Z-manifest.json)
- [本机无pip新虚拟环境启动与完整验收](evidence/clean-20261022T075355890355Z/clean-report.json)
- 独立补充真实时钟后台约定端到端：PASS；[报告](evidence/realtime-e2e-20261022T081045850285Z/REPORT.md)、[完整证据](evidence/realtime-e2e-20261022T081045850285Z/report.json)。本轮只执行这一项，未重跑原35项或干净环境；生产代码未改。

历史失败结果均保留，不能以最新成功覆盖；证据文件中的绝对路径为执行时现场路径，解压后按相对目录查找。

压缩包排除解释器虚拟环境、重复的干净环境源码副本、缓存、运行中数据和交付包自身；保留干净环境原始命令输出与结果。协作记录截至最近导出快照，当前打包调用和最后回复可能不在其中，不声称完整平台导出。
