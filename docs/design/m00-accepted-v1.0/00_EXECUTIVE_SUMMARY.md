# M00 Phase 3｜已验收架构基线摘要（科学负责人／工程负责人）

**状态：** `M00-ARCH-v1.0 · design_accepted`（用户 2026-11-01 接受 RC2）。科学与搜索边界不可由模块自行修改；模块内科学细则继续独立研究。没有开始 M01 代码开发。

## 最重要的七条结论

**1. 单一新系统。** 正式架构只建一套科学工作流；旧G3是独立的算法、源码和科学对照，不继续维护旧Controller，也不将历史Run恢复/发行兼容作为新系统要求。可复用TrueSkill/UCB/检索适配等小组件，拒绝整体迁入旧Orchestrator。

**2. 科学审查完整且有分工。** M03 Claim与机制覆盖、M04真实检索、M05文献实际发现及Claim关系、M06 Dossier、M07完整R2评议。R0初评；R2发现普通新前提／Coverage／证据缺口，可要求 M03–M06 补核查再回 R2。仅高影响科学风险进入R3，所有R3结果交R2汇总。Reflection不修改候选科学内容。

**3. Ranking只比较，绝不回调科学核查。** 入场前完成必要证据工作；Ranking Judge只使用两侧固定科学依据和比较政策；同一候选跨Match保留同一核心支持、反证、缺口与最终Reflection，可从冻结材料按一致、对称策略增补，并记录实际输入。`needs_more_evidence`等非决定性不更新TrueSkill，不自动补文献。Evolution可使用比较理由创造**新子代**，新子代再走科学审查。

**4. 一个正常Run，一个Epoch。** 不同Generation的新候选依次经审查后加入；已入场候选科学依据不变，不按代建立新Epoch，不自动重建比赛和评分。严重来源/输入错误是异常处理，而不是日常搜索的证据刷新。

**5. 用户对F1/F2已给出最终裁决。** **Winner = 终局资格合格池中最高TrueSkill μ**；父代只从**Admission通过且M10父代资格充分**的候选中按UCB探索；未准入的RevisionSuggestion不产生自动修复型Mutation。比较不充分或无资格者时，可明确无Winner。

**6. 子代增量核查与完整科学重评不冲突。** 先生成新候选/DeltaProposal，经Ethics、R0、M03完整Inventory后解析ResolvedDelta；只在适用时复用材料或部分证据解释，M07必须对新整体机制形成新的R2和必要R3。父代分数不可继承。

**7. 科学评测从开始而不是最后才做。** M20a先准备固定专家任务和反例；M03/M05/M07/M08/M10/M11各自报告真实科学表现，工程schema通过不是科学有效性。首阶段内部科研使用，API无用户总额度，只记录实际消耗，科学质量优先。

## 版本边界和新系统最小接口

`GoalContext → Hypothesis → ClaimInventory → EvidenceDossier → FinalReflection → Admission(fixed refs) → Match → TrueSkill → Terminal`，父子候选由Delta连接。M15负责真实模型调用记录/证据可见视图、恢复和用量。

**精简方案：** Reflection Bundle融入FinalReflection引用、Evaluation Basis融入轻量Admission、Evidence View直接记在模型调用记录。**这属于已验收的跨模块最小接口组织；不是额外三种科学评分对象，也不预定全部Python类名。**

## M01–M20最重要的实施顺序

- **最小先导（不新增模块）：** M09a固定参赛依据、M11aDelta关系、M14aProject/Brief/Run、M15a最小执行、M20a专家样例。
- **可并行科学方法：** M01初始候选，M02 Ethics/R0，M03覆盖，M04检索，M05科学评价，M07/R3科学反例，M10比较偏差和TrueSkill数学，M11演化新意。
- **生产接入：** M03→M04→M05→M06→M07→普通缺口时按需M03–M06回R2／高影响风险时M08回R2→M09；随后M10→M11→子代复审；M12负责多代闭环。
- **产品与下一阶段：** M13可选非阻断增强（消费M03/M06/M07/M10/M11），M14–M17内部研究工作区与输出，M18/M19独立实验核验与规划；M20贯穿全过程。

## 仍未冻结的科学细节

Claim粒度与Coverage、Appraisal Rubric（独立Rubric附件本轮未提供）、R3高影响风险和核查充分性、M10比较次数/配对与资格、M11演化增益、Run代数与科学停止、具体数据源/全文能力、HITL和实验计划都留给负责模块。**最高合格μ和只从合格父代繁殖已经定，不要再当作待定问题。**

## 本次产出和下一验收门

已经形成主架构、决策日志、接口所有权、20模块依赖、G3保留清单、M00 Handoff、验收与开放问题、来源索引及五张Mermaid图。2026-10-31再次核实GitHub main为`7313ca032e4f5f0c84578523e0f5639ad038e7af`，未修改代码、未运行科研任务或新旧系统测试。

**用户已于2026-11-01验收Phase3 RC2整包；本设计基线状态为`design_accepted`。** 科学模块具体开发仍需按各模块设计门单独批准，不随M00验收自动开始。
