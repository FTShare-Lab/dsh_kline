# npm 首次发布准备

候选：`@ftshare-lab/dsh-kline@0.6.9`，公共 npm registry，公开访问。

npm 安装包与 DSH GitHub 发行资产使用同一份已验证的 TGZ，避免发布时重新取到不同内容。`package.json` 已移除 `private` 并设置 `publishConfig.access=public`。上传需在跨平台 CI、发行资产核对及 npm 登录验证后执行。

## 发布前

1. 推送候选到 `test`，等待九组跨平台 CI 全部通过，完成 DSH/Codex 桌面验收，再合并 `main`。
2. 创建 `v0.6.9` 标签，等待现有发行流水线生成草稿资产；下载 TGZ/ZIP，校验版本、SHA-256 和内容。
3. 本机使用 `npm login` 登录有 `@ftshare-lab` scope 发布权限的账号；`npm whoami` 核对账号。首次 scope 权限尚未验证，GitHub 组织权限不等于 npm 组织权限。
4. 对准备上传的 TGZ 执行下面的 dry-run。dry-run 只验证打包与命令，不证明 npm 权限或正式上传会成功。

```sh
npm publish ./release/dsh-kline-v0.6.9.tgz --access public --dry-run
```

## 获准发布后

对核对过的同一份 TGZ 执行；如 npm 要求身份验证，由维护者完成。

```sh
npm publish ./release/dsh-kline-v0.6.9.tgz --access public
npm view @ftshare-lab/dsh-kline@0.6.9 version dist.integrity dist.tarball
```

在全新 DSH profile 验证按包名安装后，再提交插件市场目录将来源关联到该 npm 包。当前包尚未公开，README 继续提供可用的 GitHub 正式版安装路径。

## 统计口径

市场显示 npm 下载量需市场目录关联本包，发布 npm 本身不会自动改目录。下载包含更新、重复下载和自动构建，不能称为安装人数；本候选未添加用户追踪或安装遥测。

参考：[npm 公开 scope 包](https://docs.npmjs.com/creating-and-publishing-scoped-public-packages/)、[npm publish](https://docs.npmjs.com/cli/commands/npm-publish/)。
