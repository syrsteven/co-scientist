# V6 科研阅读与独立判断优化（2026-11-06）

本轮在仍 Open 的 PR #20 分支 `codex/v6-stage-workbench` 追加前端优化，保持未合并。实际实施起点 `b1d357595780c389df263a7a56efb3014a18dbd3`；PR 合并基线仍为 `758bd4132a1792da01ab996b91d78711c494d6a2`。

## 改了什么

- `workbench.js`：以候选摘要→四个阅读标签→完整原始记录替代连续11类递归对象。机制、证据、预测、必要前提/证伪和P09/R0使用专用组件。陈述全文来自保存字段；不概括改写原科学措辞、不补机制、参数或来源。未单列“问题标题”的预测明确提示该字段未提供，不替模型构造问题。
- 候选顶部展示完整主张、保存的生成/审查状态、条件性机制原文、首项关键前提/科学未知及能力边界。真实模型、开发替身、非生产政策分别标记；没有评分/科学准入/实验许可。完整列表及其他原始字段在对应标签和原始JSON中保留。
- “科学内容 / 证据与来源 / 科学审查 / 我的评估”共享当前候选。来源报告的候选转述、模型阅读卡和实际原文分区；不把模型卡当原文，摘要/片段/全文及未读范围分别展示。
- P09展示限定用途、政策版本、理由、具体风险和缺少信息；R0展示正式disposition、原文依据、科学未知、R1核查和限制。原有显式审查操作/同ID查询保留在该标签的折叠操作区；失败和未完成不是完成决定。
- “记录我的判断”直接绑定当前候选，五个评价维度复用 `/api/annotations`；原文弹窗“记录来源问题”绑定实际material_view与哈希。只有冻结输入来源且没有注释目标时，明确不能持久化；历史ALS只读不显示保存/修复/执行按钮。保存成功后读取后端事实，意见不注入模型。
- 研究概览展示保存的背景、最近候选及主张、逐候选正式状态、当前问题及下一步边界；入口直达候选。主导航调整为七项；简报、审查/意见汇总功能在概览和候选内保留。
- `index.html` / `workbench.css`：四标签、专用阅读卡、常驻Run状态、原文意见区和窄屏布局。`app.js`：409单独解释为本机写锁繁忙，断连不重发；只读标签/导航可在长操作中使用。`generation.js` / `candidate-review.js` 共享已读的正式审查数据；`background.js` 复用原文弹窗，不新增科学操作。

本轮**没有新增后端接口或数据字段，没有修改科学模块、Store、M12、M15、科学Prompt、政策/结果契约或历史HTML**。使用已有GET、注释POST、原始Attempt读取和显式执行入口；保留原有单写锁。模型执行期间不能并发写意见；未来如需独立写并发，需要单独评审，本轮不实施。M03/R1/Ranking/Evolution仍未实现，无执行入口或假结果。

## 使用

当前本机服务仍为 <http://127.0.0.1:8767/>，静态文件读取新前端；刷新仅读取。原服务及用户阶段库继续保留，本轮没有往其中写入开发意见。启动/重启方法见上级README和 `scripts/start_stage_workbench.sh`，本轮不改变服务或模型配置。

1. 我的研究→选择研究卡→概览→点击具体候选。
2. 顶部先读完整主张、生成/审查状态及核心前提，再在四个标签内查看机制、来源、正式审查和自己的判断。
3. 原文按钮显示本次实际取得的文本/范围；需要时点击“记录来源问题”。有可保存的目标时自动绑定；不能保存时如实说明。
4. “记录我的判断”自动打开当前候选的五维评估。保存后显示已保存记录；刷新后再次打开该候选的“我的评估”读取。未保存草稿仅在本页内存中，不写浏览器存储。
5. 原始候选、全部冻结输入、模型结果、用量及请求/原始响应保留在折叠详情；查看这些内容只GET。
6. 历史演示→浏览已保存ALS：同样的四标签阅读，但不提供写操作；V5演示继续是独立禁止联网沙箱。

## 工程验证

在已有conda `coscientist`（Python3.12）与Node环境实际执行：

```sh
PYTHONPATH=src /Users/lemintea/anaconda3/envs/coscientist/bin/python -m pytest -q tests/next
/Users/lemintea/anaconda3/envs/coscientist/bin/python -m ruff check src/co_scientist_next tests/next
for f in src/co_scientist_next/frontend/*.js; do node --check "$f"; done
/Users/lemintea/anaconda3/envs/coscientist/bin/python -m build --wheel --sdist --no-isolation --outdir /private/tmp/co-scientist-reader-build
```

- 开始前原398项全量：398 passed，56.03s。
- 最终全量：**403 passed，失败0、跳过0**，54.81s。新增5项在 `tests/next/test_reader_frontend.py`：完成/技术状态与执行方式；Run/候选/内容版本筛选；只读历史解码/原字段/未知用量；专用DOM组件、四标签、字段完整性、只读/不可注释边界；HTTP409及断连每次仅一次发送、不自动重试。单元DOM为最小离线harness，不冒充浏览器测试或科学验证。
- Ruff、全部Next前端JS语法、wheel和sdist构建通过。旧G3全套及任何在线模型/Europe PMC检查**未运行**。
- 真实浏览器IAB桌面1280px、390×844窄屏：从研究卡进入概览、直达候选，四标签切换，原文弹窗/范围，候选内和来源意见保存、刷新读回，兄弟候选无意见/审查继承，跨Project/Run空状态，新建任意“光周期与开花”问题及固定Run不继承旧候选。浏览器控制台未出现页面错误。
- 延迟4秒的纯开发Goal适配器：执行期间点击GET刷新和研究过程仍能读取running事实；完成后再次刷新，恰有两个原Goal任务/两个Attempt，各ordinal=1，未重复提交。证据 `slow-fixture-check.json`、`screenshots/fixture-running-refresh.png`。不是付费请求或真实Goal能力测试。
- V5十候选、排序阅读、选两条并排比较及G0→G3历史边界实际操作；未穷举所有历史组合。原历史HTML字节未改。
- 390px真实ALS长文本：document/body scrollWidth均390，无整页横向溢出。桌面均1280。原始记录使用局部换行/滚动。

## 真实ALS只读验收

来源：PR #19既有隔离试跑库 `/private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite`，通过现有只读 `/api/history`，不创建新的Run或模型结果。

实际页面保留条件性主张、四项新桥接和核孔蛋白真实磷酸化未确证的前提；P08已保存真实输出，P09为真实模型在development/nonproduction政策下的限定用途pass，P10为真实 `proceed_to_R1`。正式R0有**6项科学未知、8项R1核查、空阻断缺陷列表**，均逐条原文呈现。R1未执行且能力未实现。ANXA11/SUN1来源措辞弱化没有被添加为正式R0发现，仓库Codex REVIEW未被注入页面正式结果或新Run。

真实记录、纯开发夹具和V5历史演示分别标明。实际保存意见只在新建 `/private/tmp/co-scientist-reader-fixture/reader.sqlite` 开发库：候选内判断与来源问题各独立一条。另有空Run用于隔离验证；夹具本身不代表科学相关性或模型表现。

## 截图索引

| 文件 | 证据 |
|---|---|
| `screenshots/fixture-overview.png` | 开发研究概览、候选和原始问题 |
| `screenshots/als-summary.png` | 真实候选顶部全文及正式状态 |
| `screenshots/als-mechanism.png` | 来源／作者解释／新猜想分区机制 |
| `screenshots/als-predictions.png` | 候选与竞争解释、比较及测量 |
| `screenshots/als-source-range.png` | 实际正文片段与只读边界 |
| `screenshots/als-candidate-ethics.png` | 真实P09限定用途及政策 |
| `screenshots/als-r0-unknowns.png` | 正式R0六项未知／八项待核查 |
| `screenshots/fixture-assessment.png` | 当前候选内保存的独立人工判断 |
| `screenshots/fixture-process.png` | 真实持久化的开发任务过程 |
| `screenshots/fixture-running-refresh.png` | 延迟开发操作执行中只读刷新 |
| `screenshots/v5-comparison.png` | 原V5双候选比较与排序展示 |
| `screenshots/mobile-als-reading.png` | 390px真实ALS候选长文本阅读 |

## 科学内容与原工作区保护

原工作区232项文件内容、索引和status指纹不变。原始Goal、Candidate、P09/P10、背景材料及试跑文档均未修改。两历史DB前后SHA256保持：

- p04-v2-prepared.sqlite：`a1414816be01c06535e9493f9eaa62d40ee892ad45cf024af61dc7776ab7a2b9`
- candidate-review.sqlite：`3da6812c150d38c712952ed1148c4a8f740b22a96886a69cc1bb296a5db70874`
- V5沙箱HTML：`5b59c7bfc10001593460b2a800127d9243c5f656999ccb9b65fa4b921545b875`；用户V6原件：`cce3ad7bddb9b7c141f3bd87da7079f2b823dc0907f2830e01284de20e7f702e`。

本轮真实模型请求0、真实检索0，没有新增自动重试、自动恢复或收费调用。`science_validated=false`。工程/浏览器测试不证明科学内容正确；独立科研评议、生产伦理政策成熟度、模型表现和科学验证仍未完成。
