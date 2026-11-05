# v0.6.6 验收

## 功能与回归范围

- 未配置 Key、FTShare SDK 缺失或初始化失败时，仍可从独立公开目录刷新港美股证券；搜索输入不调用供应商网络接口。
- 常用中英文别名、旧缓存补全、英文名称合并后的别名保留、目录格式兼容、目录源故障时的缓存回退。
- Nasdaq 两份目录的格式解析、测试证券和不支持代码的过滤、错误响应不被标记为完整目录。
- 港美股的 401、403、400、429 与 5xx 不再进入 A 股历史接口；保留原始错误类型，不把匿名访问认定为有效 Key。
- `BRK.B.US` / `BRK.B.NYSE` 的股类保留、美股不复权数据的真实元信息。
- 无 Key 板块提示、权限不足和临时上游故障的界面分支。
- DSH 客户端构建、启动目录校验、独立公开插件目录同步及双包校验。
- macOS/Linux/Windows × Python 3.11/3.12/3.13 的完整行为测试、普通安装、DSH 独立与嵌套安装、Codex 桌面/CLI 安装烟测。

## 证据与发行门槛

- 功能提交 `8637ba3` 的 [test 分支九组 CI 全部通过](https://github.com/FTShare-Lab/dsh_kline/actions/runs/42008850491)后已合并 main；完成的 Linux CI 日志记录 Node 342 项、Python 529 项通过，另有 1 项跳过和 361 个子测试通过。
- 隔离的无 Key 进程实测苹果日 K 返回 5 根；腾讯港股返回明确的匿名访问权限限制，不再被 A 股接口的 400 覆盖。禁用 FTShare SDK 后仍能刷新公开目录，实测港股 3,270 项、美股交易所证券 12,864 项；这些是当次快照数量，不是永久覆盖承诺。
- v0.6.6 的版本发行提交须重新通过同一提交的九组 [安装 CI](https://github.com/FTShare-Lab/dsh_kline/actions/workflows/install.yml)，再合并 main、创建标签并运行 [双包发行流水线](https://github.com/FTShare-Lab/dsh_kline/actions/workflows/release.yml)。
- 草稿资产须下载后核对 SHA-256、GitHub 资产摘要、包内版本和实际文件内容；Codex ZIP 须与提交中的公开插件目录逐文件一致，再正式发布。

未增加实际桌面画布的人工验收；界面提示通过执行视图分支的自动化测试验证。免费港美股日 K 仅完成初步只读评估，尚未接入自动备用链路；板块、分钟和新闻等权限不由搜索目录推断。详细边界见 [无 Key 说明](anonymous-market-support.md)。
