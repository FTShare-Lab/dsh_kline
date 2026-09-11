# dsh_kline v0.2.7 发布前检查报告

检查日期：2026-09-11
被检版本：`0.2.7`（工作区未提交状态；`HEAD` 仍为 `v0.2.6`）
检查环境：macOS（arm64）、Node `v26.7.0`、pnpm `11.7.0`、Python `3.13.13`（`.venv`）、pytest `9.1.1`
检查范围：自动化质量关卡、构建可复现性、版本/清单一致性、发布包内容、普通用户首次安装、隔离 DSH profile 集成

**初检结论：发布包本身健康，但发现一条冷启动不稳定的发布门禁。该问题已在本报告末尾的复检中修复并验证。**

---

## 1. 检查结果总览

| # | 检查项 | 命令 / 方法 | 结果 |
|---|---|---|---|
| 1 | 构建流水线 | `pnpm build:sidebar`（generate → tsc → tsdown → verify:package） | 通过 |
| 2 | 构建可复现性 | 构建前后 6 个产物 sha256 比对 | 通过（逐字节一致） |
| 3 | 打包产物完整性 | `pnpm verify:package` | 通过 |
| 4 | Node 测试 | `node --test tests/*.test.ts tests/*.test.mjs` | 通过：73/73 |
| 5 | Python 测试 | `.venv/bin/python -m pytest -q` | 通过：120 passed, 1 skipped |
| 6 | 空白/换行卫生 | `git diff --check` | 通过 |
| 7 | 版本一致性 | `package.json` / `src` / `lib` / `d.ts` / `CHANGELOG` | 通过：均 `0.2.7` |
| 8 | 锁文件同步 | `pnpm-lock.yaml` importers ↔ `package.json` devDependencies | 通过（`--frozen-lockfile` 可用） |
| 9 | 发布包内容 | `tar -tzf release/dsh-kline.tgz` | 通过：61 项，无越界文件 |
| 10 | 开发文件/密钥/本机路径泄漏扫描 | 包内条目 + `grep` 绝对路径/密钥模式 | 通过：0 命中 |
| 11 | 普通用户首次安装 | `node scripts/smoke-packed-install.mjs` | 通过 |
| 12 | 隔离 DSH profile 集成 | `node scripts/smoke-dsh-profile.mjs` | **失败（3/3 次）** → 见 F1 |

第 5 项说明：在受限沙箱下直接运行会因 npm 缓存目录（`~/.npm`）不可写而使 `test_release_packer_ignores_files_outside_the_allowlist` 报 EPERM；将 `npm_config_cache` 指向工作区内目录后全绿。属于执行环境限制，非代码缺陷（见 F4）。

---

## 2. 通过项的实测证据

### 2.1 构建可复现性

构建前后对以下产物取 sha256，**完全一致**，说明已提交的 `lib/` 与 `view/kline.html` 生成链保持同步：

```
src/client/generated-view.ts
view/kline.html
lib/client.js
lib/index.js
lib/types/client/generated-view.d.ts
lib/client/generated-view.js
```

`src/client/generated-view.ts` 由 `.gitignore` 排除（构建生成物），而 `lib/client/generated-view.js`、`lib/types/client/generated-view.d.ts` 已入库——本次确认二者未漂移。

### 2.2 测试基线

| 套件 | 结果 |
|---|---|
| Node（`*.test.ts` + `*.test.mjs`） | 73 passed / 0 failed |
| Python（pytest 全量） | 120 passed / 1 skipped / 0 failed |

唯一 skip：`test_distribution_install.py:286`「Windows default path assertion」，macOS 上预期跳过。

### 2.3 发布包内容

`release/dsh-kline.tgz`（5,517,461 字节，61 个条目，sha256 `d1ef8228…249ec5`）。

- 顶层内容：`package.json`、`README*.md`、`CHANGELOG.md`、`LICENSE`、`PROVENANCE.md`、`cordis.patch.yml`、`server.py`、`chart_service.py`、`requirements.txt`、`screenshots.json`、`config/`、`core/`、`lib/`、`tools/`、`view/`、`docs/images/`、`scripts/`。
- 包内 `package.json` 版本为 `0.2.7`；包内 `tools/fetch.py`、`lib/client.js` 与工作区 sha256 一致。
- 越界扫描 0 命中：无 `__pycache__` / `*.pyc` / `.venv` / `node_modules` / `.runtime` / `.env` / 凭据文件 / `* 2.*` 冲突副本 / 绝对开发路径。
- 包内所有 JSON 可解析，所有 Python 文件可编译。
- 重复打包得到相同 sha256（确定性构建）；`release/dsh-kline.tgz.sha256` 与当前包一致。

### 2.4 普通用户首次安装（`smoke-packed-install.mjs`）

```
PASS first launch: fresh venv + native Node launcher + Unicode/space path
PASS MCP initialize + 14 tools (14 required)
PASS anonymous index candles: 10 bars
PASS host-scoped locator + HTTP health + unauthenticated access denied
```

覆盖：全新 venv 引导、含空格与中文的路径（`profile 空格` / `运行 runtime`）、14 个必需 MCP 工具齐全、匿名指数行情真实可用、locator 绑定宿主 PID、`/healthz` 200、未认证访问 `/api/tools/*` 返回 401。

---

## 3. 待处理发现

### F1（阻塞级 · 发布门禁不稳定）冷启动引导时长与 MCP 握手 60s 超时竞争

**现象**：`node scripts/smoke-dsh-profile.mjs release/dsh-kline.tgz` 连续 3 次失败，退出码 1。

**实测证据**：

```
[dsh_kline] Dependencies ready in 60s.
McpError: MCP error -32001: Request timed out   data: { timeout: 60000 }
failed to apply loader entry mcp-dsh-kline: initial connection or tool synchronization failed
DSH exited before ready (1)
```

**根因**：首次安装时 `scripts/run-dsh-kline.mjs` 需要新建 venv 并从零安装 `requirements.txt`（含从 GitHub 构建的 `ftshare` wheel）。本机冷启动实测：

| 场景 | MCP 握手耗时 | 对比 60s 超时 |
|---|---|---|
| 冷启动（新 venv + 新缓存）A | 71.9 s | 超时 |
| 冷启动（新 venv + 新缓存）B | 55.0 s | 勉强通过 |
| 热启动（复用 venv + 缓存） | 0.7 s | 通过 |

即冷启动落在 **50–72 s**，而 DSH MCP client 的 `initialize` 握手超时固定为 **60 s**，处于刀锋竞争区间。

**影响面**：
1. `smoke-dsh-profile.mjs` 本身即冷缓存运行，无法自愈；该步骤在 `.github/workflows/release.yml:72` 中执行，且位于 `gh release upload` **之前** —— 一旦失败，已发布的 Release 将拿不到 `dsh-kline.tgz` 资产。
2. 真实首次安装方向：新用户在慢网络下首次启动 DSH Web 时，MCP 握手可能在 venv 就绪前超时。`cordis.patch.yml` 已配置 `reconnect`（maxAttempts 10），但本次观测显示**首次连接**超时是致命的（插件条目加载失败、DSH 以 1 退出），reconnect 未能救回。

**是否为 0.2.7 回归**：不是。`cordis.patch.yml` 与 `scripts/run-dsh-kline.mjs` 在本次改动中均未修改，该行为自 v0.2.6 起即存在。

**建议方向（未改代码）**：
- 让 launcher 在依赖引导期间先完成 MCP 握手（把 venv 准备推迟到首次工具调用/就绪通知之后），或在引导期对外保持 MCP 可响应；
- 或把冷启动结果缓存为可复用的 venv（例如 `DSH_KLINE_VENV` 指向持久目录）以缩短首启时间；
- 门禁侧：给 `smoke-dsh-profile.mjs` 预热缓存/提高 DSH 侧握手超时，避免把「网络慢」判成「功能坏」。

### F2（文档 · 轻微）README 的 MCP 工具清单不完整

`server.py` 注册 14 个工具，而 `README.md`「给 AI 与开发者」与 `README.en.md`「For AI and developers」仅列出 9 个，缺：

`get_watchlist`、`save_watchlist`、`market_pulse`、`market_board_detail`、`security_intelligence`

（注意 `smoke-packed-install.mjs` 已把 14 个全部列为必需，测试与文档口径不一致。）

### F3（元数据 · 轻微）`screenshots.json` 落后于 README 预览图

Manifest 列 3 张：

```
docs/images/kline-support.png
docs/images/kline-range-stats.png
docs/images/kline-news.png
```

而 README/README.en.md 实际引用 5 张，未被 manifest 收录的是两张主预览图：`docs/images/dsh-kline-tab-workspace.png`、`docs/images/dsh-market.png`。

本仓库内没有任何脚本消费 `screenshots.json`（仅出现在 `package.json` 的 `files` 白名单），推测由插件市场侧读取；若如此，市场页会漏掉两张主要截图。

### F4（环境 · 非缺陷）`pnpm pack:release` 依赖可写的 npm 缓存

打包脚本 `scripts/build-release-package.mjs` 通过 `npm pack` 落包。在缓存目录不可写的环境下会失败：

```
npm error code EPERM
npm error path /Users/jas/.npm/_cacache/tmp/
```

将 `npm_config_cache` 指向工作区内目录后，`pack:release` 与相关测试全部通过。CI 环境不受影响；记录以便本地复现发布门禁时使用：

```bash
export npm_config_cache="$PWD/.runtime/npm-cache"
```

### F5（仓库卫生 · 轻微）未跟踪的构建产物目录

`release/`（含 5.5 MB tarball）与 `.tmp-render/` 既未被跟踪也未被 `.gitignore` 覆盖，会持续出现在 `git status` 中，存在误提交大文件的风险。已确认两者**不会**进入发布包。

### F6（发布流程 · 提醒）v0.2.7 尚未提交与打 tag

- 工作区 `package.json` 为 `0.2.7`，但 `HEAD` 仍为 `v0.2.6`，且不存在 `v0.2.7` tag。
- `.github/workflows/release.yml:44` 强校验 `RELEASE_TAG === v{package.json.version}`，因此必须先把 `0.2.7` 提交并打 `v0.2.7` tag 再发布，否则 Release job 第一步即失败。
- `CHANGELOG.md` 已有 `0.2.7 - 2026-09-11` 条目，`## [Unreleased]` 为空，符合规范。`docs/` 下暂无 v0.2.7 的 release notes（现有仅 v0.2.0），如需与其他版本保持同等文档密度可补。

### F7（文档 · 极轻微）`docs/provider-adaptation.md` 新增行缺少官方文档链接

能力表新增的 `Realtime stock minute candles` 行只写了接口路径，同表其他行均为指向 `market.ft.tech` 的链接。

---

## 4. 检查未覆盖的范围

以下项目**本次未验证**，需真实环境与人工操作，不作为本次结论依据：

- 真实浏览器内的 UI 交互与视觉验收（`docs/USER_EXPERIENCE_ACCEPTANCE.md` 的 B/C/D 组）。
- 双 AI 并发归属、分栏/浮窗长时组合、老版本 profile 升级（`docs/release-acceptance-checklist-v0.2.0.md` 的 A/B/C 组）。
- 带 FTShare API Key 的付费接口（分钟 K / 新闻 / 板块等）；本次仅验证匿名免费指数行情。
- Windows / Ubuntu 上的安装矩阵（由 `install.yml` 覆盖）。
- v4 实时分钟 K 线的真实数据正确性（仅做了协议与回退路径的静态检查）。

---

## 5. 发布建议

| 项 | 结论 |
|---|---|
| 发布包（`release/dsh-kline.tgz`） | **可发布**：内容、版本、可复现性、安装冒烟均通过 |
| 自动化质量关卡 | 通过（Node 73、Python 120）+ 1 项沙箱环境限制（F4） |
| 发布门禁（CI `release.yml`） | **存在不稳定风险**（F1），建议先处理或加缓存预热再打 tag |
| 文档一致性 | 有轻微缺口（F2、F3、F7），不阻塞发布，建议随版本一并修正 |
| 仓库卫生 | 建议把 `release/`、`.tmp-render/` 加入 `.gitignore`（F5） |

按仓库既有约定，本次检查**未执行** commit / tag / push / Release。

## 6. 修复后的复检（2026-09-11）

F1 已修复：DSH 启动时若 Python 依赖尚未准备完毕，启动器会改为后台完成准备；MCP 客户端初次连接失败不会再导致 DSH Web 退出，而会按既有重连策略在运行环境就绪后接回工具。隔离 DSH profile 冒烟测试已更新为等待健康的服务 locator，而不是仅等待 DSH Web 端口打开。

复检结果：

- `node scripts/smoke-packed-install.mjs release/dsh-kline.tgz`：通过。
- `node scripts/smoke-dsh-profile.mjs release/dsh-kline.tgz`：通过。
- Python：121 passed，1 skipped；Node：73 passed。
- F2 已补齐 14 个 MCP 工具的 README 说明；F3 已将全部 5 张 README 截图纳入 `screenshots.json`；F5 已忽略 `release/` 和 `.tmp-render/`。

F4 仍为受限执行环境的 npm 缓存权限提示，不构成产品或 CI 缺陷。F7 未添加未经官方页面确认的深链；能力表保留准确接口路径，避免使用不可靠链接。
