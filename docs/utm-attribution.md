# 官网入口与渠道统计

图表顶部「FtShare」打开官网；欢迎页和「设置 → FTShare 配置」提供注册／登录。登录后在账号中心获取 API Key，再粘贴到插件并测试连接。官网登录不会自动授权图表取数，本版不接入 OAuth。

## 前往 FtShare

官网与登录链接使用 `utm_source=dsh_kline`、`utm_medium=AI`；`utm_campaign` 按宿主使用 `dsh` 或 `codex`，`utm_content` 区分 `header`、`welcome`、`settings`、`help`、`market_footer`。中英文 README 使用 `readme-zh`、`readme-en`。

这些标签随链接交给官网。插件不上传 Key、行情、对话或安装记录。我们验证链接携带字段，无法从插件端独立确认 FtShare 内部是否完成注册、付费归因；本轮未登录用户账号或修改官方统计后台。

## 插件推广入口

[公开推广页](https://ft-kline-links.zippymarshmallow.chatgpt.site/)与[统计后台](https://ft-kline-links.zippymarshmallow.chatgpt.site/admin)由独立网站承载。后台需要管理员登录；产品字段为 `dsh_kline`，同时保留 `a-share-etf-board` 与 `a-share-vix-board` 的独立统计。历史 `kline` 记录在报表中合并到 `dsh_kline`，不删除旧记录。

GitHub README 链接使用 `utm_source=github`、`utm_medium=readme`、`utm_campaign=evergreen`，并按安装入口或徽章区分 `utm_content`。其他推广渠道可在后台生成链接。

- 页面访问、点击、复制和直接入口跳转分别记录，不能合计为独立用户或安装量。
- 页面上的一次出站点击使用一个短期操作编号；相同编号的并发请求、重试只计一次，另一次点击可以再次计数。
- HEAD、预加载、过期或无效操作编号不计点击；未带操作编号的 K-Line 直接跳转单独计为入口。
- 测试使用 `qa-` 渠道活动标签，默认报表排除，不混入真实推广数据。
- 统计网站出现故障时仍保留跳转；npm 月下载徽章来自 npm，不等于该后台的点击数。

本版独立网站来源提交：`8c8402a00061df0b2b29afb66e0d4f5e85372070`（Sites 版本 4）。
