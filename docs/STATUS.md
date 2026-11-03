# 项目状态 — W1-L1

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
