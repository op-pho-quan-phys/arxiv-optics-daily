# arXiv Optics Daily

这个项目是一个适合放到 GitHub Pages 上的静态网页生成器。它会每天抓取 arXiv 当天公告页中的新论文，范围限定为 `cond-mat`、`physics`、`quant-ph`、`eess`，然后筛出和光学方向相关的文章，最后生成一个可在线浏览的日报页面。

当前版本已经覆盖了你最核心的目标：

- 从 arXiv 当天 `new submissions` 页面抓取论文
- 按光学方向做关键词筛选和主题归类
- 可选接入 DeepSeek，为每篇论文生成英文 / 中文 / 日文的一句话总结
- 输出静态 HTML 页面，适合直接挂到 GitHub Pages
- 自动生成归档页和最新一期跳转页

## 为什么选 arXiv 的 `list/<category>/new`

对于“当天 arXiv 新出的论文”这个口径，最接近需求的入口不是通用搜索，而是分类公告页：

- `https://arxiv.org/list/cond-mat/new`
- `https://arxiv.org/list/physics/new`
- `https://arxiv.org/list/quant-ph/new`
- `https://arxiv.org/list/eess/new`

这样拿到的是 arXiv 当天公告批次里的论文，更符合“每日文献日报”的语义。

官方资料可参考：

- arXiv 新论文公告和更新时间说明: [Availability of submissions](https://info.arxiv.org/help/availability.html)
- arXiv API 用户手册: [API User Manual](https://info.arxiv.org/help/api/user-manual.html)
- arXiv 分类体系: [Category Taxonomy](https://arxiv.org/category_taxonomy)

## 项目结构

```text
.
|-- .github/workflows/daily-update.yml
|-- arxiv_optics_config.json
|-- index.html
|-- optics_daily/
|-- requirements.txt
`-- tools/generate_arxiv_optics_daily.py
```

## 第一步：本地准备

你只需要 Python 3.11 或更新版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python tools/generate_arxiv_optics_daily.py
```

运行结束后，生成结果会写到 `optics_daily/<日期>/index.html`，同时会更新：

- `optics_daily/index.html`
- `optics_daily/latest.html`
- 根目录 `index.html` 会跳转到最新一期

如果你想启用 DeepSeek 三语总结，先设置环境变量：

```bash
export DEEPSEEK_API_KEY="your_api_key_here"
python tools/generate_arxiv_optics_daily.py
```

如果没有设置 `DEEPSEEK_API_KEY`，脚本会自动回退到本地英文首句提取 + 机器翻译。

## 第二步：理解这条流水线

整个网页生成过程可以分成 5 步：

1. 抓取当天四个 arXiv 分类页的 `new submissions`
2. 解析出标题、链接、作者、摘要、分类、主题信息
3. 用光学关键词判断是否属于目标方向
4. 生成英文一句话总结，并翻译成中文和日文
5. 把结果写成静态网页和 JSON 数据

如果你之后想把筛选做得更准，可以把第 3 步和第 4 步升级成大模型分类与总结。当前代码先用一个可直接上线的基线版本把流程跑通。

## 第三步：调整“什么算光学方向”

核心配置在 `tools/generate_arxiv_optics_daily.py` 里，主要有两层：

- `TOPIC_KEYWORDS`
- `GENERAL_OPTICS_KEYWORDS`

当前主题标签包括：

- Integrated Optics
- Nonlinear Optics
- Quantum Optics & Quantum Computing
- Optical Computing
- Optical Imaging
- Optical Materials
- AMO Physics
- Other Optics

如果你发现筛选太宽或太窄，就直接改这些关键词集合。这个阶段最重要，不需要一开始就追求“完美分类”，先让每天自动出一版结果，再迭代关键词。

## 第四步：把网页发到 GitHub Pages

1. 新建一个 GitHub 仓库
2. 把当前目录的所有文件上传到仓库根目录
3. 打开 GitHub 仓库设置里的 Pages
4. Source 选择部署当前分支根目录
5. 等几分钟，网页就会从仓库地址发布出来

由于根目录 `index.html` 会跳转到 `optics_daily/latest.html`，所以打开仓库页面时会直接看到最新日报。

## 第五步：让它每天自动更新

工作流文件在 `.github/workflows/daily-update.yml`。

它会：

1. 拉取仓库代码
2. 安装 Python 和依赖
3. 运行生成脚本
4. 提交新的 `optics_daily/` 输出
5. 推回仓库，让 GitHub Pages 自动更新

当前 cron 设在每周一到周五 `02:30 UTC`。这个时间点比 arXiv 的当日公告更晚，适合稳定抓取当天批次。

## 第六步：如果你想把筛选做得更准

关键词法的优点是便宜、稳定、容易上线，但它会有两个常见问题：

- 有些“带 optical 一词但不属于你想看的光学方向”的论文会混进来
- 有些没有明显关键词、但其实很相关的论文可能被漏掉

更好的升级路线是：

1. 先保留当前关键词做粗筛
2. 再把粗筛结果送给大模型做二次判断
3. 让大模型输出：
   - 是否属于光学方向
   - 属于哪几个子方向
   - 英文一句话总结
   - 中文一句话总结
   - 日文一句话总结

这样每天要调用模型的论文数会小很多，成本也可控。

## 第七步：你真正需要按什么顺序做

如果你准备从零开始把它做成线上网页，最顺的顺序就是：

1. 先运行当前版本，确保可以稳定抓到当天论文
2. 打开生成的网页，人工看 2 到 3 天结果
3. 调整光学关键词，减少误判
4. 上传到 GitHub，先把自动发布跑通
5. 最后再决定要不要接入大模型，提升筛选和摘要质量

这个顺序的好处是，你不会一开始就卡在“分类到底准不准”或者“摘要要不要最先进”，而是先拿到一个真的能每天更新的网站。

## 你可以优先改的地方

- 如果你更关心集成光学，把 `集成光学` 关键词扩展得更细
- 如果你更关心量子光学，把 `single-photon`、`cavity QED`、`quantum photonics` 相关词再补充
- 如果你想只看高置信度论文，可以把筛选规则改成“命中至少两个主题词才收录”
- 如果你想做得更漂亮，可以把 HTML 模板换成你喜欢的视觉风格

## 后续建议

你现在最适合做的不是从头重新设计，而是：

1. 先跑一遍当前骨架
2. 看看筛出来的论文是不是接近你的口味
3. 再让我帮你做第二版

第二版我可以继续帮你做这些事情：

- 接入大模型做更准的光学分类
- 把页面改成更像真正产品的网站
- 增加按主题、作者、关键词、日期的筛选
- 增加 RSS / JSON API 输出
- 改成 Vercel 或 Cloudflare Pages 部署
