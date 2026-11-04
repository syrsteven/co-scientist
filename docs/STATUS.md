# 项目状态 — W1-L2

## P04 v2 真实试跑及离线初审（2026-11-04）

起点main378475b2e5a86d1c6504138bc3992dae2c977e81；独立结果分支codex/p04-v2-trial-review，应用代码不改，不合并main。
使用已验收Run cea909fe8a004010b1896df1c1d98e02及原独立准备库。调用前准备包/数据库事实/两份视图与消息/HTTP均与审查版本一致；无对应旧调用。
按p04-v2-control-single → p04-v2-complement-single顺序执行，各1次新Attempt，均w1-l2-p04-context-v2、HTTP200/stop、saved。
实际模型gpt-6.1-sol/high/32768/JSON object，无temperature、600秒；无自动重试或模型切换。

| 材料 | 输入 | 输出（含reasoning） | reasoning | 结果 |
|---|---:|---:|---:|---|
| 对照摘要 | 1749 | 4273 | 1024 | 1 Attempt，saved |
| 互补Results片段 | 3328 | 6326 | 2563 | 1 Attempt，saved |
| 本轮合计 | 5077 | 10599 | 3587 | total15676；cost未知/null |

完整实际请求、原始响应、finish_reason、所有provider usage、解析结果和身份均在[结果/审阅包](trials/p04-context-v2-real/README.md)。
[20项Codex初审及6项v1比较](trials/p04-context-v2-real/codex-review.md)发现本样本情境覆盖/措辞差异，同时记录C-08潜在情境错配、M-09缺失范围歧义、M-08统计信息局部遗漏。
仅Codex初审，待独立人工复核；单次比较且Brief背景/Run/Prompt均改变，不能宣称稳定提升。science_validated=false。
Goal制备/Goal Ethics仍为此前开发替身结果，不是真实伦理审查；本轮无新公共检索、无P05–P07/P08/Candidate Ethics/R0。
原库只有两个P04背景动作，Run状态background_saved，不表示科研完成；旧Brief、旧试跑包及已审查准备包未改写。

本轮只新增结果与离线核对脚本：实际DB只读审计、包SHA/输入/原始字节/usage/引用/审阅定位及独立解压核对。
未重跑203项新系统工程回归（应用代码不变），未做独立专家科学验收或稳定性试验。用户原工作区232项改动与暂存状态指纹保持不变。

## 以下保留准备阶段及更早交付的历史记录

## P04 context-v2 与独立新Run准备（2026-11-04）

实际起点main：`87668c8ee84a52aa3109830cd7dbef02d0a32f28`；独立分支`codex/p04-context-preparation`。
代码/准备数据commit：`776b202383ab47d112d5d4e95bc76c023a05014f`；后续提交仅STATUS/验证记录，独立PR不合并。

| 维度 | 本轮实际状态 |
|---|---|
| P04 | 新版本w1-l2-p04-context-v2；按实验保留Abstract/Highlights/In Brief互补情境；缺失限定当前视图；忠实保留作者诱导/相关措辞，限制单列；原字段区分来源报告/作者解释/模型外推/未建立关系 |
| 历史兼容 | 每个action固定版本；老库仅追加身份列，原v1文字保留，不重写请求/响应/结果；跨进程成功回放不重发测试通过 |
| 新Brief/Run | 新Project/Revision/Run、独立库；原科学问题及两项约束保留，新背景移除“仅检索、不执行阅读”；旧Brief/Run和原试跑文件未变 |
| Goal/伦理 | 新Run仍用明确开发模式Goal/Goal Ethics替身与示例政策，不是真实制备/伦理审查，不作为生产默认 |
| 实际材料 | 重新取得首次预印本2746字符摘要对照（与原文相同）；另取PMID35112738/PMC9016352开放全文125363字符，显式选Results小节[33770,41370)共7600字符；保留完整所得内容、未选范围与原始响应 |
| 来源边界 | 新增材料为条件依赖的无效应/作者限制对照，不是ANXA11播种研究的直接反驳、独立复现或核孔蛋白磷酸化证据；CCBY4许可及作者/DOI保留 |
| 实际发送 | 本轮5次真实公共发送（人工身份查询2、metadata2、fulltext1）均经M15；无隐藏重试；新库另有2个本地Goal开发替身Attempt，不能计真实模型调用 |
| 模型与科学模块 | **0次模型请求**，新库P04阅读/seed/readiness/背景动作均0；未在该Run执行P05–P07、P08、Candidate Ethics或R0；新Prompt模型遵从性及科学表现未验证，science_validated=false |
| 待执行配置 | gpt-6.1-sol/high/max_completion_tokens32768/JSON object，无temperature，timeout_seconds600；不读模型凭据/不授权；不自动使用替身 |
| 页面 | 已显示新Prompt版本、材料片段/范围、未授权无凭据模式及Goal测试声明；IAB刷新实测仍读取已存数据，阅读/真实模型Attempt为0，无浏览器错误 |
| 检查 | 在代码commit776b202上新系统**203 passed、0 failed、0 skipped**（原197+新6），含本地HTTP与跨进程恢复；Ruff/7文件format/JS语法/独立包校验通过 |

[准备包/恢复/页面与待执行命令](preparations/p04-context-v2/README.md) ·
[来源/选择/范围清单](preparations/p04-context-v2/material-manifest.json) ·
[验证证据](verification/p04-context-v2/RESULTS.md)。
本轮不进行真实P04试跑，不把工程检查或Codex选材当科学验收；独立专家审阅、新Prompt真实模型效果、本机Python3.12及旧G3全套回归均**未运行**。
原工作区232项改动与暂存指纹保持不变。原M00 Accepted及W1 Proposed状态不改变；不直接合并本轮PR。

## 以下为PR #8及更早的历史交付记录

## 首次真实P04：初审与独立PR交付（2026-11-03）

基线main重新fetch核实为 `e705953818feb866dddfcb8093fbc6230e02978f`。
独立分支 `codex/w1-l2-trial-preparation`；代码commit `796a94b497978e7010cf5f3a2ae5e0cef926085e`，
后续提交仅为审阅/验证证据及本状态；本轮提交独立PR，保持未合并，未改main。
用户原工作区232项改动及暂存状态指纹保持不变，不切换/不stash原工作区。

| 维度 | 当前事实 |
|---|---|
| 真实文献及访问 | 已取得Europe PMC PPR1217875预印本摘要字段2746字符；含文字Highlights/In Brief，非全文、未看图或补充 |
| 已授权单次真实P04（前一轮） | gpt-6.1-sol/high/32768/JSON object，无temperature，timeout=600秒；HTTP200/stop，saved；仅一个Attempt，无自动重发 |
| 完整用量 | 输入1477、输出2785（含reasoning1010）、合计4262；cache_write1474/cached0；cost=null；原响应/完整usage保留 |
| 本轮新真实模型调用 | **0次**，仅导出/文本初审/离线测试/代码PR；不执行P05–P07、P08、Candidate Ethics或R0 |
| 模型阅读审阅 | **Codex 初审，待独立人工复核**，35项带原文字符位置/实际字段/问题；未改原始输入、模型输出或解析结果 |
| 科学与伦理验证 | science_validated=false；Goal/Ethics仍为开发适配器事实；不声称真实伦理审查、独立发现或完整W1-L2真实阅读验收 |
| 代码 | 可选显式timeout、兼容旧请求形状、finish_reason/完整provider_usage、空正文/截断/无效JSON拒绝解读、稳定trial ID和本次Attempt用量 |
| 当前工程验证 | **197 passed、0 failed、0 skipped**，在代码commit796a94b上全量tests/next；包含此前未重跑4项HTTP |

此前196和193两次均为HEAD=e705加未提交修改，并非两个已提交版本；196+新增1项旧请求兼容性测试=197，
排除4项HTTP后=193。上轮全量复跑审批容量失败的缺口已在本轮获准回归中补齐；
详细命令/代码版本边界/历史日志见[测试证据](trials/w1-l2-first-real-p04-review/TEST_PROVENANCE.md)。
旧G3全套回归、本机Python3.12和独立专家科学审阅本轮**未运行**。

[审阅包入口](trials/w1-l2-first-real-p04-review/README.md) ·
[35项对照](trials/w1-l2-first-real-p04-review/codex-initial-review.md) ·
[ZIP](review-bundles/w1-l2-first-real-p04-review.zip)（SHA-256见旁边.sha256）。
未发布SQLite/旧替身P04–P07记录/凭据；仓库可访问路径交付，不只提供本机链接。

初审重点：SH-SY5Y情境遗漏，“未知”须限定视图，“诱导”与“伴随”的措辞层次、作者机制总结句定位、
空阴性数组不等于干预无效；固定Goal存在早期仅检索阶段的历史文字，已披露但不篡改本次输入。
以上为Codex文本初审，不是独立科学验收；原W1包仍Proposed，M00不变。

## 以下保留PR #7及更早交付的历史记录

## PR #7 总控复现修正（2026-11-03）

修正起始head：`43ca215b0e7f7ac19b353ca4107d728e1449398f`；继续同分支/PR，不合并。
原进展指纹只含材料/查询，遗漏了阅读和背景综合的实质变化，可能把补充阅读后的P07错误判成no_progress。
现以内容规范化P04卡片/待读请求、P05概览/竞争解释/关系及依据/限制/选择，与原文/查询/具体程度一起比较；
临时引用映射成对应内容并去重，不把新ID、时间戳或重复记录计作进展。不同Run/seed范围保持隔离。
历史P07按已保存input重算新指纹，历史结果不改写，无数据迁移；新记录标记p07-preparation-content-v2。
页面提示已同步。新增回归覆盖同原文有效重读、仅综合更新、重复阅读/重建包、ID/时钟变化和seed隔离。
本轮无真实付费模型调用、无新公共检索、无P08/Candidate Ethics/R0或科学验收扩展。
限制：比较结构化内容，不判断科学价值；自然语言同义改写可能触发重评。
本次检查：183 passed、0 failed、0 skipped（原176 + 新7），背景专项23项通过；
Ruff/33文件format、两JS语法、Wheel构建和新编文件空白检查通过，用户232项改动指纹未变。
页面实测以旧版P07已保存输入作相同内容检查，v2返回no_progress且无新Attempt（13→13）；刷新0 POST，无JS错误。
记录见 [progress-fix-tests.txt](verification/w1-l2/progress-fix-tests.txt)、
[页面检查](verification/w1-l2/progress-fix-browser.json)及[提示截图](verification/w1-l2/progress-fix-no-progress.png)。
未运行真实模型/付费调用、专家科学审阅及Python3.12本地回归；原科学未验证状态不变。

## 原W1-L2交付（2026-11-03，Asia/Shanghai，以下保留原验证记录）

重新fetch核实main / 起始commit：`cb3f79f987e6c14a6f8d2c5475868f17414f7a96`，PR #6已合并。
独立分支 `codex/w1-l2-reading`，checkout `/private/tmp/co-scientist-w1-l2`；独立PR，不直接合并。
最终head以该PR及 `git rev-parse HEAD` 为准。用户原工作区232项改动、暂存区与status指纹保持不变。
M00 Accepted、W0-T4接受决定不改，原W1 v0.4包仍Proposed，旧G3未改。

| 维度 | 实际状态 |
|---|---|
| 已实现 | P03计划/显式LiteraturePort执行接入、P04选定视图阅读、P05中性/单seed综合、分离P06定向与开放调用、P07逐seed readiness |
| 真实适配器 | 独立OpenAI Chat HTTP客户端、显式模型/端点/参数配置、独立凭据与授权开关、无SDK隐藏重试、实际请求/原始响应/用量记录 |
| 替身验证 | 离线夹具、模拟OpenAI HTTP、真实本地页面/SQLite持久化和恢复已验证；不计为真实模型阅读 |
| 真实模型调用是否执行 | **未执行**，本轮0次真实供应商请求/付费模型调用；只提供后续另获授权后的单次P04命令 |
| 模型阅读表现是否审阅 | **未审阅**；未做真实输出科学准确性、负结果理解或种子质量审阅 |
| 科学有效性是否验证 | **未验证，science_validated=false**；不宣称完整W1-L2已通过真实阅读验收 |
| 页面/M12 | 逐步显式操作、原文/模型解读分区、状态/负结果/来源/背景/seed/readiness/配置/用量可读；ready停等待生成，刷新不执行 |

只增加material_views与background_actions两表，复用Run/Task/Attempt/Result；无独立服务或通用图工作流。
新代码：background.py、background_ops.py、reading_model.py、background_trial.py和background.js。
Store/Scheduler/workspace及既有LiteratureService只作当前切片必要接入，不调用旧Orchestrator。
实施/操作/官方文档/输入隔离见 [W1_L2_BACKGROUND.md](W1_L2_BACKGROUND.md)。

### 运行与当前可操作页面

```sh
cd /private/tmp/co-scientist-w1-l2
PYTHONPATH=src python -m co_scientist_next.workspace --db runs/w1-l2-live.sqlite --port 8786 --development-test --development-reading --public-literature
```

已启动 `http://127.0.0.1:8786/#run=9b5abf8a5ccd496d8c45ff9a6666b20e`。
数据库是既有W1-L1真实获取事实的一致独立备份，源数据库只读、未修改；不是V5内置结果。
Goal/Ethics与本轮背景结果均清楚标为开发替身，材料是真实已取得文献。模型与公共检索各需显式启用/操作，启动不发送。
没有配置时不回退替身；真实模式没有授权时不发送。当前无真实模型凭据读取。

### 最小契约和边界

- 材料视图固定Run/Goal/seed范围、获取Task、来源/版本/位置、字符范围/SHA与裁剪理由；原始材料不被转述覆盖。
- P04保留上下文、干预/对照、实测终点、观察/负结果、作者解释、未证明与外推。摘要/片段不升级成完整全文阅读，图像/补充未读。
- P05使用实际解读与执行查询；保留所选卡片/原文/负结果/竞争解释与覆盖限制。不做M05正式评级、M06 Dossier或新颖性结论。
  排除解读需显式理由，当前不允许排除已知负结果；容量不够明确不调用，不无记录截断。
- P06_OPEN单独调用，实际输入仅Goal、中性概览、来源能力、通用约束；没有定向seed/优先机制/兄弟资料/评审答案。
  seed是问题，数量是本次配置，不成为全局科学规则；不是候选答案。
- P03保存计划不等于执行；显式执行通过LiteraturePort/M15，宽/seed意图及后续分页/fetch继续保留。兄弟定向资料/解读不能混入开放分支。
- P07 ready/retrieve_more/unable_to_prepare分别记录理由/具体程度/缺失及后续动作；无因果桥证明、判别预测完成或论文/全文配额要求。
  同资料/覆盖/具体程度不无限重复，no_progress不发模型、不改科学结论；一个seed未准备好不阻止其他seed ready。
- 技术失败/无效输出/缺配置与科学未知分离；成功本地回放，幂等结果与任务；响应保存失败留下未决发送时也不能绕过恢复继续新模型任务。
  每seed的完成决定固定在自己的packet；Run状态是最近机械操作状态，不是全局科研完成。

### 真实试跑（本轮未执行）

公开配置模板 [reading-model.explicit.json](examples/reading-model.explicit.json)故意不选model。
先另获授权、填入明确模型与支持参数，并通过独立环境变量/仓库外私密文件提供凭据。
单运行者SQLite要求先停止占用该库的页面。帮助和不带执行标志拒绝路径已验证，下面真实执行命令**未运行**：

```sh
PYTHONPATH=src python -m co_scientist_next.background_trial --db runs/w1-l2-live.sqlite --run-id YOUR_RUN_ID --view-id YOUR_SAVED_VIEW_ID --config /private/tmp/reading-model.json --credential-env CO_SCIENTIST_READING_KEY --execute-real-call
```

仅做一次P04，不自动综合或生成；seed视图另传seed-id。密钥不进公开配置/Prompt/M15/Git/日志；回显脱敏、异常信息去凭据。
实际HTTP body/模型配置/Prompt版本/完整消息/原始响应、解析错误与可得用量持久保存。成本未知为null，未用量不填0。

### 实际验证

环境macOS / Python3.11.4，复用已有环境；无新生产依赖，支持兼容conda，不强制.venv。
浏览器使用临时工具Playwright1.64.0与Chromium1248。

| 检查 | 实际结果 |
|---|---|
| `PYTHONPATH=src python -m pytest -q -s tests/next` | 176 passed，0 failed，0 skipped（原142 + 新34） |
| 输入/材料/seed隔离 | Run/Goal/来源/视图/seed/packet绑定、原文与转述分离、负结果/限制、开放四字段、评审字段隔离、P03范围继承通过 |
| 供应商模拟HTTP | 实际请求格式/响应/usage、非stop完成、HTTP302/429/503不重试、凭据回显脱敏/异常脱敏、未配置/未授权无回退均通过；不是实际供应商成功 |
| readiness | 三分支、假设未知可保留、未准备seed不阻挡其他ready、重复检查无进展停止、技术问题无科学决定通过 |
| M15/跨进程 | 真正os._exit于P04成功响应保存后、结果应用前退出；另一PID只回放，fixture发送仍1；重复应用/不确定授权谱系及响应保存失败反例通过 |
| 本地HTTP/页面 | HTTP服务子进程重启后背景/seed事实不变；实际浏览器14动作/13替身Attempt/3条解读，刷新POST=0、固定Brief与L1材料不变、无JS错误、390px无溢出 |
| Ruff / JS | check与33文件format通过；两份前端JS语法检查及Prettier通过 |
| Wheel | 构建与隔离运行通过；4份页面资源、真实客户端导入和离线P04–P07持久链可用，无真实发送 |
| 原工作区/原件 | 用户232项指纹不变；未改M00/W0/W1原件；新编文件空白检查通过 |

[tests.txt](verification/w1-l2/tests.txt)、[浏览器报告](verification/w1-l2/browser.json)、
[完整开发执行证据gzip](verification/w1-l2/development-execution.json.gz)、[页面](verification/w1-l2/workspace.png)、
[解读](verification/w1-l2/saved-reading.png)、[seed](verification/w1-l2/seeds.png)、[刷新](verification/w1-l2/after-refresh.png)、[移动](verification/w1-l2/mobile-seeds.png)。
初期浏览器脚本CSP等待/隐藏控件选择问题已修正并重跑，诊断数据库保留；没有放松CSP。
本轮P03执行接入用响应夹具验证，页面只保存未执行计划；未新增真实公共文献请求，未执行真实模型调用。

### 未实现、未运行与待审阅

未实现P08、Candidate Ethics、R0及后续模块；无候选、排名或科研完成。未建无人值守循环、全自动分块综合或知识图谱服务。
真实供应商兼容性/权限/计费/模型输出质量尚未试跑；工程引用检查不能证明引文支持、正确情境理解或seed科学价值。
真实模型上下文限制由显式技术配置和供应商错误处理，不把字节限制当token保证。
**未运行：** 真实模型/付费试跑、真实阅读表现/专家科学审阅、科学有效性与开放/定向策略评测、完整W1-L或S01–S14、湿实验、旧G3全套本地测试、Python3.12本地回归。
待专家审阅：转述准确性/负结果与情境保留、中性综合遗漏/偏向、seed是否问题、readiness具体程度是否合理。
无新增需总控修改M00规则的跨模块冲突；后续真实试跑与科学验收需另行授权。

---

## W1-L1历史交付（以下按当时状态保留）

## 当前交付（2026-11-03，Asia/Shanghai）

实际fetch核实main：`47a8a09b7730bd869843e4fc236e9a2f9f1d061f`，与用户参考一致，PR #5已合并。
本轮独立分支 `codex/w1-l1-literature`，checkout `/private/tmp/co-scientist-w1-l1`，独立PR不合并。
最终head以该PR及 `git rev-parse HEAD` 为准。原工作区232项用户改动、暂存区与status指纹未变。

M00仍Accepted；W0/W1原件保持Proposed，W0-T4已接受修订不变。**本轮只交付W1-L1，不是完整W1-L或科学验收。**

| 维度 | 实际状态 |
|---|---|
| 真实检索 | Europe PMC官方公共REST已接入；用户/开发者人工查询，未实现Agent规划；空结果/技术失败/部分完成/未穷尽分页分开 |
| 实际材料获取 | core元数据/摘要、OA PMCID全文XML已实现并实测；保存实际字节、文本、定位和访问限制；图像/补充未获取 |
| M12接入 | 已保存的completed Goal Ethics pass才可追加search/fetch任务；复核政策/Goal身份；固定Goal与旧查询不覆盖 |
| 页面接入 | 人工查询、显式翻页、来源列表、摘要/全文、数量/游标/错误/真实历史可读；伦理结果改为易读状态和理由，原JSON折叠；刷新只读 |
| 模型阅读 | 未实现，全部材料标“已获取、尚未解读”；没有背景发现或主张支持判定 |
| 科学能力 | `science_validated=false`；Goal筛查仍确定性开发测试，真实公共文献获取不构成真实伦理审查/生产科学链 |

实现：新增 `europe_pmc.py` / `literature_runtime.py`，沿用LiteraturePort；Store只增加小型动作索引表，
M12只增加两命名操作条件接入；workspace增加显式API/开关，页面同步接入。未连接旧G3。
每次HTTP经M15，保存实际请求、原始响应/错误、时间、调用关系和未知用量；无隐藏重试/跳转。
成功响应可回放；重复request_id不重复执行；不确定发送需显式核实，不能宣称外部exactly-once。

操作/官方依据/范围/来源证据见 [W1_L1_LITERATURE.md](W1_L1_LITERATURE.md)。
选择Europe PMC是因为同一官方公共来源提供检索、core摘要和OA全文XML，无需模型或付费凭据。
用户明确输入查询，不实现P03查询规划、P04模型阅读或后续科学方法。

```sh
cd /private/tmp/co-scientist-w1-l1
PYTHONPATH=src python -m co_scientist_next.workspace --db runs/w1-l1-live.sqlite --port 8785 --development-test --public-literature
```

当前可操作页面 `http://127.0.0.1:8785/`；主验收固定Run：
`http://127.0.0.1:8785/#run=9b5abf8a5ccd496d8c45ff9a6666b20e`。
必须分别显式启用测试Goal适配器与公共文献请求；示例政策不自动成为生产政策。

### 真实请求与页面证据

已有ALS-GOAL开发者转述保留原问题/磷酸化条件；人工宽查询：
`"amyotrophic lateral sclerosis" AND (nucleoporin OR "nuclear pore")`。
未预选具体分子；查询只是宽概念入口，不声称覆盖Goal全部条件或穷尽文献。

- 主验收5次显式动作、6次真实HTTP：第一页面5条/报告1781、返回预印本PPR1217875摘要2746字符、
  返回MED42437963对应PMC13357693全文XML（展平113989字符）、第二页5条仍未穷尽、工程不存在ID查询成功0条。
- 全文文献是review；没有认定为独立实验证据。预印本未认定同行评议或与正式版独立。
  实际来源/许可/定位及原字节均保存；DOI不同不推断独立性。
- 初期另4次诊断HTTP保留失败：2次EXT_ID身份lookup空记录、1次article单对象响应解析未匹配，及其首次查询。
  修正为官方article身份接口/单对象解析。失败未删除，不改成“没有证据”；合计10次发送都有M15 Attempt。
- 浏览器通过页面创建/保存/执行，查看摘要/全文后刷新：POST新增0，历史完全一致，无JS错误；390px无横向溢出。

[浏览器报告](verification/w1-l1/browser.json)、[固定Run](verification/w1-l1/run-snapshot.json)、
[真实请求及材料gzip](verification/w1-l1/public-acquisition.json.gz)、[初期诊断](verification/w1-l1/diagnostic-acquisition.json.gz)、
[页面](verification/w1-l1/workspace.png)、[刷新](verification/w1-l1/after-refresh.png)、[移动](verification/w1-l1/mobile.png)。
原始响应SHA-256可离线复核。记录不是夹具，取得不代表模型已经阅读或评价。

### 实际检查

macOS / Python3.11.4，复用现有Python环境，无新生产依赖；兼容conda，不强制.venv。
浏览器验收使用临时目录Playwright1.64.0和Chromium1248。

| 检查 | 结果 |
|---|---|
| `PYTHONPATH=src python -m pytest -q -s tests/next` | 142 passed，0 failed，0 skipped（原109 + 新33工程/获取检查） |
| 离线响应夹具 | 明确虚构标识；空结果、HTTP失败、部分行、分页、重复结果、各访问层级、错源/空正文/abstract-only/截断、幂等/非pass阻断均通过；不冒充真实接入 |
| 跨进程恢复 | 实际os._exit于成功HTTP保存后中断，新进程通过保存响应回放，Attempt仍1，不重新发送；原恢复测试回归通过 |
| HTTP持久化/重启 | 真实loopback子进程服务+虚构响应夹具；POST幂等、GET不重发、重启读取通过 |
| 真实公共接入 | 上述6次主验收+4次诊断M15发送，摘要/开放全文路径确已完成；没有付费模型 |
| Ruff check / format | 通过；26个Python文件格式检查通过 |
| JavaScript | node --check通过；Prettier格式化 |
| Wheel | 构建通过；隔离从wheel加载页面资源、固定Goal门及离线获取持久化通过 |
| 原件/工作区 | 未改原M00/W0/W1设计文件；用户232项改动指纹不变；新编文件空白检查通过 |

测试输出：[tests.txt](verification/w1-l1/tests.txt)。网络错误和初期解析失败保留在诊断证据，不能靠夹具通过替代真实请求。

### 已知限制、未运行及后续边界

尚未实现：自动查询生成、真实Goal模型适配器/伦理分类准确性、模型阅读、知识图谱、seed readiness、候选生成、
M03–M11科学逻辑、图像/补充获取、研究独立性/主张支持判定、全面文献覆盖；仅单进程loopback页，无远程多用户认证。
源端结果会变化，1781只是当时provider报告；已保存材料不能等同全文全部附件或科学证据已验证。

**未运行：** 付费模型/真实模型阅读、专家科学评测、完整W1-L与S01–S14科学流程、湿实验、旧G3全套本地测试、Python3.12本地回归。
没有新增需要总控裁决的跨模块冲突。进一步科学能力需要另行授权与验收。

---

## W0-T4历史交付（以下按当时状态保留）

## 当前交付（2026-11-03）

PR #4 固定 head `c6f7e0949f9353bfcd9ea1d8be28daef273f8292` 复核未变，4项CI成功，
无新增阻断、状态检查或冲突；按该SHA约束合并。合并 commit / 本轮实际起始 main：
`aa2cc7fe0a2b12398ba71d8dcc0c75a0c230a004`。本地 main 已更新。
独立分支 `codex/w0-t4-goal-workspace`，checkout `/private/tmp/co-scientist-w0-t4`。
本轮新PR不合并；最终head以该PR及 `git rev-parse HEAD` 为准。
原工作区仍在原分支/HEAD，232项用户改动、暂存区与status指纹保持一致。

| 维度 | 本轮实际状态 |
|---|---|
| 后端 | M01 prepare_goal、M02 screen_goal最小契约/输入保留/持久化实现；确定性开发适配器；真实供应商尚未接入 |
| M12 | 两命名操作的条件推进已接入；只有completed pass进入awaiting_background，未创建背景或Generation任务 |
| 页面 | 创建/保存Brief、固定Run、显式执行、结果与澄清展示、刷新读取SQLite已接入 |
| 科学验证 | `science_validated=false`；自然语言抽取、关键歧义判断、伦理分类准确性和真实模型表现未验证 |

W1原7文件逐字节保存于 `design/w1-method-v0.4-proposed/`，保持Proposed；
原ZIP及V5参考哈希见 `design/w1-v04-source-integrity.json`。
V5只参考布局/视觉，不导入其内置案例或假候选。M00 Accepted、旧W0/真实案例原件及旧G3保持原状。
用户已接受修订单列 [W0_T4_DECISIONS.md](W0_T4_DECISIONS.md)：P08六字段一致的采用示例、
DIRECT/ASSUMPTION_STRUCTURED单次方式、R0明确事实错误政策（未实施）、Goal Ethics完成决定仅pass/reject。
Candidate Ethics不改；W1整包不转Accepted。

实现文件：`goal.py`、`workspace.py`、`frontend/*`；Store新增Goal/Run配置表与原子结果应用，
Scheduler增加当前两操作的条件分支；pyproject打包页面资源。另有两组Goal/HTTP测试、浏览器脚本、
源文件完整性记录、采用示例、决策/操作文档及实际验证记录。新运行链不依赖旧Orchestrator。

启动（兼容现有Python/conda，不强制新环境，无新生产依赖）：

```sh
PYTHONPATH=src python -m co_scientist_next.workspace --db runs/goal-workspace.sqlite --port 8784 --development-test
```

交付时已启动页面 http://127.0.0.1:8784/ ，实际数据库 `runs/w0-t4-live.sqlite`。
显式开发模式和政策示例需主动启用；不带开发参数不会连接真实模型或加载默认政策。
操作/适配边界详见 [W0_T4_WORKSPACE.md](W0_T4_WORKSPACE.md)。

### 本轮实际检查

环境：macOS、Python3.11.4，使用已有 `/Users/lemintea/Documents/co-scientist/.venv/bin/python`；
Playwright1.64.0仅装入临时工具目录，实际Chromium1248，未添加生产浏览器依赖。

| 检查 | 结果 |
|---|---|
| `PYTHONPATH=src python -m pytest -q -s tests/next` | 109 passed，0 failed，0 skipped；含原80项回归和29项新增工程检查 |
| 跨进程恢复 | 实际os._exit中断于prepare成功调用保存后；不同PID恢复，prepare发送1次、screen1次；另含原恢复/不确定发送回归 |
| HTTP持久化/恢复 | 子进程服务重启可读原Run；未完成运行GET/启动不执行，显式POST才恢复，保存成功调用不重发 |
| 浏览器真实页面操作 | pass/reject/澄清/风险信息缺失/无效输出/技术失败/缺政策；刷新新增POST为0，草稿更新不改固定Run，无页面JS错误 |
| 布局 | 桌面和390px移动截图；移动无横向溢出 |
| Ruff check / format | 通过；22个Python文件格式通过 |
| JavaScript语法 | node --check通过 |
| 原附件一致性 | ZIP SHA与7文件逐字节比对通过；V5参考SHA匹配 |
| Wheel | 构建成功；隔离从wheel加载3页面资源并完成开发Goal切片 |
| 空白检查 | 新编文件通过；原附件Markdown原有行尾空格原样保留 |

测试输出：[w0-t4-tests.txt](verification/w0-t4-tests.txt)；
页面报告：[w0-t4-browser.json](verification/w0-t4-browser.json)，
[桌面](verification/w0-t4-workspace.png)、[固定Run](verification/w0-t4-fixed-run-after-edit.png)、
[移动](verification/w0-t4-mobile.png)。HTTP最初受沙箱禁止绑定loopback，授权本地主机端口后实际重跑通过。

### 剩余能力和限制

没有真实API/付费模型调用；真实适配器、生产安全政策、背景调研、Generation、Candidate Ethics、R0、
M03–M11科学实现均未接入。工程替身只复制结构化条件/返回固定情景，不能证明科研或伦理能力。
缺信息/政策、无效输入输出、技术失败为执行状态，不是第三种完成伦理决定；科学未知不自动拒绝。
原问题保守原样保存，真实自然语言条件分类和关键歧义有效性待真实适配器及专家确认。
仅单进程loopback页面，无远程/多用户认证；刷新不自动恢复。不确定外部发送需明确核实/授权，
不承诺外部exactly-once。缺政策/澄清等已停止Run需要以修订输入/政策创建新Run。

**未运行：** 真实模型能力/伦理分类科学评测、专家盲评、湿实验、完整S01–S14科学流程、
旧G3全套本地测试、Python3.12本地回归。无新增需要总控裁决的跨模块冲突；
生产政策和科学有效性仍须另行审批/评测。

---

## W0-T3历史交付（以下按当时状态保留）

更新：2026-11-02，Asia/Shanghai。本轮为公开真实开发案例采用、来源核对和 M01/M02 实施提案，
**没有实施 M01/M02 生产科学逻辑，没有执行科学模型评测或付费候选生成。**

## 起点、分支与设计状态

- 实际 fetch 后最新 main / 起始 commit：`e98404cda9ec35a82a1c363c14e315f54e240d96`。
  PR #3 已合并；W0-T0/T1、W0-T2 的代码及验收历史保留。
- 分支 `codex/w0-t3-real-cases`，工作目录 `/private/tmp/co-scientist-w0-t3`；独立 PR，本轮不合并。
  最终 head 以 PR head 和该分支 `git rev-parse HEAD` 为准。
- 原工作区仍在 `codex/preserve-local-before-w0-t2`，旧 HEAD 为
  `c2ddbda03f84d5a52f46b47d942b2cce710c919b`；未 reset/stash/覆盖用户文件。
- M00 仍是 Accepted；W0 最小设计、真实案例包、本轮采用说明和 M01/M02 提案均保持 Proposed。
  `reference/` 仍为历史材料；旧 G3 固定参考 `7313ca032e4f5f0c84578523e0f5639ad038e7af` 未删除。

## 附件与采用材料

用户给定 Downloads ZIP 路径已不存在；在项目文档目录找到唯一同名副本：
`/Users/lemintea/project/project/co-scientist/M0-M20开发文档/CoScientist_W0_Real_Cases_v0.1_PROPOSED.zip`。
实际 ZIP SHA-256 为 `8c4f695826657e45ed7b6feb8fba2a76862c73f2995d8cc8b5b421e2b47b6075`。

两个原文件原样保存至 `docs/design/w0-real-cases-proposed-v0.1/`。
其中“来源核对完成”和 R06 “独立研究”的原有文字保留，但不作为本轮已验证结论。
采用已有 ALS、AML/KIRA6 和 R01–R06，未新建另一套完整疾病案例。

`evaluation/w0_real_cases/` 的审计、材料短转述和输入选择是采用层，不改原包：
区分报告观察、作者模型输出、作者解释、开发重建和项目路由预期。
ALS 原始 Goal 的来源定位/转述、加入 iPSC 情境的开发 Brief、公开示例 Hypothesis 分开。
R01 的机制覆盖只评价给定假说拆解，不要求自由生成复述同一分子机制。

## 实际核对来源及限制

| 来源 | 本轮实际取得/核对 | 未验证部分 |
|---|---|---|
| P-01 arXiv 2502.18864v1 | 版本、标题、摘要、2025-02-26提交历史 | 各具体结果首次公开位置、预训练泄漏均未独立审计 |
| P-02 Nature DOI 10.1038/s41586-026-10644-y | 主文 HTML 的 AML/Fig.3图注与数值正文、肝纤维化段、ALS警告、引用/作者关系 | 原图独立数字化、全方法与原始数据重分析未做 |
| P-03 120页补充PDF | 所列 Note10.1/10.2/10.5/10.6、5.2、6 的具体段落与实体页码 | 部分截图cache miss；非整份内容或模型Trace的完整复核 |
| P-04 KIT研究 | Europe PMC MED30931942 官方身份/摘要；另有索引片段 | publisher重定向及PMC CAPTCHA；未核对全文方法/图 |
| P-05 选择性研究 | PubMed/Europe PMC MED33290055摘要与 DOI 10.1021/acschembio.0c00802 | 原包ScienceDirect URL 403且身份待核，ACS页面403；全文未核对 |
| P-06 HSP60研究 | Europe PMC MED34453119 官方身份/摘要与 DOI | 直接页面访问受限；全文方法及AML情境适用性未核验 |
| P-07 肝纤维化配套论文 | PMC全文HTML选定段落、作者/贡献、数据声明与计数口径 | 原始图像、样本/批次及GEO/Zenodo数据未下载对齐 |

位置、URL、访问限制、官方摘要响应哈希和研究关系详见
[来源/案例说明](W0_REAL_CASES.md)及 `evaluation/w0_real_cases/source_audit.json`。
P-08/P-09 本轮未使用、未核对。未进行当前FDA批准或临床注册库的全面搜索；
Note6有关药物安全/新颖性的模型输出不能作为当前监管或全球新颖性事实。

R06 配套论文与主文存在引用、作者及项目关联，不能默认计为独立复现；
精确样本/批次重叠仍待核实。三类推荐靶点、五种抑制剂与25药物池不混为同一分母。

## 交付范围与未实施能力

- 新增原附件两文件及完整性记录。
- 新增 `evaluation/w0_real_cases/{source_audit,materials,adoption}.json`。
- 新增 `src/co_scientist_next/development_cases.py`：仅固定数据读取、白名单导出、引用/访问一致性检查。
  `expected`、`critical_failures`、评审及评分记录有独立审阅路径，不进入导出的被测输入。
- 新增 `tests/next/test_development_cases.py` 和 `docs/verification/w0-t3.txt`。
- 新增 [W0_REAL_CASES.md](W0_REAL_CASES.md) 与 [M01_M02_PROPOSAL.md](M01_M02_PROPOSAL.md)。
  更新本STATUS、AGENTS和设计目录说明；既有 M12/M15生产实现与全部原基线未改。
- 固定模式实际可见材料是短转述，非全文。R03当前视图仅读作者评议，R05当前视图仅解释给定数值，
  不能声称已实现原任务的独立新颖性检索或原图提取。
- 开放模式只导出题目与搜索起点，不执行检索。两模式分开记录，所有材料均为公开开发集，非盲测/独立发现。
- 没有 M01/M02科学函数、完整科学Schema、M03–M09实现、检索策略、通用评测平台或新服务。

## 实际执行检查

本地 macOS / Python3.11.4，使用现有 `/Users/lemintea/Documents/co-scientist/.venv/bin/python`
运行 pytest/Ruff/build；导出也用系统 python3 成功。无新生产依赖或环境安装，不强制 .venv，允许兼容 conda。

```sh
PYTHONPATH=src python -m co_scientist_next.development_cases --case ALS-GOAL --mode fixed_materials
PYTHONPATH=src python -m co_scientist_next.development_cases --case R04 --mode fixed_materials
PYTHONPATH=src python -m co_scientist_next.development_cases --case R04 --mode open_retrieval
PYTHONPATH=src python -m pytest -q tests/next/test_development_cases.py
PYTHONPATH=src python -m pytest -q tests/next
python -m ruff check src/co_scientist_next tests/next
python -m ruff format --check src/co_scientist_next tests/next
```

| 检查 | 实际结果 |
|---|---|
| 新增数据读取/隔离/引用检查 | 28 passed，0 failed，0 skipped |
| 全部新系统工程/契约回归 | 80 passed，0 failed，0 skipped（原52 + 新28）；不是80项科学评测 |
| Ruff check/format | 通过；17个Python文件格式检查通过 |
| 实际附件ZIP比对 | ZIP哈希匹配，两个文件逐字节一致 |
| 原M00/W0文件完整性 | 既有完整性检查通过，原文状态未改 |
| 模型可见视图 | 8个输入视图×2种模式检查；无评审字段，固定/开放模式明确分离 |
| Wheel构建与隔离运行 | 构建通过；python -I仅从wheel导入数据CLI，显式--root指向案例checkout，成功导出R05 |
| Git空白检查 | 新编文件 staged检查通过；全量检查仅报告原附件Markdown四处行尾空格，按原样保留 |
| 原工作区保护 | 232个相关文件、差异、暂存区和status指纹与此前保护记录一致 |

输出见 [verification/w0-t3.txt](verification/w0-t3.txt)。外部来源访问是本轮人工核对行为，
不是应用已通过 LiteraturePort/M15 完成真实来源摄入的证明。

**未运行：** 真实M01/M02输出、付费模型、科学评分/通过率、真实开放检索评测、专家盲评、湿实验、
当前药物监管库核验、完整科学S01–S14/R01–R06执行、旧G3全套本地测试、浏览器、Python3.12本地测试。

## 待审阅及下一项编码任务

全部科学预期仍为 provisional，未有专家签名、独立共识或统计阈值。
待审阅：来源转述准确性与条件归属、给定假说Coverage、KIRA6靶点因果及新颖性边界、
材料访问限制、R06计数/数据关系、Goal/Candidate Ethics与R0的边界及适用安全政策。

提案已给出方法/Prompt草案、最小I/O、真实来源/模型接入M15所需记录及M12合法顺序。
现有固定序列 Scheduler 尚无 Ethics条件门，不能仅注册函数就宣称拒绝时不会生成候选。
建议下一项为 W0-T4：固定材料下 prepare_goal + Goal Ethics + 最小M12条件推进切片；
先保证 pass/reject/incomplete/技术失败和日志/恢复语义，Generation先保留未实施的显式后继边界，
不以替身候选冒充科学能力。具体验收条件见提案；仍需单独审查与授权，不在本轮自动启动。
