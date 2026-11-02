# Co-Scientist：跨聊天固定项目背景（Baseline Context）

**状态：** 截至 2026-10-30 的项目背景快照。每个新聊天应核对当前仓库最新 main 和实际审查 commit；不要把此快照当作实时仓库状态。

## 项目定位

- 仓库：https://github.com/syrsteven/co-scientist
- 最近核实的 main：`7313ca032e4f5f0c84578523e0f5639ad038e7af`（2026-10-30 查询）。如有更新，以实际检查的版本为准，并记录差异。
- 使用者：不懂 Python/API/Agent 内部机制的医学、生物学等科研人员。前端是主要工作入口；以**研究问题与科学假说**为核心，而不是普通聊天机器人。
- 两阶段产品流程：**研究问题 → 文献背景 → Generation → Ethics → Reflection → Ranking → Evolution → 终局候选**；随后**选定候选 → Pre-experiment Verification Gate → 实验规划**。
- 参考资料：https://www.nature.com/articles/s41586-026-10644-y 及 https://arxiv.org/abs/2608.26701。Nature 原版描述分层 Reflection、Elo、Proximity/Meta-review；arXiv 扩展版使用 TrueSkill、UCB、Tournament Selection、70% crossover / 30% mutation，具体未披露项需标明推断。

## 科研方法的已确认决定

- [已定] Reflection 由 **R0 快速科学初评 → R1 逐主张证据核查 → R2 Evidence-grounded Full Reflection** 组成；**R3 Deep Verification** 由高影响风险触发。
- [已定] 新子代 **Claim Delta → Ethics → R0 → R1 → R2 →（按需 R3）→ Tournament**；既有证据可按适用条件复用，但必须重新评估完整子代机制。
- [已定] 完整 Claim Coverage，不按固定数量上限截断必要主张；不引入用户预算限制，**记录每阶段、每次调用与 Run 总消耗**。工程层面仍需如实处理 API 超时/不可用，未来再设计用户额度政策。
- [已定] 无直接文献证据但检索与评估完整、无致命问题且可检验时，仍可以进入 Ranking。科学未知与技术失败是不同状态。
- [已定] 保留冻结 G3版本 作基线，优先跑通完整流程。保留现有成对比较、TrueSkill、UCB 父代选择及 0.7/0.3 演化主体。当前冻结 G3 balanced pairing、终局最高合格 μ 规则为对照；不要混淆 μ、σ、UCB 和科学真实性。
- [已定] 当前项目**暂不涉及 Human-in-the-Loop**；它由独立专题研究。其他计划还包含 WP3 机制多样性与创新性、V5.1 工作区、Project/Draft/Run/Import、运行监控/安装/导出、第二阶段核验和实验规划。

## 已有代码与目标能力边界

- 当前 G3 冻结流水线已有 Generation、Ethics、基线 Reflection、成对比较、TrueSkill、UCB 选父代与子代演化。
- 仓库已有 Claim Verification V2、EvidenceUnit、SourceUnit、ClaimLineage，但**当前冻结 G3 尚未整合为完整的主张级证据审查流程**。不能声称已有契约 = 已投入 G3 生产运行。
- 现有来源合法性校验不等于科学证据评价正确。目标为 Claim Coverage / Search Coverage / Evidence Appraisal / Prior-art / Evidence Dossier + 分层 Reflection + 严格的评价版本冻结。
- 现阶段 Evidence Dossier Contract V1 与 Reflection Pipeline Contract V1 是**讨论提案**，不是已合并、已验收的正式代码契约。新聊天需根据最新已验收的上游交接包重新校准。
- V5 工作区已认可“候选假说为阅读中心”的总体方向。要修复科学决策卡、主张证据绑定、Ranking 理由、主题聚类、编辑/再次研究/导入关联、真实长任务执行和导出。不要为了当前模块无故重画 V5 视觉样式。

## 一致性约束

- 新模块独立版本/分支，不静默改旧 G3、原始运行、Match、评分或历史终局；候选和证据评价依据有稳定 ID/Hash/版本。
- 区分 [已定]、[拟议]、[待定]、[工程细节]、[测试/防御]；不把论文没有披露的算法冒充论文原始实现。
- 每个窗口只解决本模块；跨模块问题记录为上游缺口、接口请求或待定决策；不在本模块擅自扩大范围。
- 有关文献、真实科学支持度、具体版本与执行结果必须引用可检查的原始资料或真实测试，不凭想象。

## 上下文优先级

已验收的接口/代码版本和新聊天中用户明确确认的决定必须与 `06_DECISION_LOG.md` 对齐；旧背景快照只用于说明缘由。发生冲突时先列出冲突，不静默选择。
