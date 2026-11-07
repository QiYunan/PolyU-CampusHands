# 05 · 演示加固

## 目标

把完整流程整理为可重复、五分钟内能完成的课程演示，并让协作检查可在全新环境执行。

## 交付范围

- 提供可重建的 Alice、Bob、Carol、David seed 和明确标注的 Demo Mode；编写五分钟演示脚本与 Windows PowerShell 启动说明。
- 完善移动端基本布局、加载/失败提示、公开时间线及 provider 状态显示。
- 建立离线 CI：后端 pytest、前端 lint/test/build；提供 Pull Request 模板和贡献说明，保护密钥与数据库文件。
- 检查完整流程的边界：拒绝、超时、重复操作、双人确认、断线重连和模型不可用。

实施以 [Demo runbook](../DEMO_RUNBOOK.md)的隔离 reset、setup/ready preflight、计时脚本和故障恢复为准。Agent UI 仅展示本地验证后交给服务执行的工具名称；Mock Recovery Mode 必须在计时前选定并明确标记，不代表真实模型结果。离线 CI 和协作命令见 [README](../../README.md)与 [CONTRIBUTING](../../CONTRIBUTING.md)。

## 完成证据

通过 [AT-13 与 AT-14](../ACCEPTANCE_TESTS.md#05-演示与协作)，并复核此前各阶段的关键场景。完整目标体验见 [产品规格](../PRODUCT_SPEC.md)。
