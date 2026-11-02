# Co-Scientist M00 · Phase 3 架构基线交付包

**版本：** `M00-ARCH-v1.0`（RC1全量 + RC2四文件修订）  
**状态：** `design_accepted`（2026-11-01 用户确认接受 M00 材料）。已确认的全局决策、RC2新增四项边界及跨模块最小接口已纳入。**不是已实施代码，也不是 M01 开发授权。**  
**形成日期：** RC1为2026-10-31，RC2与最终验收为2026-11-01。**最后一次核实的 GitHub main HEAD：** `7313ca032e4f5f0c84578523e0f5639ad038e7af`。  
**范围：** 新建单一科学优先 Co-Scientist，完整科学核查与 TrueSkill/UCB 演化；旧 G3 仅作独立算法及科学实验对照。

**正式权威顺序：** 本包 `01–04` 为已验收RC2修订内容；`05–08`为RC1沿用的支持文件（交接/验收状态已同步）；`reference/`为历史材料，只供追溯。`09_ACCEPTANCE_RECORD.md`记录本次验收。

## 阅读顺序

| 文件 | 解决的问题 |
|---|---|
| [00_EXECUTIVE_SUMMARY.md](00_EXECUTIVE_SUMMARY.md) | 10–15分钟阅读：全局结果、主要保留/删改和已验收设计边界 |
| [01_ARCHITECTURE_BASELINE.md](01_ARCHITECTURE_BASELINE.md) | 完整科学流程、五层架构、终局与运行边界（主文件） |
| [02_GLOBAL_DECISION_LOG.md](02_GLOBAL_DECISION_LOG.md) | 全局已定／设计已验收／模块待定、旧设计替换索引 |
| [03_INTERFACE_OWNERSHIP_MAP.md](03_INTERFACE_OWNERSHIP_MAP.md) | 科研对象、统一跨模块接口、写入权、输入身份、状态边界 |
| [04_MODULE_DEPENDENCY_MAP.md](04_MODULE_DEPENDENCY_MAP.md) | M01–M20 各模块输入输出、前置工作包、依赖、交接与实施波次 |
| [05_G3_REFERENCE_PRESERVATION.md](05_G3_REFERENCE_PRESERVATION.md) | 旧代码复用／重构／废弃分类和 G3 独立科学对照保留计划 |
| [06_M00_HANDOFF.md](06_M00_HANDOFF.md) | 可带入后续每个新聊天的独立交接与执行门槛 |
| [07_ACCEPTANCE_AND_OPEN_ISSUES.md](07_ACCEPTANCE_AND_OPEN_ISSUES.md) | M00 设计验收、模块科学未决项、非目标与测试底线 |
| [08_SOURCE_TRACEABILITY.md](08_SOURCE_TRACEABILITY.md) | 论文、旧代码、Phase 1／2 和决策的来源索引 |
| `diagrams/*.mmd` | 可复用的 Mermaid 科研流程、Reflection、分层、模块依赖与身份图 |
| `reference/` | 供独立复查的 Phase 1／2 提案与原始设计材料；**包含被替代的历史要求** |
| `manifest.json` | 交付文件 SHA-256 与来源清单 |

## 读取优先级

1. **用户当前和后续明确决定**（此包已涵盖：F1 最高合格 μ；F2 仅从已准入且满足父代资格的候选繁殖）。
2. **本包已经验收的跨模块科学与工作流约束**；最小接口建议已经随整包升为有效设计约束。
3. 当期该模块最新 `accepted` 设计与已实施代码（实施前再次核实 main）。
4. 本包明确标记的 `[模块待定]` 由相应模块及 M20 科学评测决定，不能由下游猜测。
5. `reference/` 以及历史 Phase 1／2 是审查证据，**不是当前目标流程的第二套规范**。

## 全局最短定义

**M01.prepare_goal → M02.screen_goal → M01.generate_hypotheses → M02.candidate_ethics/R0 → R1（M03–M06）→ R2 → [普通新必要前提/覆盖/证据缺口时 R1补核查回R2；高影响风险时 R3回R2] → Admission（固定依据）→ Pairwise / TrueSkill → UCB合格父代 → Crossover/Mutation → 新子代复审 → 最高合格 μ 或明确无 Winner。**

- 一个正常 Run 一个 Epoch；不同 Generation 的新候选可依次入场。
- Ranking 不检索、不触发 Reflection、不改已参赛依据；同候选跨Match固定核心支持、反证、缺口及FinalReflection；对称增补已冻结材料且记录实际输入。`needs_more_evidence` 只记录为非决定性反馈。
- 子代先 Ethics/R0/Inventory，解析 Delta 后执行增量 R1；完整 R2 每次重新形成。不存在自动修复未准入候选的 Mutation 通道。
- R2普通R1补核查与高影响R3相互区分，均在Admission前返回R2；R3始终只由R2触发；无额外终局R3。
- 第一版终局：最高**合格** μ，不是最高 UCB；资格不足可无 Winner。
- 旧 G3 不在新系统中继续运行，不要求旧 Run 恢复；仅用于独立对照。

**验收结果：** 用户于2026-11-01确认接受M00当前材料；状态已在 `06_M00_HANDOFF.md` 中标记 `design_accepted`。科学模块的实施、分支、实际测试与科学验收仍须单独批准。
