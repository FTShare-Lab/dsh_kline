# 一个项目，两个宿主

双宿主版本从 v0.4.0 开始发布：DSH 与 Codex 共用行情和分析运行时，但各自使用独立的宿主适配器与发行包。
行情 provider、核心指标、应用服务、`view/kline.html` 和 KLineCharts 都只有一份。

| 宿主 | 安装产物 | 入口 | 图表承载 |
| --- | --- | --- | --- |
| DeepSeek Harness | `release/dsh-kline.tgz` | `scripts/run-dsh-kline.mjs` | 原生 chart service / sidebar |
| Codex | `release/dsh-kline-codex.tgz` | `scripts/run-codex-kline.mjs` | 通用 MCP Apps resource |

安装到哪个宿主，就由该宿主的清单选择入口，不通过进程名猜测宿主。
DSH 入口明确选 `dsh`，Codex 入口明确选 `codex`；互相不受继承环境变量干扰。
直接启动 `server.py` 的高级用户可设 `DSH_KLINE_ADAPTER=dsh|codex`，默认兼容 DSH。

## 构建与插件目录

需要 Node >=22.19.0、Python >=3.10。

```bash
pnpm build:sidebar
pnpm pack:release
pnpm pack:codex
```

两个包使用严格独立的文件白名单。Codex 包解压后是一个完整的 `dsh-kline/` 插件目录，
包含可移植的 `plugin.json`、`mcp.json` 以及 Codex 兼容 fallback
`.codex-plugin/plugin.json`、`.mcp.json`、运行时、数据目录和图表资源。
不需要旁边存在源代码仓库，也不需要访问开发者的服务器。
DSH npm 包仅包含 DSH 所需的 `package.json` / `cordis.patch.yml`、侧栏和 chart service；
它不携带 Codex 清单、MCP Apps bridge 或 Codex 文档。

`plugins/dsh-kline/` 是插件清单和品牌资源的**构建模板**，不是完整安装目录；
不要只把这个小目录安装到 Codex。应解压 `release/dsh-kline-codex.tgz`，再把得到的
完整目录作为本地插件 marketplace 的 source。未自动创建 marketplace、安装插件，
也未修改任何真实 Codex 配置。正式安装还需在用户自己的 Codex 中验收。

可移植 `mcp.json` 使用 `${PLUGIN_ROOT}` 定位 Node 启动器；兼容 fallback
`.mcp.json` 保留 `${CLAUDE_PLUGIN_ROOT}`。两者都不依赖终端当前目录、用户名或 SSH 别名。
Node/Python 必须能被桌面宿主找到；
第一次启动会在用户缓存目录安装独立 Python 环境。

如果桌面宿主已提供 Python 3.10+ 与全部依赖，可显式设置
`DSH_KLINE_RUNTIME_MODE=external` 和 `DSH_KLINE_PYTHON`。该模式适用于
DSH 与 Codex：只校验并启动指定解释器，绝不创建 venv、安装依赖或回退到其他
Python；未设置时保持默认 `auto` 模式。Codex external 模式仍使用 Codex adapter，
不会创建 DSH locator 或启动 chart service。

## 不安装插件时，直接注册 MCP

下面命令由用户在运行 Codex 的机器上执行，会修改该机器的 MCP 配置：

```bash
codex mcp add dsh-kline -- node /absolute/path/to/dsh_kline/scripts/run-codex-kline.mjs
```

Mac 使用远程服务器是另一种**可选部署**，不写入通用插件默认配置：

```bash
codex mcp add dsh-kline -- ssh -T YOUR_SSH_ALIAS \
  'cd /absolute/server/path/dsh_kline && exec node scripts/run-codex-kline.mjs'
```

切换到插件安装时先处理原手动注册项，避免同一套工具注册两遍。
更改后新开任务或重启 Codex，以刷新 MCP 进程和缓存的 UI resource。

## MCP 合同与交互

原有 14 个模型可见工具的名称和输入 schema 与上游相同。
DSH `tools/list` 共 14 个；Codex 额外注册 `chart_action`，其 `_meta.ui.visibility`
为 `["app"]`，仅供图表前端调用，因此协议层列表共 15 个、模型工具仍是 14 个。
该元数据是宿主可见性约定，不是服务器端授权机制；action 白名单由服务器另行校验。

内部 action 复用 DSH 的搜索、自选、市场数据、区间统计、关键点位等操作，
不访问 DSH HTTP route，也不导入 `chart_service.py`。

Codex 图表 resource：`ui://dsh-kline/kline`，MIME `text/html;profile=mcp-app`。
HTML 内联共享图表资源；侧边栏图标和消息桥只在 adapter 渲染时注入，
原版 `view/kline.html` 保持上游字节一致。展示模式由宿主决定；不支持展开的宿主
会看到禁用按钮及提示，普通 stdio 客户端仍可消费结构化结果。

Codex 返回 `chart_ready=false`、`chart_session=null`、
`chart_service.error=chart_service_disabled` 是预期行为；
`chart_ui.ready=true` 表示 MCP App payload 已就绪，不代表已人工确认桌面展示成功。

## 本地验收

```bash
python3 -m pytest -q
node --test tests/*.test.ts tests/*.test.mjs
pnpm build:sidebar
pnpm pack:release
pnpm pack:codex
node scripts/smoke-packed-install.mjs release/dsh-kline.tgz
node scripts/smoke-dsh-profile.mjs release/dsh-kline.tgz
python3 scripts/smoke-codex-plugin.py release/dsh-kline-codex.tgz
# Linux 有 Chrome 时可运行真实浏览器 + 模拟 MCP Apps 宿主验收：
node scripts/smoke-mcp-app-browser.mjs
```

测试使用隔离缓存/凭据目录。迁移后保留上游 DSH 回归，另外验证 14 工具 schema、
App-only 操作、握手/图标状态、图表参数一致性、Codex 不启动 HTTP 服务，
以及解压插件搬到含空格/中文路径后能独立启动。
