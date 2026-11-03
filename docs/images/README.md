# README 产品概览图与演示截图

## 产品概览图

- `readme-workflow-zh.png`：用户提供并指定用于中文版 README 的产品流程图。
- `readme-workflow-en.png`：用户提供并指定用于英文版 README 的产品概览图。

两张图按原样保存，没有嵌入图片元数据。它们是概念性说明，不是真实业务截图或功能验收记录；README 正文说明了当前平台、自动研究条件和人工交易边界。

## 演示截图

这些图片由实际前端构建渲染，API 响应全部来自 `devtools/readme_screenshots.mjs` 中的合成数据。项目、目标、商品、卖家、报价和研究结论均为模拟，不是用户业务数据，也不是模型质量或真实交易验收证据。

生成时只在随机本机端口托管静态前端，不启动应用后端。浏览器上下文不复用用户登录资料；API 请求全部拦截，站外请求阻止。唯一允许的模拟写请求是生成目标草案，不保存目标、不启动采集、不调用模型。

截图包含“界面演示 · 全部数据为模拟”标记。图片没有真实商品照片、账号标识、本机路径、Token 或浏览器地址栏。

安装 `web` 的开发依赖和 Playwright Chromium 后，可在仓库根目录重新生成：

```powershell
node devtools/readme_screenshots.mjs
```

- `readme-overview.png`：当前目标和模拟研究概览。
- `readme-products.png`：4 件模拟商品的比较列表。
- `readme-goal-edit.png`：模拟修改意图与尚未保存的目标草案。
- `readme-shortlist.png`：报告候选、收藏与待核实事项。
- `readme-monitors.png`：单次、限时与长期监控的模拟状态。
- `readme-research.png`：模拟研究答复、研究安排与追问入口。

## Logo 与动态导览

`readme-logo.svg` 提取自当前前端的品牌图标，用于 README 的项目标识，没有引入参考网站的 Logo 或界面素材。

`readme-tour.gif` 是 20 秒的五工作区界面导览，由实际前端的 5 个模拟数据画面编码而成，按左侧导航顺序播放：研究概览 → 候选清单 → 全部商品 → 监控任务 → Agent 研究。它展示页面导航，不演示真实商品逐渐入库，也不代表实际执行了 AI 研究。画面始终标明模拟数据。

重新生成截图、Logo 及 GIF（需本地 Python 环境安装 Pillow）：

```powershell
node devtools/readme_screenshots.mjs --tour
```
