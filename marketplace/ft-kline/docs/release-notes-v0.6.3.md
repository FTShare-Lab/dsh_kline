# v0.6.3 · 公开 GitHub 插件源

本版统一公开 GitHub 源、插件版本、ZIP 安装包和安装文档。行情、指标、图表和绘图行为延续 v0.6.2。

- 新增项目维护的 **FTShare** GitHub 插件源，可添加一次后安装 `ft-kline@ftshare`，无需构建源码或手动下载 ZIP；尚未上架 OpenAI 官方公共插件目录。
- 提供完整独立插件目录，与 Codex ZIP 使用同一文件清单；CI 校验文件一致性，并分别测试桌面与 CLI 启动。
- 补齐插件名称、图标、开发者与说明；中英文 README 包含安装、刷新更新、固定版本 ZIP 和旧来源迁移步骤。
- 两个宿主的版本及安装包统一为 v0.6.3，保留 v0.6.2 的原始发布资产。

首次安装：

```bash
codex plugin marketplace add FTShare-Lab/dsh_kline --ref main
codex plugin add ft-kline@ftshare
```

更新已添加的源：

```bash
codex plugin marketplace upgrade ftshare
codex plugin add ft-kline@ftshare
```

重新打开 Codex 后使用。已有 `ft-kline@ftshare-local` ZIP 安装的用户，请先在插件页面停用旧来源，避免重复加载同名工具。首次启动仍需 Node.js 22.19+、Python 3.11+ 和网络；GitHub 源另需 Git。

发布资产为 `dsh-kline-v0.6.3.tgz`、`ft-kline-v0.6.3.zip` 及各自的 SHA-256 文件。DSH 安装方式保持不变。检查范围与发布门槛见 `docs/release-acceptance-v0.6.3.md`。
