# W0-T3：采用真实公开开发案例

状态：**Proposed / evaluation preparation only**。本轮没有运行科研模型、独立专家评审、湿实验或科学评分。
使用已有 ALS、AML/KIRA6 和 R01–R06，不另建完整疾病案例，也不改变 M00 Accepted 科学规则。
原包中“来源核对完成”是历史作者状态，**不是本轮事实核对的结论**。

## 原包与本轮采用层

用户所列 Downloads 路径当前不存在；实际使用的唯一同名副本位于
`/Users/lemintea/project/project/co-scientist/M0-M20开发文档/CoScientist_W0_Real_Cases_v0.1_PROPOSED.zip`。
ZIP SHA-256：`8c4f695826657e45ed7b6feb8fba2a76862c73f2995d8cc8b5b421e2b47b6075`。
两个原文件逐字节保存在 `docs/design/w0-real-cases-proposed-v0.1/`，原有 Proposed 状态、错误、待核实声明均不重写。
原件与采用层的文件哈希见 `docs/design/w0-real-cases-source-integrity.json`。

`evaluation/w0_real_cases/` 仅是该包的采用说明，不是另一套疾病数据集：

- `source_audit.json`：本轮实际访问、位置、限制、研究关系和未核实项。
- `materials.json`：首批固定阅读材料的短转述；不是论文全文或作者逐字输出。
- `adoption.json`：直接引用原 R01–R06，列出被测可见字段和审阅侧说明；ALS 另有两个明确的输入视图。

必须区分以下来源性质，不能因为内容出现在正式论文中就把它当实验真值：

| 标签 | 含义与实际例子 |
|---|---|
| reported_observation | 论文报告的实验观察，例如主文 Fig.3 的细胞剂量反应；仍须考虑实验局限 |
| author_model_output | 作者模型生成或评议示例，例如 Note10.2 假说、Note6 新颖性评议；不是项目专家金标准 |
| author_interpretation | 作者对观察的解释，例如 Note5.2 细胞差异解释；不能单靠叙述视为靶点定因 |
| developer_reconstruction / developer_paraphrase | 中文 Brief、公开文本转述、R02 人为遗漏；不是作者完整原始 Trace |
| project_route_expectation | R1/R3 路由、Admission 前置等 M00 规则；放在审阅侧，不冒充论文发现 |

## 2026-11-02 实际核对的首批来源

全部只核对列明位置，不声称整篇论文或原始实验数据已完整复核。

| 来源 | 实际取得与核对位置 | 边界与待核实 |
|---|---|---|
| [P-01 arXiv v1](https://arxiv.org/abs/2502.18864v1) | 标题、摘要、提交历史：2025-02-26；未带版本 URL 已指向 v2 | 未逐项核对 v1 每个结果首次公开的日期；不能仅靠日期排除训练泄漏 |
| [P-02 Nature 主文](https://www.nature.com/articles/s41586-026-10644-y) | HTML：AML 段、Fig.3d–h 图注和数值正文；肝纤维化段；Methods 的 ALS 示意性警告；作者与参考文献1 | 未独立数字化曲线图像、复算实验或审查全部方法。数值报告与机制/临床解释分开 |
| [P-03 Supplement](https://static-content.springer.com/esm/art%3A10.1038%2Fs41586-026-10644-y/MediaObjects/41586_2026_10644_MOESM1_ESM.pdf) | 120页 PDF 文本。Note10.1 实体p70；10.2 pp70–72；10.5 pp74–75；10.6 p76起；5.2 pp26–27；Note6 pp39–50，安全性示例p44、新颖性评议pp49–50 | 位置按 PDF 第一个页面为1计数。部分截图请求 cache miss，未据此声称图像复核成功；仅核对所列段落 |
| [P-04 KIT DOI](https://doi.org/10.1038/s41419-019-1523-3) / [Europe PMC 摘要](https://europepmc.org/article/MED/30931942) | 官方 MED 30931942 core 接口取得身份与摘要，另见 PMC 索引片段 | Nature 重定向失败、PMC CAPTCHA；本轮**未核对全文方法和图**。其 KIT 依赖细胞结果不直接证明本 AML 实验的因果 |
| [P-05 选择性摘要](https://pubmed.ncbi.nlm.nih.gov/33290055/) | PubMed 与官方 Europe PMC MED 33290055 摘要，核对 DOI 10.1021/acschembio.0c00802 | 原包 ScienceDirect URL 403，身份仍待核实；ACS 页面也403。不沿用原 URL 为已证实匹配，不声称掌握全文靶点清单 |
| [P-06 HSP60 摘要](https://europepmc.org/article/MED/34453119) | 官方 Europe PMC MED 34453119 core 接口身份/摘要，DOI 10.1038/s41418-021-00853-5 | PMC/PubMed 页面 initially CAPTCHA，publisher 重定向失败；未核对全文方法。其研究情境不等同 AML 活力测定 |
| [P-07 肝纤维化配套论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC12667525/) | HTML Abstract、Results2.1/2.2、作者/贡献、数据声明 | 原始图像、样本批次、GEO/Zenodo 与补充实验未重分析。P-08/P-09 本轮未用、未核对 |

Europe PMC 的实际请求 URL 和返回字节 SHA-256 记录在审计 JSON；查询在本轮人工来源核对中执行，
不是新系统 LiteraturePort 已实现或 M15 已接入真实检索的证明。固定模型输入只有材料短转述。

## ALS：原始 Goal、开发 Brief、公开假说分开

| 视图 | 实际被测输入 | 用途与不能混用的条件 |
|---|---|---|
| ALS-GOAL | Note10.1 原始 Goal 的中文转述，附原文定位；全文原始 Goal 仍在 PDF p70，不伪称本地转述是逐字 Trace | 保留 ALS、核孔蛋白磷酸化、新关键因素/过程假说、详细机制和可行实验；原 Goal **没有指定** iPSC 运动神经元 |
| ALS-BRIEF | 同一 ALS 案例的开发重建 Brief，明确加入 iPSC 来源运动神经元 | 这一条件来自 Note10.2 公开实验示例的开发采用，不追写为 Note10.1 原始约束 |
| R01 | 原 JSONL 的 brief_cn 与 hypothesis_summary_cn，另给 Note10.2 的短转述 | **给定假说拆解**，不是自由生成任务。Nup98/Nup62–TDP-43–运输桥接只用于拆解该候选，不是其他候选必须命中的标准答案 |

两种自由生成视图均不包含 R01 假说、R01 expected、原作者评议或具体 Nup98/Nup62/TDP-43 材料。
提出不同且符合 Goal 的可检验机制可以是合格开发输出，不能以“未复述公开机制”直接判失败。
ALS 公开假说仅为作者模型示例，主文 Methods 也提示其示意性和可能错误；不是科学实验证实。

R02 的 Inventory 遗漏由开发者注入；原字符串 `same fixed DEV-01` 在采用层解析成原 R01 给定假说转述。
普通遗漏是否走 R1 由项目 M00 路由标准评价，不把它写成作者原系统发生过的失败事件。

## 实际可见输入与隔离

`development_cases.model_payload` 是数据导出函数，不调用模型、不运行检索、不评分。
它只输出 task、允许的 input 字段、输入来源类型、所选材料或搜索起点、公开开发集标识。
`expected`、`critical_failures`、assessment、evaluation_reviewers、科学金标准状态及采用层 review_only
不会进入该 JSON；`reviewer_record` 是单独的本地审阅路径，禁止传给被测模型。
**禁止将整份 casebook/原 JSONL、源审计审阅结论或本文评审规则作为被测模型附件。**

| R条目 | 允许 input 字段 | 固定材料 ID（完整文本以实际导出为准） |
|---|---|---|
| R01 | brief_cn、hypothesis_summary_cn | ALS-HYP |
| R02 | hypothesis（已解析）、injected_gap、gap_provenance | ALS-HYP |
| R03 | question_cn | AML-NOVELTY |
| R04 | question_cn | AML-HYP、AML-DOSE、KIT-ABSTRACT、SELECTIVITY-ABSTRACT、HSP60-ABSTRACT |
| R05 | question_cn | AML-DOSE、AML-CONTEXT |
| R06 | question_cn | LIVER-SUMMARY、LIVER-COMPANION |

每份材料带 `claim_kind`、来源 URL、段落/页码、实际来源访问层级与 `representation`。
来源曾取得 PDF/HTML 全文不等于被测模型读了全文：本轮固定模式只读短转述，不能要求其引用未给的方法细节。
原文/摘要内容本身可能含作者答案，这是公开阅读任务的属性，不是盲测。允许文本中的人工错误、编辑者藏入答案、
模型预训练记忆不能由字段白名单自动消除；本轮检查只证明导出的结构和选取规则。

## 固定阅读与开放检索分开评价

- **fixed_materials**：只用导出给定材料，网络/检索权限应关闭；评价信息保留、材料准确引用、观察/解释及不确定性。
  材料只到摘要或转述时，合理指出无法核对细节应记录为材料限制，不直接判检索能力失败。
- **open_retrieval**：导出不含材料文本，只保留题目与来源起点（ALS自由生成无种子）；真实检索尚未执行。
  后续另外评价查询、支持/反证覆盖、分页、获取失败和资料访问层级，保存时间与实际材料；不可把这种结果混记为固定阅读。
- 两种模式均公开 development、retrospective、非盲；不给出独立发现指标。即使模型没在本轮检索到某答案，也不能排除预训练泄漏。
  本轮没有模型答案、评分或通过率；R01–R06 的科学 expected 全部 provisional，原包的 source_fact_is_gold 字段不构成专家真值。

## 可导出不等于原任务已具备完整科学执行条件

| 条目 | 当前固定视图与尚缺材料 |
|---|---|
| R01 | 可阅读给定假说短转述；真实机制拆解与专家Coverage确认未执行 |
| R02 | 可阅读人为遗漏；M03–M08及M12科学路由未实现，不能声称原作者失败已复现 |
| R03 | 当前只读作者模型的新颖性评议，不是独立 prior-art 检索；原始既有研究与当前监管状态仍需另核 |
| R04 | 仅摘要及机制/表型短转述，全文方法、靶点参与和AML因果归因未验证 |
| R05 | 当前给出数值转述供解释，不测试从 Fig.3 原图抽取；原图/原文切片需后续纳入实际模型输入后才能验证原阅读任务 |
| R06 | 配套报道转述可供限定性阅读；原始数据/批次独立性、计数口径与专家解释仍待审阅 |

采用层 R03/R05 的实际 task 已注明上述限制，原包任务文本不重写。不得把转述阅读结果报告成原任务全部通过。

## R06：配套实验不是默认独立复现

P-02 参考文献1引用 P-07，作者重叠，P-07 Results2.2 说明其 Co-Scientist 推荐与实验跟进。
因此原 R06 的 `independent_primary_study` 历史标签保留在原件，但采用层改记为 related companion reports，
**不按两篇论文计两次独立有效性复现**。GSE228214、GSE306096 和 Zenodo 14996331 仅核对到数据声明，
未下载对齐；具体样本、批次和原始数据重叠仍待核实，不能反向断言所有数据完全相同。

主文的三项推荐概述、配套论文的三类 AI 靶点/五种抑制剂和25药物分析池不是同一计数单位；
不能把“2/3”直接套在五种抑制剂或整个药物池上。类器官、靶点机制与临床获益仍分层评价。
P-05/P-06 也存在研究者重叠；本轮未审计探针/数据谱系，独立 DOI 不自动等于独立证据单位。

## 运行与待专家审阅

```sh
PYTHONPATH=src python -m co_scientist_next.development_cases --case ALS-GOAL --mode fixed_materials
PYTHONPATH=src python -m co_scientist_next.development_cases --case R04 --mode fixed_materials
PYTHONPATH=src python -m co_scientist_next.development_cases --case R04 --mode open_retrieval
PYTHONPATH=src python -m pytest -q tests/next/test_development_cases.py
```

无模型密钥或新生产依赖。评审者须复核材料转述、ALS条件归属、R01必要桥接的完整性、
KIRA6 因果归因和“新颖/获批”表述的时间/证据范围、R06计数与数据关系，以及 Ethics/R0 科学责任边界。
当前没有专家签名或共识。下一项编码提案见 [M01/M02 提案](M01_M02_PROPOSAL.md)。
