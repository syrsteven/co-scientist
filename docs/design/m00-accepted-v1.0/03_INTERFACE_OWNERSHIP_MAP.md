# 03｜Interface & Ownership Map（跨模块最小接口）

**状态：** 用户已定科学边界 + Phase 3 推荐的轻量交接协议；`M00-IFACE-v1.0`，设计已验收（2026-11-01）；模块实现未验收。  
**强约束：** 不将接口名、样例字段和伪函数签名当成必须采用的 Pydantic Schema、服务边界或论文原文。

## 1. 科学权威链与最小引用

```text
ResearchBriefRevision / GoalContext ──> ResearchRun
                                         │
                                         ├─> Hypothesis (immutable scientific content)
                                         │     └─> ClaimInventory (mechanism coverage)
                                         │           └─> EvidenceDossier (scope + findings + appraisal + prior-art)
                                         │                 └─> FinalReflection (R2 synthesis; R3 findings as inputs)
                                         │                       └─> Admission (fixed refs + eligibility decision)
                                         │                             └─> PairwiseMatch (same Run/Epoch and policy)
                                         │                                   └─> TrueSkill Rating projection
                                         ├─> Evolution (qualified parents + feedback)
                                         │     └─> new Hypothesis + DeltaProposal
                                         │           └─> ResolvedDelta (after child Inventory)
                                         └─> TerminalResult (eligible max-mu or explicit no-winner)
```

### 1.1 必须一致的身份语义

- `run_id`：一次科学研究的不可混用身份；目标／评价政策以 Run 为界固定。
- `hypothesis_id`：一个科学内容快照；科学机制、因果假设、条件或预测的修改生成**新候选**，不能覆盖父代。非科学显示属性不要求新候选。
- `claim_id`：在特定 `hypothesis_id + inventory` 内定位主张；主张间语义相似不自动拥有同一权威身份。必要时引用候选原始段落及其角色。
- `dossier_ref`：M06 针对具体候选／Inventory／科学评价政策的输入成果；入场前允许形成新的完成版本，入场后引用不得被重新指向。
- `reflection_ref`：M07 对完整假说作最后一次综合评价的记录；引用实际使用的 Dossier、R0、所有必需 R3（包括其未完成情况）。
- `admission_ref`：一份**轻量引用列表**，绑定以上具体结果和准入判断、当次政策，并在同一 Run/Epoch 注册；不复制 Dossier，不要求另造 `EvaluationBasisService`。
- `match_id`：对固定的两个参赛引用、统一 Ranking 政策与呈现记录的**一次科学比较**。技术 retry 和外部 API attempt 不是自动的新 Match。
- `epoch_id`：同 Run 内一次连续的排名空间。**正常 Run 只有一个**，新候选追加成员；历史科学输入不可原地更换。
- `rating_snapshot`：同 Epoch 按实际生效顺序重放有效决定性 Match 得出的 μ/σ；非决定性和执行失败无评级变更。
- `terminal_ref`：一份完整或不完整的研究终局，引用固定候选和比较资格结果，不重新请求科学核查。

**实现自由：** ID/Hash/版本并非每层都要同时存在；只有需要证明“入场时使用了哪一份不可变内容/策略/调用”时才保留必要稳定引用。M09/M15共同规定可追溯性，不能强迫所有模块单独建三层身份包装。

## 2. 科学对象：唯一所有者、消费者和禁止的侧写

| 对象 | 真正的科学含义／最低交付 | 唯一逻辑所有者 | 消费方 | 禁止行为 |
|---|---|---|---|---|
| **GoalContext / BriefRevision** | 确定研究任务、情境、目标和当前科学评价要求 | M14保存工作区版本；M01组织运行目标；M12固定运行输入 | M01–M12 | 编辑 Draft 改变运行中 Goal |
| **Hypothesis** | 一组完整、确定的科学命题/机制/前提/预测/证伪条件 | M01 根候选；M11 演化子代；M12负责保存已准许的结果 | M02–M13 | R2/R3/Judge修改其科学内容，或子代复用父代身份 |
| **Ethics + R0 Result** | 科学执行是否安全、结构初审与核查重点，分别报告 | M02 | M03/M07/M09/M12 | 把R0的未知当成已有文献证实/证伪 |
| **Claim Inventory** | 科学实质主张、隐含必要前提、依赖与Coverage，真实机制不按固定数量截断；可响应R2普通覆盖补核查 | M03 | M04–M09/M11/M13（可选） | 由检索或演化器擅自增加候选科学内容；把隐含推断装作原文 |
| **Retrieval Result / Material** | 实际查到、取得、未取得、筛选过的资料及访问层级 | M04（共享工具能力被M01/M08复用） | M05/M06/M08 | 检索成功即代表科学支持；把摘要说成全文 |
| **Evidence Finding / Appraisal** | 研究报告的实际结果与该结果对 Claim 的解释、适用性、因果性、偏倚 | M05 | M06/M07/M08/M11 | 将同一研究复制为多项独立证据、给未读方法学的材料打满分 |
| **Evidence Dossier** | Inventory/检索范围/材料/Assessment/Prior-art/冲突缺口的综合可追溯记录；纳入R2普通补核查完成的材料与评价 | M06 | M07/M08/M09/M10/M11/M13（可选） | 自行形成整体Winner或直接更新TrueSkill |
| **Final Reflection** | R2对整条机制的最终评议及限制；吸收初次R1、普通R1补核查和必要R3，给出科学问题与修订建议 | M07（M08只形成R3发现） | M09/M10/M11/M16/M13（可选） | 未完成普通补核查就准入；从R3直达准入；根据Ranking反馈更改已经入场的评议 |
| **Verification Issue / R3 Result** | 针对R2高影响风险的范围明确的核查，完成和科学未知分开 | M08（R2独占触发） | M07/M09/M12 | 最后排名触发；自己改候选；同问题无变化无限派发 |
| **Admission / Fixed References** | 精确绑定所用科学对象和共同政策，决定准入状态 | M09 | M10/M12 | 重新解释科学质量、把无直接证据一概拒绝 |
| **Match / Comparative Feedback** | 固定双方核心科学呈现并按对称策略增补已冻结材料的相对优先级判断和比较理由 | M10 | M11/M12/M16/M20/M13（可选） | 输出执行型 EvidenceRequest、改 Dossier 或改科学候选；在不同Match中静默改变同候选核心呈现 |
| **TrueSkill Rating / UCB** | μσ的确定性比较估计；UCB服务父代探索 | M10 | M11/M12/M16 | LLM自填Rating；非决定性改分；UCB作为正式Winner |
| **DeltaProposal / ResolvedDelta** | 演化修改意图 / Inventory建立后真实父子主张变化 | M11产出提案；M03负责解析结果；M04/M05分别判定复用 | M04–M07/M20/M13（可选） | Delta文字相似=文献评价直接可继承 |
| **Research Run / Terminal** | 固定目标和政策、必要任务、代际计划、统一Epoch和正式/不完整结果 | M12科学协调；M15运行事实/恢复；M14目录关联 | M16–M19/M20 | 旧G3恢复目标；终局后追加科学任务改赢家 |
| **Model/Tool Call Record** | 真实输入、返回、固定核心科学呈现、针对性材料选择与对称策略、实际可见证据、A/B顺序、错误及消耗 | M15保存，M10准备比较输入并声明引用 | M07/M09/M10/M16/M20 | 缺失反证仍声称Judge已经完整看过Dossier；以入场引用代替实际输入记录 |

**R1 的三个不同完成性：** 检索是否在所声明范围执行完成；取得的资料是否完成预定评价；科学判断是否得到了有利证据。三者不可互换。还须区分Coverage是否完整和必要R3是否完成。

## 3. 只冻结跨模块输入与输出，不冻结方法细节

| 调用接口（语义名） | 主要输入 | 必须返回／交付 | 绝不拥有的权限 |
|---|---|---|---|
| `prepare_goal` M01 | BriefRevision、约束与资料 | GoalContext、输入范围 | 不在用户草稿修改时暗改旧Run |
| `screen_goal` M02 | GoalContext | 目标Ethics与原因 | 不生成候选或改计划 |
| `generate_hypotheses` M01 | 通过目标、背景与固定生成配置 | 新候选、内容、生成来源与未知前提 | 不生成Evidence Dossier/排名 |
| `screen_and_review_candidate` M02 | 完整候选 + Goal | Candidate Ethics、R0、核查重点 | 不审查文献事实 |
| `build_inventory` M03 | 候选、R0Focus、可选父代/DeltaProposal | 覆盖所有必要前提的Inventory；子代ResolvedDelta | 不编辑候选科学机制 |
| `retrieve_for_claims` M04 | 主张/核查意图、可复用材料/Issue | 原始/结构化资料、查询记录、访问层级、未取得范围 | 不决定全文科学可信度 |
| `appraise_claim_evidence` M05 | Claim上下文 + 实际材料 + 科学标准 | Observed Finding与Interpretation、因果/偏倚/适用性 | 不直接否定整体假说或写评分 |
| `assemble_dossier` M06 | 完整Inventory、检索/评价/PriorArt | Dossier与未决/未执行范围 | 不跳过M07形成完整结论 |
| `reflect_full` M07 | Hypothesis + Dossier + R0 + R3Results（如有） | R2综合、普通 `R1SupplementRequest`（新必要前提/Coverage/证据缺口）或高影响R3 Issue、Final Reflection/RevisionSuggestion | 不创建新候选；不运行R1工具；不依Ranking比较意见自动启动任何补核查 |
| `verify_issue` M08 | 仅R2派发的高影响Issue，冻结核查范围 | Findings、已执行范围、科学未知与技术未完成区分、关闭原因 | 不直接Admission；不直接改R2结论 |
| `admit` M09 | 最终Reflection + Dossier + Inventory + Ethics与政策 | `AdmissionDecision`及固定参赛引用 | 不设置与M10混合的比赛配额 |
| `compare_pair` M10 | 同Run同Epoch两个已准入引用、双方固定核心科学呈现、统一且对称的增补材料选择政策 | 决定性/非决定性比较、理由、实际输入及材料选择记录 | 不检索、不要求重跑R1/R2/R3、不修改依据或同候选核心输入 |
| `update_ratings` M10 | 按顺序有效决定性Match | μ/σ更新和覆盖统计 | 非决定性/技术错误均不更新 |
| `select_parents` M10 | 已准入且符合父代资格的评分候选 | UCB tournament选择及依据 | 不从未准入池选修复来源 |
| `evolve` M11 | 合格父代、评议、比较反馈及科学限制 | 新候选 + DeltaProposal + 科学修订意图 | 不继承评分，不跳过子代核查 |
| `advance_and_finish` M12 | 持久任务状态、科学交付、比较覆盖 | 下一合法任务或TerminalResult | 不代M05/M07/M10做科学判断 |

**运行时先后：** `M01.prepare_goal → M02.screen_goal → M01.generate_hypotheses → M02.candidate_ethics/R0`；由 M12 协调调用，M01/M02 的实现只依赖共同输入输出接口，不互相导入。**普通科学修复：** R2 发现新的必要前提、Coverage 遗漏或普通证据缺口时，向 M12 提交作用域明确的 `R1SupplementRequest`，由 M03–M06 按实际缺口补核查、形成新 Dossier 后返回 R2；该请求不是 R3 Issue，更不得由 Ranking 发起。**比较输入：** 固定核心至少含主要支持、重要反证、关键缺口和最终 Reflection；可从已冻结证据按统一对称策略增补，M15 留存真实可见输入，不新增 Evidence View 服务。

接口名与是否写成一个或多个函数，是对应模块内部决定。**跨模块必须共享的是语义、边界、返回状态以及引用依赖，而不是 Python 调用签名。**

## 4. 最小状态轴：不可混用

| 状态轴 | 需要能区分的情形 | 为什么关键 |
|---|---|---|
| **Scientific Content** | 根候选／子代／科学内容改变 | 避免覆盖父代与错误复用分数 |
| **Ethics** | 通过、拒绝、技术未知 | 技术故障不能假装安全通过 |
| **Claim Coverage** | 机制关键点覆盖完成／遗漏／无法完成 | 不因数量限制丢掉致命前提 |
| **Retrieval/Assessment Execution** | 已按规定范围执行／部分／失败 | `searched_empty`不等于`not_searched` |
| **Epistemic Appraisal** | 支持／反证／冲突／适用性不足／无相关证据／无法评价 | 未知不能被视为错误或成功 |
| **R3 Issue** | 尚未调查、正在调查、范围内完成、未完成、同Issue已核查 | 防止无限循环或假关闭 |
| **Admission** | 准入、科学阻断、流程不完整 | 不和比赛资格混成一个标签 |
| **Match Outcome** | decisive/inconclusive/needs_more_evidence；技术failed分开 | 只有合法决定性才更新TrueSkill |
| **Comparison Coverage** | 有效比较成熟／不足／存在偏差风险 | 决定父代和正式终局资格（M10定义） |
| **Run Execution / Terminal** | 完成、有原因不完整、失败／暂停／取消；是否正式Winner | 任务结束与科学成功是两件事 |

不要求“所有维度组合的超级枚举”；让各模块保留自己的状态，M09/M12通过必要判断决定推进。只有跨模块出现“同词不同义”时才需要加字段和错误类别。

## 5. 一次正常 Run 的信息冻结点

| 阶段 | 哪些内容允许更新 | 什么必须保留历史引用 |
|---|---|---|
| 研究准备 | Project、Brief Draft | 新 Run 开始时的 GoalContext/评价政策快照 |
| 已生成但未入场 | 可因R2普通缺口执行R1定向补核查，也可按高影响风险R3补充；不能修改Hypothesis科学内容 | 候选内容；已实际发生的外部调用输入/返回 |
| Admission通过并入场 | 新候选仍可加入当前Epoch；原候选仅增加Match和派生Rating | 原候选、Inventory、Dossier、FinalReflection、评价政策与Admission指向 |
| Ranking | 比较记录、决定性评分与非执行性反馈；计划内后代 | 每场比赛的双方固定核心呈现、对称增补材料、实际输入、位置、判定与外部调用 |
| Terminal | 阅读、导出、另起独立M18/M19阶段 | 原Run的选择/不完整结果和比较依据 |

**异常处理：** 发现已参赛输入损坏、伪造、错绑或严重来源缺陷，不建立“原地修补 Match、自动新 Epoch”的常规业务路径。优先保障不继续错误科学判断，并保留原问题；暂停、结束或另开研究属于M09/M12设计细则。未来人工仅补材料不改候选的重评，属于HITL专题，不在第一版。

## 6. R3、Match 与 Delta 的交界

- R2的普通R1补核查与高影响R3是**两个独立的入场前路径**：前者按缺口要求M03–M06补足必要科学前提、Coverage或证据评价并回R2；后者仅对R2高影响Issue执行M08核验。R3可复用既有R1并按需调用M04/M05；**每次R3都由R2最后汇总**，不因无需新搜索而跳过。
- Ranking只向M11传`ComparativeFeedback`（强调相对优劣、具体比较困难及未决信息），不向M03–M08发执行任务；M10需保持候选跨Match核心科学输入一致，针对性材料选取对双方对称，实际输入留存在M15调用记录。
- M11的`RevisionSuggestion`参考限于选择已达父代资格的父代；不批准“基于科学未准入H的直接修复型Mutation”。
- `ResolvedDelta`区分科学继承关系与证据复用资格；M04判断哪些来源材料可复用，M05独立核对其对新的 Claim 和实验条件是否仍成立。
- M10选父代时UCB从实际μσ计算，模型不得自填。M12终局以合格最高μ，不把μ理解为候选科学真实性。

## 7. 执行和资源的最小界面

M15提供：(1)稳定任务引用和实际执行状态；(2)外部调用请求/响应与材料访问记录；(3)同一科学结果幂等应用或可证明不会重复更新评分；(4)可恢复的运行检查点；(5)分任务/阶段/Run真实用量汇总。M12只调用这些必要能力，无须继承旧G3中所有Lease/事件类型和旧profile绑定。

新的技术重试/上下文溢出/模型工具故障不能伪造“科学未知”；实际 API 重试确实计入消耗，重放本地记录不重复计费。同一已确认决定性 Match 只产生一次合法评分影响。M00不强制选择全事件溯源、分布式Worker或持久化引擎。

## 8. 各模块交接最小实例

不要求本阶段构造全部Schema；后续模块应提交**正常例、科学反例、技术不完整例**：

- **M03→M04：** 一个可检验因果假说的完整关键Claim、检索意图、未覆盖点及一个隐含必要前提。
- **M04→M05：** 实际得到摘要/全文材料的来源记录，另有未取得关键来源与成功空检索。
- **M05→M06：** 一篇相关性研究被错误解读成因果支持的纠错例、一项研究不能适用目标生物体系的例子。
- **M06→M07：** 各单项Claim有支持但完整机制仍有方向性缺口的Dossier。
- **M07→M03–M06→M07：** R2发现隐含必要前提遗漏或普通证据缺口 → 作用域补核查与Dossier更新 → 最终R2重评；不触发R3、不改Hypothesis。
- **M07→M08→M07：** R2高影响Issue → R3核验发现 → 最终R2整合；含无新文献与同Issue重复两例。
- **M09→M10：** 入场与未入场候选各一；同一候选两场Match均呈现相同核心支持／反证／缺口／最终Reflection；针对材料经对称选择并记录，A/B换序不静默删减证据。
- **M10→M11：** 一个已入场合格父代、一个未准入有修订建议的候选、一个`needs_more_evidence`比较，验证仅前者有父代资格。
- **M11→M03：** `combined_from`/`modified`子代，明确其中一个旧论文仅在父代生物体系适用。
- **M12→M16：** 正式最高合格μ、无合格Winner、技术不完整三种Terminal说明。

这些是科学验收测试的**最低案例类型**，不是已有专家标注或已执行测试结果。
