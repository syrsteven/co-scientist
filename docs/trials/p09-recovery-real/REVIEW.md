# Codex初审，待独立人工复核

本审阅在两阶段真实调用完成后离线制作，未进入任何模型消息或固定输入。不修改候选、P09/P10原始输出、政策、原文或历史卡片。
判断只涉及本次可见输入与政策对应关系，不替代独立伦理/科学专家复核，science_validated=false。

| 关注点 | 固定输入／原文定位 → 模型字段 | 初审与未验证项 |
|---|---|---|
| P09是否独立审查 | P09/input.json的完整fixed_candidate、intended_use、NP-02 → artifact.rationale | 明确表示未继承Goal pass，讨论拟议修饰纠正/重施和输出中介比较。没有依靠Goal测试结果直接放行的表述；是否全面识别风险仍待专家复核 |
| 用途与具体风险 | NP-01/04/06；当前仅非临床假说阅读/评议/方法开发 → specific_risks[0:3]、rationale | 区分必要核质运输受扰/脱靶等潜在干预风险与当前并未授权执行的用途；没有把文献动物/AAV叙述当成本候选已获实验许可。SOD1摘要[0,1714]确有transgenic mice/AAV报告，来源只是历史背景 |
| 科学未知不是拒绝 | NP-03/05；未指定分子/位点/模型及因果桥 → rationale、limitations_or_missing_context | 没有将科学未知、弱证据或新颖性未知直接作为reject或incomplete；将必要安全信息是否足够限定在非执行用途。这个范围判断仍需独立伦理复核，不推断所有未来实验信息都充分 |
| 政策引用与结论范围 | prepared/candidate-ethics-policy.json → applicable_clauses、limitations_or_missing_context | 引用了NP-01/02/03/04/06/07，quotes与文本一致。未单列引用NP-05，但理由讨论当前用途下是否缺少安全必要信息。pass仅到本次独立R0，保留development，不是组织批准 |
| 固定Goal与命题可辨 | goal-context.json；candidate.scoped_claim/biological_context → P10.goal_alignment | 保留核孔蛋白自身磷酸化和“不预选分子/模型”；将mRNP释放延迟作为条件性机制，未宣称在ALS已实测。没有新造位点、激酶或预定实验模型 |
| 未知／局部问题是否误阻断 | 候选premise/假设/limitations与R0政策 → blocking_defects=[]、scientific_unknowns[0:6] | 未因未知因果桥、工具尚未确定、跨情境迁移而自动阻断。proceed_to_R1不是科学肯定，不等于后续实验可以完成或机制有效 |
| 核心事实阻断依据 | 实际5份source-views，4份摘要类文本+TDP43局部正文 → blocking_defects、limitations[2] | 本次无阻断，不能编造反驳定位。明确限制未看未提供正文、图像/补充或原始数据；“未识别核心直接矛盾”不是完整来源核验 |
| 作者措辞仍有局部失真 | ANXA11视图75bf…：原文“ANXA11 fibrils induces pathological conversion of TDP-43”；candidate.evidence_anchors[2].reported_basis为“ANXA11纤维相关的…” | 候选弱化了作者报告的诱导措辞。P10未逐项指出这处强度变化，required_R1_checks也未明确点名。保留历史问题，待人工/R1逐句核查；此局部失真不自动证明本候选不可缺少核心前提错误 |
| 另一处因果措辞弱化 | SUN1视图692c…[0,1188]，约字符487起“leading to reduced interaction”；candidate.evidence_anchors[6].reported_basis为“伴随…相互作用降低” | P10.required_R1_checks[2]提醒SUN1内核膜/LINC背景及迁移边界，但未点明leading to→伴随。不能据其概括“来源报告、作者解释和新猜想被明确区分”宣称来源措辞已逐字核准 |
| 阴性与实验条件 | TDP43[33770,41370]的特定输入/RNA功能结果，SOD1核圆度无变化，SUN1弱恢复/缺失变体不影响等 → P10.required_R1_checks[2:4]、limitations[2:4] | 提出跨体系与阶段测量限制，没有宣称TDP43阴性结果证明核孔蛋白磷酸化无效；但未逐条复述所有阴性，不能说阴性覆盖已完整验证。原候选中的阴性和原始文本仍全部在输入/包中 |
| 检验与否证 | candidate.falsification_conditions特别是有效干预、可逆窗口、排除有意义效应 → P10.required_R1_checks[7] | 明确避免把统计不显著当否证，并要求预先明确检测能力/干预充分性等，契合本轮检查关注点；并未实际证明工具或测量可行 |
| R1事项是否具体 | P10.required_R1_checks[0:8] | 分别覆盖对象固定、真实修饰测量控制、来源迁移、mRNP到达/停留/释放、修饰干预选择性、时序、损伤中介与否证边界，均与当前候选有关。尚无R1执行，也不是已核实的研究设计 |

审阅结论：工程链条与限定路由成功完成；本次文本没有明显把科学未知直接升级为拒绝/阻断。仍存在未逐项点名的原候选措辞问题与阴性覆盖限制，不能宣称科学审阅完整或科学有效。
这只是一次P09和一次P10输出，不证明分类准确性、方法稳定性或政策成熟。原P09 uncertain及历史费用仍未知，恢复成功不能解决旧调用。
