# Co-Scientist W0｜原论文真实案例驱动的开发与最小科学评价 v0.1

**状态：** PROPOSED / 来源核对完成、未做专家标注、未执行系统测试。  
**上游：** `M00-ARCH-v1.0 / design_accepted`；`W0-MINIMAL-CONTRACTS-v0.1 / proposed`。  
**范围：** 2 个有原始论文依据的开发案例 + 6 个最小来源锚定评价任务；不改 M00，不移植原作者实现，不运行湿实验，不改变 W0 的 14 项合成接口测试。

## 0. 方法边界：真实材料 ≠ 可直接宣称的科学金标准

- **PAPER（原文事实）**：原文真实给出的研究目标、示例假说、检验结果或局限；必须附论文位置。
- **RECONSTRUCTED（开发重建）**：我们将原文内容切成 Brief、Hypothesis、Claim、Evidence、Review、Match 的开发输入；不是论文公开的系统全量原始 Trace。
- **SOURCE-ANCHORED（临时评价参考）**：已有文献支持的明确事实与必要限定；不是经独立专家盲标后冻结的最终 Gold Label。
- **UNTESTED（未验证）**：尚未运行本地 Co-Scientist、没有生成真实 Match/Rating、没有执行专家评价或湿实验。

特别重要：原始 Co-Scientist 2025-02-26 预印本已经公开了 AML 等发现，2026-05-19 Nature 是后续正式版本；现代模型可能已经学到这些结果，不能以再次说出 KIRA6 或 cf-PICI 的结论声称“独立发现”。对比发现能力需要严格独立的未来、未公开或原模型无法见到的验证材料；即使限定检索时间，也无法独自排除模型预训练泄漏。

## 1. 参考资料：来源与具体用途

| ID | 材料与具体位置 | 本包使用方式 |
|---|---|---|
| P-01 | Gottweis et al., *Towards an AI co-scientist*, arXiv 2502.18864（2025-02-26）https://arxiv.org/abs/2502.18864 | 确认早期公开日期；不能作晚于2025的盲测结果 |
| P-02 | Gottweis et al., *Accelerating scientific discovery with Co-Scientist*, Nature 2026, DOI 10.1038/s41586-026-10644-y https://www.nature.com/articles/s41586-026-10644-y | 正文 AML / liver / AMR；Fig. 3；研究局限 |
| P-03 | P-02 Supplementary Information（120页），Note 5.2（PDF页26–27）、Note 6（PDF约39–51）、Note 10.1–10.10（PDF约70–85） https://static-content.springer.com/esm/art%3A10.1038%2Fs41586-026-10644-y/MediaObjects/41586_2026_10644_MOESM1_ESM.pdf | ALS 真实示例输入和中间输出、KIRA6 原始方案、重要假设列表与评价 |
| P-04 | *The unfolded protein response modulators GSK2606414 and KIRA6 are potent KIT inhibitors*（2019）https://www.nature.com/articles/s41419-019-1523-3 | KIRA6 非预期 KIT 抑制：潜在机制替代解释，不证明 AML 中致效就是 KIT |
| P-05 | *Kinase Photoaffinity Labeling Reveals Low Selectivity Profile... KIRA6*（2020）DOI 10.1021/acschembio.0c00802 https://www.sciencedirect.com/science/article/pii/S1554893720000734 | 独立研究对 KIRA6 选择性提出限制 |
| P-06 | *Stress-induced inflammation ... KIRA6 through HSP60 targeting*（2021/2022）https://pmc.ncbi.nlm.nih.gov/articles/PMC8738768/ | 特定模型中 KIRA6 非 IRE1α 依赖效应；跨癌种不能直接外推至 AML |
| P-07 | Guan et al., *AI-Assisted Drug Re-Purposing for Human Liver Fibrosis*, Advanced Science 2025, DOI 10.1002/advs.202508751 https://pmc.ncbi.nlm.nih.gov/articles/PMC12667525/ | 人肝类器官体系下的独立实验和转化边界 |
| P-08 | He et al., *Chimeric infective particles expand species boundaries in phage-inducible chromosomal island mobilization*, Cell 2025, DOI 10.1016/j.cell.2025.08.019 https://www.sciencedirect.com/science/article/pii/S0092867425009742 | 后续可用于高度概括的机制解释、时间泄漏控制；本轮不制作可操作基因转移实验 |
| P-09 | Schmidgall et al., *Accelerating Scientific Research with Gemini in the Real-World*, arXiv 2608.26701 https://arxiv.org/html/2608.26701 | 扩展版实验：E. coli 群体形态、材料和推理系统；部分未公开实验读数不作为现成最小金标准 |

`P-03` 仅为作者给出的示例输出，并非完整可重放的全量系统运行记录。`P-04`–`P-06` 为外部独立科学证据，**不是**原作者对 AML 的实测机制证实。

## 2. DEV-01｜ALS 核孔–TDP-43：科研流程开发案例

**类型：** 原文真实研究需求 + 原文生成/评议示例；科学正确性**未**由论文实验验证。  
**原文位置：** Nature Methods 的 ALS illustrative example；P-03 Supplementary Note 10.1、10.2、10.3、10.6、10.9。

### 可用于前端提交的 Brief（中文忠实改写）

> 研究核孔复合体的核孔蛋白磷酸化是否参与肌萎缩侧索硬化症（ALS）的关键致病过程；提出一个具有创新性、可检验性的机制假说，阐明分子因果链，并给出可在 iPSC 来源运动神经元中开展的验证方案。

论文 Note 10.1 将其解析为 Novelty / Feasibility 等偏好。Note 10.2 给出的**示例（不是实验真理）**大意为：细胞应激可能改变 Nup98/Nup62 等 FG-nucleoporins 的翻译后修饰，影响其与 TDP-43 的相互作用与核孔滞留，并可能扰乱核质运输。Note 10.6 还提出运动神经元易损性及因果方向等必要假设。

### 开发运行建议（测试配置，不是全局算法默认值）

1. `prepare_goal → screen_goal → generate_hypotheses → candidate_ethics/R0`；用一个公开示例候选进行证据链调试，另外生成独立候选作流程可运行验证。
2. M03 建立可追踪的必要 Claim：应激与具体 PTM；特定 FG-Nup 在相关细胞中的状态；Nup–TDP-43 接触及其改变；TDP-43 核孔滞留；核质运输改变；运动神经元偏向性；从局部运输改变到 ALS 表型的因果桥接。这里的划分是**我们为测试设计**，不是原论文已标注的专家金标准。
3. M04–M06 取得真实材料、区分已知 NCT/TDP-43 背景与未验证的新桥接；不得把 ALS 原文示例反向用作生物学机制被证实的证据。
4. M07 发现普通遗漏时可提出 `R1SupplementRequest`；如发现可能颠覆整个机制的高影响问题，可单独提出 `R3 VerificationIssue`，交由 M08 核查后再回 R2。两种回路在 Admission 前完成。
5. 测试 M09/M10/M11：固定入场核心科学依据；真实 Match 需要**双方**都有独立 Dossier/Reflection。子代必须新 Inventory、新 R2、独立评级，不继承父代结论。

**最小完成产物：** GoalContext、Hypothesis、ClaimInventory、SearchCoverage、EvidenceAppraisal、Dossier、FinalReflection、Admission 决定，以及每次模型调用真实输入。跑通流水线不证明 ALS 机制成立。

**这个案例最适合开发：** M01、M02、M03、M07、M08、M12；原文过程完整，科学真值反而需要保守对待。

## 3. DEV-02｜AML / KIRA6：真实文献与体外验证的科学质量开发案例

**类型：** 原作者明确展示的假说 + 真实细胞实验结果 + 可核对的独立反证/限制材料。  
**原文位置：** P-02 Fig. 3，Single-agent AML repurposing；P-03 Note 5.2 和 Note 6；外部 P-04/P-05/P-06。

### 可用于前端提交的 Brief（针对性验证模式）

> 评估 IRE1α 抑制剂 KIRA6 是否值得作为 AML 的研究候选；拆解其调节内质网应激、细胞存活及药物敏感性的机制，检索既有 AML 与其他体系研究，识别能推翻机制解释的证据，并提出最小区别性验证方案。不要将体外抑制效果直接等同于靶点因果证明或临床有效性。

**说明：** 这个 Brief 已经给出了 KIRA6，适合验证 M03–M08 的科学能力；绝不可将其输出计入“系统从零独立发现 KIRA6”的指标。原文 Supp. Note 6 的 KIRA6 研究假说比这个 Brief 更完整，属于评价用参考输出。

### 真实结果与科学评价分开存储

| 事实/主张 | 论文真实报告 | 科学判定要求 |
|---|---|---|
| KIRA6 在 AML 细胞中抑制活力 | KG-1a IC50 约10 nM；NOMO-1 144 nM；HL-60 870 nM；MOLM-13 1,750 nM；非 AML TK6 180 nM（P-02 Fig.3） | 不同细胞差异巨大；不能写成“所有 AML 亚型高度敏感” |
| 体外选择性 | KG-1a/TK6 对比约18倍 | TK6 是非 AML 淋巴母细胞对照，不能代表正常造血系统、患者安全窗口或临床疗效 |
| IRE1α–XBP1 可能参与作用 | 原假说的核心机制，且已有人研究 AML 中的 IRE1α 靶向 | 剂量反应仅说明药物表型，不足以把作用归因于唯一靶点 |
| KIRA6 存在 off-target 风险 | P-04/P-05/P-06 在其他系统报告 KIT、其他结合靶点或非 IRE1α 依赖效应 | 需要靶点参与证据和更特异的对照；不能武断认为 off-target 一定解释本次 AML 结果 |
| 创新性 | 作者称“IRE1α 在 AML 已有研究，KIRA6 的具体使用在当时具有相对新颖性”，总体约为中等新颖性 | 区分 target prior-art、drug-specific prior-art、context/combination prior-art；限制为检索时点和检索范围 |
| 药物身份 | KIRA6 是研究用 IRE1α 抑制剂，论文补充材料指出其临床安全数据有限、尚未进入临床试验 | 虽原论文将其列入 repurposing 案例，但**不要称它是 FDA 已批准药物** |

### 两段可执行的科学工作流程（仅开发路径）

**A. 科学审查路径：** KIRA6 → M03 因果主张 → M04/M05 捕捉既有 AML IRE1α 研究与 off-target 来源 → M06 Dossier（有利、反证、缺口并存）→ M07 R2 识别对中心机制因果归因的高影响风险 → 必要的 M08 R3 核验 → M07 最终归纳 → M09 决定准入。发现 off-target 风险不意味着必须否决探索性、可检验的候选。

**B. 评价/演化路径：** 在两个或以上候选均独立准入并达到比较所需条件后，可对 KIRA6 与 binimetinib（P-02 均有体外数据）的机制和研究价值做 M10 练习。每场必须展示 KIRA6 的同一份主要支持、反证、缺口和最终 R2；可以对称补充比较材料。**不预设哪种药必胜，也不从论文 Fig.3 的 IC50 直接计算 TrueSkill 胜负。** 仅从已经准入且达到 ParentEligibility 的父代用 UCB 选取；演化出新子代后，M03 解析真实 Delta，再独立核查新机制。此流程为我们构建的开发测试，**不是论文公开的 KIRA6 原始 Match 或 G0–G3 Trace**。

**最小完成产物：** 至少一个有真实文献绑定的 Dossier，一个允许未知并列的 FinalReflection，一个有 off-target 问题归属的科学决策卡，以及可审核的 Match 输入（如果实际运行排序）。

## 4. 额外独立验证源：肝纤维化（先做单项评价，不再开第三个完整开发项目）

原文 P-02 的肝纤维化案例与 P-07 的配套实验指出：3 个 AI 推荐的表观遗传调节方向中，有 2 个对应药物在人肝类器官模型中展现抗纤维化效应；其中 vorinostat 是已批准用于其他癌症适应证的药物。P-07 正式期刊版描述 25 个被评价药物及多细胞系 microHO、TGFβ 相关实验；不要与更早预印本描述的 14 个药物混为同一筛选统计口径。

用于测试：区分抑制纤维化表型、影响染色质状态、促进部分再生指标和**临床肝纤维化疗效**之间不同证据级别；不能将类器官抗纤维化结果自动认定为动物或患者获益。

## 5. 最小 6 项真实来源锚定评价任务

每项都有独立条目写入随附的 `W0_MIN_REAL_EVAL_v0.1.jsonl`，包含输入上下文、指定文献、来源锚定的预期行为、不可声称的结论和专家验收状态。

| ID | 真实材料 | 评测任务 | 关键应答/失败信号 | 涉及模块 |
|---|---|---|---|---|
| R01 | ALS Note 10.1/10.2 | 从论文研究问题拆解必要因果前提 | 不漏 Nup PTM→TDP-43→NCT 桥接；不把假说称为实验证实 | M01/M03 |
| R02 | ALS Note 10.6 | R2 识别普通 Coverage 遗漏并请求 R1，而不是无故触发 R3 | 补核查完成前不 Admission；高影响独立问题仍可另进 R3 | M03–M08/M12 |
| R03 | AML Note 6 / Nature 主文 | KIRA6 在 AML 的研究新颖性 | IRE1α 靶点已有研究，药物/情境新颖性只能带范围限定；不能称绝对首创或获批 | M04–M07 |
| R04 | AML Note6 + 2019/2020/2021 off-target 原始研究 | 机理反证、竞争解释与 R3 高影响判断 | 不能用活力下降单独证实 IRE1α 因果，也不能认定 off-target 必然导致 AML 实验表型 | M05–M08 |
| R05 | Nature Fig.3 + Note5.2 | 比较不同 AML 细胞系的体外剂量反应与证据边界 | 正确识别 KG-1a 与 MOLM-13 的显著差异；TK6 不是临床安全性证据 | M05–M07 |
| R06 | 肝纤维化 Nature + P-07 | 类器官抗纤维化与临床外推、治疗性/毒性区别 | 报告 2/3 有活性并限定微型肝类器官模型；不擅自推断人体疗效 | M05–M07 |

**横切工程检查仍使用原 W0 合成 S01–S14**，尤其 S06（同候选跨 Match 核心材料固定）、S07（非决定性不更新评级）、S09（合格父代）、S10（子代重新核查）、S12（最高合格 μ）。R01–R06 不替代这些不变量测试。

## 6. 最小科学评估规则（建议，未定阈值）

每项分别记录四个维度，不用空泛的总体 LLM 自评替代：

1. **来源与事实准确性：** 论文、具体实验体系、读到的材料、数值及证据位置是否正确；编造证据为关键失败。
2. **科学推断边界：** 观测 vs 解释、药效 vs 靶点因果、体外 vs 临床、有无反证/替代解释是否被正确区分。
3. **必要机制覆盖：** 主要因果环节与关键隐含前提是否被辨识；有缺口时是否准确限定。
4. **操作路径正确性：** 普通证据不足→R1，真正高影响科学风险→按定义考虑 R3；所有核查回 R2；Ranking 不触发科学核查。

**专家临时判定卡：** `supported / contradicted / insufficient / contested` + 实际来源与理由 + 关键错误代码（`fabricated_source / omitted_counterevidence / causal_overclaim / context_overgeneralization / wrong_route / false_novelty`）。这些是**评测建议状态**，不是生产领域 Schema 或已验收 M05 Rubric。

**可直接走查的通过门：** 对上述每个案例给出可核对的证据定位、科学限制及误差报告；有基础引用错误、遗漏可得的关键 off-target 反证、把体外结果写成人体效果等情况，明确判为不通过。允许正常且有理由的 `insufficient` 或争议结论，不强制猜“正确药物”。各项的判定样本量、是否一票否决和科学统计标准由 M20 通过专家工作确定。

**评测分层：** R01–R06 是公开的 **development / retrospective source-grounded** 集，能够启动科研能力调试，但**不是盲法测试，也不是可量化“独立新发现”的结论**。真实隐藏测试须另行获取授权的未发表/时间隔离问题和实验结果，并检查训练及检索泄漏。

## 7. 推荐的最短开发与验收顺序

1. W0 设计阶段：先对 R01/R03/R04/R05 纸面标注 1 轮，确认原文事实和关键问题；同时继续维护 14 项合成接口案例。
2. M01–M07：先跑 DEV-01 的单候选科学链，再跑 DEV-02 KIRA6 的证据链；至少保留来源不足、复杂反证与普通 R1 补核查各一次。
3. M08/M09：仅在真正需高影响核验时触发 R3；固定最终 Dossier 与 Reflection 后准入。
4. M10/M11：使用独立完成准入的两个真实候选练习输入一致性与子代追踪，但没有专家独立排序前**不产生论文式排名金标准**。
5. M20：将 R01–R06 经两名领域专家逐项复核后，可冻结为有争议记录的评价集；每项记录模型真实读到的材料与完整日志。待 M20 标准审批后再定义基线模型对比与统计指标。

## 8. 不能声称的结果

- 原作者完整 Co-Scientist 代码并未开源，Supplementary Note 10 不等于可逐字重放所有 Agent Trace。
- 原文 ALS 机制示例**不是**临床或基础实验验证成功的发现；作者明示为示意且可能含科学错误。
- KIRA6 KG-1a 体外选择性不代表疾病治疗有效或靶点因果验证完成。
- off-target 文献来自不同实验情境，不是本次 AML 细胞现象的独立定因实验。
- 2026 扩展版论文的部分新实验数据（如部分未发表表型测量）未提供公开可直接计算的标签，不把其摘要声称改造成真实 benchmark。
- 本轮未下载到每场原始 Match 与训练/推理 Trace；没有运行科学模型、没有获得专家共识、没有开展对照实验，因而本包是**可执行设计提案**而不是已经验证的 scientific benchmark。
