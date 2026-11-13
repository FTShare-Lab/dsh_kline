# 嵌入式图表：把 K 线挂进宿主面板

侧栏是图表的一种宿主，不是唯一一种。本页记录把同一个图表挂进**有界面板**（画布卡片、模拟盘侧栏、任意自建面板）时，宿主与插件之间的契约；没有这些选项时，插件的行为与侧栏挂载完全一致。

## 宿主侧入口

`src/client/KlineContent.tsx` 的 `StandaloneKlineApp` 接受一组可选宿主属性（类型定义在 `src/client/embed.ts`）：

| 属性 | 取值 | 作用 |
| --- | --- | --- |
| `embedded` | `boolean`，默认 `false` | 有界面板模式：对话框与提示锚在面板内，布局按面板高度排版，不再使用整页定位 |
| `chrome` | `'full' \| 'chart' \| 'chart-search'`，默认 `'full'` | 保留的工作区外壳：完整工作台、只留图表页、图表页加标的搜索 |
| `theme` | `'dark' \| 'light'`，省略即跟随宿主文档 | 固定图表的调色板；挂载后改变也只重绘，不重挂 |
| `symbol` / `name` | 标的代码与名称，可选 | 外部选择联动：面板选中的标的推给图表，同一标的不会重开 |
| `onIdentity` | `(symbol, name) => void` | 图表内的搜索或切换回调给宿主，宿主据此更新自己的单据 |

`embedded` 与 `chrome` 落到宿主元素的两个数据集属性（`data-embedded`、`data-chrome`），视图侧只按这两个属性选样式；侧栏挂载不带属性，因此内嵌样式不可能误命中侧栏。

标的比较保留市场身份，仅归一化同一市场的别名（如 `SH` / `XSHG`）。不带后缀的代码按图表输入规则解析；存在歧义时，宿主应传完整代码，例如 `000001.XSHG`（上证指数）与 `000001.XSHE`（平安银行）。不同代码的前缀相同不会被视为同一标的。

挂载后移除 `theme` 属性会解除固定配色，恢复宿主主题路径，无需重新挂载图表。

## 视图侧的桥

内嵌挂载时，视图在 `window.__DSH_KLINE_EMBED__` 上装一组宿主可调用的方法：

- `ready`：首帧就绪的 promise；
- `openSymbol(symbol, name?)`：打开一个标的；
- `currentSymbol()`：当前图上的标的；
- `setTheme('host' | 'dark' | 'light')`：`host` 表示重新跟随宿主文档。

桥只在 `embedded` 时安装，侧栏视图的原有对外表面不变。要求宿主等 `ready` 之后再调用，避免与首帧竞争。

## 宿主需要保证的三件事

1. **有界**：面板自身要有确定高度。内嵌模式按 `document.documentElement.clientHeight` 取高度，宿主不提供高度时图表会退化成内容高度。
2. **调色板**：面板背景与文字颜色由宿主决定，需要一致时显式传 `theme`，不要依赖宿主 DOM 的 CSS 变量被继承进来。
3. **不弹全屏对话框**：内嵌模式下对话框是面板内的绝对定位元素；宿主不要给面板 `overflow: visible`，否则对话框会盖到面板外。

## 可选：宿主面板槽位

侧栏和 Tab 之外，宿主也可以在自己已有的有界面板里放一张图表，而插件不需要认识宿主：宿主的客户端半声明一个槽位、渲染时把 `{ symbol, name, onIdentity }` 传给座位，然后调用插件提供的 `klinePanels` 服务填充它。

```ts
// 宿主客户端半
ctx.inject(['klinePanels'], scope => {
  const panels = scope.get('klinePanels') as {
    mount(seat: string, options?: { chrome?: 'full' | 'chart' | 'chart-search' }): () => void
  } | undefined
  if (panels === undefined) return () => {}
  return panels.mount('paperTrading.kline') // 宿主自己声明的槽位名
})
```

- 只有调用 `mount(seat)` 才会往宿主已声明的槽位注册；没有调用的宿主不会注册任何东西，行为与没有本契约的版本一致。
- 面板体就是侧栏那张图：`chrome` 与上述内嵌契约同义，默认 `chart-search`；`symbol` 跟随宿主选择，`onIdentity` 把图内的选择回写给宿主。
- 每个座位一个独立会话（`host-panel:<seat>`），同一宿主挂多个面板不会互相串数据。
- 同一槽位、相同 `chrome` 的重复挂载共用一个图表，各调用方独立释放；最后一个调用方释放后才卸载。清理函数可重复调用，旧清理函数不会移除后来重新挂载的图表。槽位占用期间不接受不同的 `chrome`，需先释放再切换。

## 可选：宿主偏好

宿主的客户端半还可以提供 `klineHost` 服务，调整图表自绘的界面元素；没有该服务、字段缺失或取值不认识时，一律回到默认行为：

| 字段 | 取值 | 作用 |
| --- | --- | --- |
| `entry` | `'tab'` | 宿主自己提供图表入口（原生右栏）；图表不绘制经典浮动 K，并优先使用宿主的右栏 |
| `onboarding` | `'off'` | 不显示首启欢迎与一次性界面提示，也不写入相关存储 |

```ts
// 宿主客户端半
ctx.provide('klineHost', { entry: 'tab', onboarding: 'off' })
```

## 边界

- 本节描述的是**同一插件内的挂载契约**，不是跨包的 ESM 入口：客户端的交付形态是 DSH 的浏览器模块（`window.__ModuleLoader__`），第三方面板插件通过宿主槽位获得图表，而不是 `import` 本包。
- 图表的数据源、指标、绘图与对话共享链路与侧栏挂载共用同一套代码；内嵌不引入第二条取数路径。
