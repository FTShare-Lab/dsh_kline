# v0.6.0 · FT K-Line Codex 私有灰度

本版新增独立的 Codex 插件 `ft-kline`，但不改变 DSH 的安装方式或既有功能。

- ChatGPT Desktop：支持完整 K 线图、现有受控图形、指标对象、候选确认、手动工作台与自然语言创建/续改/删除。所有绘图都遵循 `get_chart_context → prepare_chart_edit → apply_chart_edit → get_chart_edit_status`。
- Codex CLI：保留行情、分析和 TA-Lib 的无界面结构化结果；**CLI 不支持交互图表**。
- 安全性：Codex 图表、函数结果和临时 FTShare Key 只存在当前连接的内存中；资源关闭、连接结束或 30 分钟空闲后清除。环境变量 Key 优先，App Key 不落盘且不回显。
- 回执含义：`applied` 表示服务端图表状态已提交；`ui_receipt=rendered` 是 UI 回执；`pixel_verified` 仍始终为 false，除非外部人工验收另行记录。

正式资产为 `dsh-kline-v0.6.0.tgz`、`ft-kline-v0.6.0.zip` 及各自 SHA-256。当前仅私有 marketplace 灰度；不含公共目录提交材料、公开隐私/支持/条款链接或对外发布授权。
