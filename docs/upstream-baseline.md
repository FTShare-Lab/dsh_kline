# 上游基线与双宿主适配

本地开发基线是 `FTShare-Lab/dsh_kline` 的 `main`：
`8d231c1c98d8112462f1d4a6c814c441b82e5365`（v0.3.4）。

通过只读 HTTPS 获取精确提交的完整快照，逐文件核对前一基线到 v0.3.3 的变化，
同步全部新增和更新的上游内容，并保留显式双宿主适配增量。同步前的本地源码已在
未纳入版本控制的归档中备份。
原 `.git`、Python/Node 环境、运行缓存和个人配置未纳入同步覆盖范围。

`config/upstream-baseline.json` 保存 120 个上游文件的 SHA-256、14 个公开 MCP 工具
的输入 schema 哈希，以及 11 个适配文件的逐项理由。其余 108 个文件与上游逐字节
一致，包括共享 `view/kline.html`、DSH 客户端、provider、指标算法和 DSH patch。

适配后不要求所有文件与远端字节相同：server 注册、共享 UI 操作服务、启动器和
打包脚本是明确的开发增量。Codex 图标按钮、资源内联、宿主偏好与 MCP 消息桥由
adapter 在返回 HTML 时注入，不改变 DSH 的共享前端源文件。

本次同步包括 v0.3.2/v0.3.3 的 FTShare 凭据来源、安全清除规则、设置下拉项、
主题/语言跟随宿主、SDK 1.0.7，以及 v0.3.4 的外部 Python 运行时和 Windows
隔离导入修复。所有依赖约束现与上游相同。
MCP 与图表 UI 均透传 `credential_source` 和 `can_clear`；MCP Apps 从标准
host context 获取主题/语言，与图表内的手动覆盖状态分开保存。

安装和宿主选择见 [Codex 与 DSH 双宿主指南](codex-adapter.md)。

## 本地验收记录（2026-09-17）

- Node 22.19.0、Python 3.10；Python 依赖检查通过。
- Python：164 passed / 1 skipped；Node：89 passed（v0.3.4 同步前基线）。
- DSH 前端构建、基线完整性和原有 14 个公开工具 schema 校验通过。
- Chrome + 本地 MCP Apps 模拟宿主：60 根输入 K 线、30px 图标展开/收起、
  宿主主题/语言切换、手动覆盖和恢复跟随通过；无未捕获 JS 异常。
- DSH 与 Codex 两种打包在 PATH 无 Git 的条件下通过。
- 未安装到用户真实 Codex、未改 Mac 配置、未执行 Git 命令或 GitHub 上传。
- 本地模拟宿主测试不代替 Mac Codex Desktop 的最终界面验收。
