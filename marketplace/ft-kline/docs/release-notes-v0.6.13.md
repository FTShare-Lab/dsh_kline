# v0.6.13 · 官网连接入口与渠道归因

- 图表顶部直接访问 FtShare；欢迎页和连接页提供注册／登录、官网及获取 Key 的简洁操作路径，窄窗口下保持顶部控件同排。
- 市场页数据来源合并为一处，相同供应商去重；底部 FtShare 名称可点击进入官网。
- 官网链接统一携带 `dsh_kline` UTM，按宿主和入口区分；README 安装、npm 与 Release 链接接入独立渠道入口。
- 独立统计后台完成一次点击去重、旧标签兼容和多产品隔离。访问、点击、复制、直接入口跳转与 npm 下载量分别解释，不作为独立安装人数。

本版继续使用 API Key，不接入 OAuth，不增加插件安装上报。保留既有绘图功能、识别条件及 README 演示截图。

详见[UTM 说明](utm-attribution.md)与[发布验收](release-acceptance-v0.6.13.md)。GitHub 附件提供 DSH TGZ、Codex ZIP 及各自 SHA-256。
