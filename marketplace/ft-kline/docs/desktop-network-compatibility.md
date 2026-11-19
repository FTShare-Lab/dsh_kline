# macOS DSH 桌面网络崩溃与插件规避

## 已观察事实

2026-11-18 至 11-19 的六份本机崩溃报告均为 DSH Desktop 0.2.2-rc.3（macOS arm64、Electron 44.7.0、Node 24.21.0）宿主进程退出，错误为 `setTypeOfService EINVAL`，栈进入 `node:internal/deps/undici` 的 `writeH1`。

从已安装应用的配套 Node 运行时读取到 Undici 7.29.1，其 HTTP/1 写入逻辑直接调用 `socket.setTypeOfService(request.typeOfService)`，没有捕获该同步异常。只读 ASAR 分析记录应用 SHA-256 为 `c0ce89f77d25e98e11952728d1fc054b6e2300db17402af83a1a225c8b36e843`；只分析所选入口，未执行包内脚本，也未完整审计宿主。

上游已有对应报告及修复：

- [Undici #5544](https://github.com/nodejs/undici/issues/5544)：macOS 套接字状态变化时的未捕获异常。
- [Undici #5547](https://github.com/nodejs/undici/pull/5547)：将 QoS 设置作为可失败的尽力操作。
- [Undici 7.x 回移跟踪 #6075](https://github.com/nodejs/undici/issues/6075)：旧版本仍可能受影响。
- [DSH 对应反馈 #9557](https://github.com/deepseek-ai/deepseek-harness/discussions/9557)。

安装插件发生在崩溃前，不足以证明请求来源；现有栈没有保留 URL。此前版本的报告也出现同一错误，不能归因于本次官网或 UTM 改动。

## 插件改动

插件在宿主中的行情后端代理和健康检查改用 Node 的 `http.request`，仅允许无用户信息的 `http://127.0.0.1` 或 `http://localhost`。不调用全局 fetch，不设置套接字 QoS，不复用后端连接，不追随重定向。

保留后端实例身份校验、请求中的服务 Token、原始 UTF-8 JSON、完整请求超时以及响应大小限制；超时和连接重置作为失败请求反馈，不能静默成功。没有修改宿主安装包、全局 Socket 原型、异常处理或权限。

## 验证与边界

在 DSH 自带 Node 24.21.0 的独立子进程内，将 Socket 的 QoS 调用替换为抛出相同错误的故障注入器：旧全局 fetch 导致退出码 1，Promise catch 未执行；新的插件通道不调用该方法，健康检查与带 Token 的中文 POST 正常完成。另覆盖连接重置后可再次请求、完整响应体超时、过大响应和重定向边界。

这是受控实验，不是声称自然复现了原始用户操作。此规避只覆盖插件自己的本机网络请求，无法保证 DSH 其他模块的 fetch 不再崩溃；完整宿主修复仍需 DSH 更新所用的网络实现或运行时。本地 DSH Web 可作为继续验收入口，不代表桌面版缺陷已消失。
