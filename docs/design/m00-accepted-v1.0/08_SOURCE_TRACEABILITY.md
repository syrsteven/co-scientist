# 08｜来源、实际代码基准与结论可追溯性

**状态：** `M00-SOURCES-v1.0-rc1`。本文件区别论文方法、历史实际代码、用户当前决策和 M00 工程方案；没有重新声称旧论文披露 M00 的内部具体Contract。

## 1. 证据分类

| 标记 | 允许支持的内容 | 不能据此推出 |
|---|---|---|
| `[Nature 明确披露]` | 原版科学研究Agent、Reflection类型、Proximity/Meta-review、Supervisor等论文公开方法 | 本项目 M03–M10的字段、R0–R3内部工作流细节完全来自Google源码 |
| `[arXiv 明确披露]` | 后续文章报告TrueSkill、UCB、tournament parent selection、交叉/变异方法 | 旧G3配额、单一Epoch/固定Admission、R1 Dossier具体Schema完全来自论文 |
| `[论文推断]` | 根据论文描述推断的实现工作分工和缺失机制 | 真实作者未公开的Prompt、服务拆分或生产代码 |
| `[现有源码]` | 经固定Git提交实际阅读到的函数/调用分支与运行配置 | 代码已在新系统实施或旧G3真正整合所有 Research-v2 能力 |
| `[已定项目决策]` | 用户在M00 Phase2及F1/F2明确确认的架构边界 | 具体科学阈值、Schema、测试结果已经获批 |
| `[工程建议]` | Phase3精简接口、对象合并、R3Issue、前置工作包及运行异常方向 | 论文已披露或用户逐项批准其实现形式 |
| `[模块待定]` | 具体Module要研究的科学方法、阈值及算法 | M00可提前替它们宣告科学有效 |

## 2. 文献来源

- **Nature：** https://www.nature.com/articles/s41586-026-10644-y ，及补充资料 https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41586-026-10644-y/MediaObjects/41586_2026_10644_MOESM1_ESM.pdf 。已在Phase1回查Agent架构、Review和Supervisor等方法；本轮没有再次逐页核验或新增作者事实。
- **后续arXiv：** https://arxiv.org/abs/2608.26701 ，HTML https://arxiv.org/html/2608.26701v1 。Phase1详细重建中确认论文采用的TrueSkill、UCB、70/30 Evolution，以及方法章节与附录部分实验配置差异；本轮没有把 G3 2-valid/6-focal当论文算法参数，也没有宣称版本v1必定是未来最新。
- **已完成的论文重建：** 用户此前委托的两篇文章的完整方法报告PDF，当前会话已提供；本Phase3使用方法级结论而非再重建全部实现细节。

**冲突优先级：** 两篇论文对同一机制有直接差异时以后续arXiv为主；Nature有而后文未再次讨论的能力，不以“未提到”推定删除。本地R0–R3职责、单一Epoch、未准入父代禁止自动修复均为项目决策，不冒充论文原生规范。

## 3. 源码基准与实际静态路径

**GitHub仓库：** https://github.com/syrsteven/co-scientist  
**2026-10-31再次检查main：** `7313ca032e4f5f0c84578523e0f5639ad038e7af`  
**提交时间：** 2026-10-26T00:46:35Z，commit message `fix(web): close diagnostic trust, PID and stream boundaries`。  
**源码完整树：** `3af0c224d664c3df5d1ba7528323f04041b0d6a1`。

固定路径中的有用结论（行号是**固定SHA阅读定位**，未来仓库变更需重新核对）：

| 旧文件、函数/范围 | 可以引用的实际结论 | 新系统处置 |
|---|---|---|
| [`src/co_scientist/supervisor/orchestrator.py` `handle_result`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/supervisor/orchestrator.py#L3745-L3795) | G3结果在Supervisor提前路由专用基线分支，并非自动使用普通Research-v2 | 不移植分支组合；M12单一新控制器 |
| [`src/co_scientist/supervisor/orchestrator.py` `advance`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/supervisor/orchestrator.py#L5870-L5940) | G3推进进入专用 `_advance_baseline_search` | 不能把其他分支的Claim核验当作G3现成功能 |
| [`src/co_scientist/domain/ideation_core_boundary.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/ideation_core_boundary.py#L110-L162) | 历史G3预期能力的显式隔离/禁入条件 | 不继承为新系统核心策略 |
| [`src/co_scientist/domain/ideation_prerequisites.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/ideation_prerequisites.py#L400-L470) | `BaselineReflectionResultV1` 是简单审查描述，不是逐Claim证据驱动R2 | M03–M08重建科研能力 |
| [`src/co_scientist/domain/bayesian_ranking.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/bayesian_ranking.py#L1-L213) | G3有TrueSkill评分和balanced pairing，旧2-valid/6-focal规则确实存在 | 只移植数学；配额另M10评测 |
| [`src/co_scientist/domain/population_evolution.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/population_evolution.py#L1-L145) | G3以UCB和固定operator选择等形成后代 | 算法可拆出；新资格先行 |
| [`src/co_scientist/domain/claim_verification.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/claim_verification.py#L1-L240) | 存在独立Claim核验与多种限制的旧契约 | 来源/检索适配可用；科学评测重建 |
| [`src/co_scientist/supervisor/verification_route_v2.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/supervisor/verification_route_v2.py#L1-L220) | 独立V2 route有真实构建与核查路径、并非G3自动启用 | 不迁移全部旧任务链 |
| [`src/co_scientist/domain/claim_lineage.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/claim_lineage.py#L1-L230) | 父子Claim关系、来源绑定表示可用 | 精简至子代ResolvedDelta |
| [`src/co_scientist/domain/source_units.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/source_units.py#L1-L149) / [`evidence_units.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/evidence_units.py#L1-L151) | 假说文本出处与文献材料出处分别有身份与片段机制 | 保留科学区别，不继承旧材料范围限定 |
| [`src/co_scientist/runtime/core_runner.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/runtime/core_runner.py#L1-L220) / [`worker.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/runtime/worker.py#L1-L220) | 任务运行、调用上下文、恢复、heartbeat等工程基础 | 选择性重构，去旧G3分支与包络 |
| [`src/co_scientist/adapters/persistence/sqlite.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/adapters/persistence/sqlite.py#L1-L190) | 保存Run、任务、事件、外部调用等 | 新系统只需必要持久化和幂等 |
| [`src/co_scientist_web/store.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist_web/store.py#L1-L123) | 工作区对象目录与科学表分离的基础 | M14可参考，不代表产品层已完成 |

Phase1原始静态引用和更长对照矩阵保存在`reference/M00_PHASE1_REVIEW.md`中，已被Phase3的目标设计**部分替换**。本轮未对上述文件进行新的逐行再审，也没有新的测试通过数可以引用。

## 4. 用户决定（最高优先级）

- **M00 Phase 1 要求：** 基于论文、旧源码、既有项目决策做架构对照和完整模块边界，不直接开发；明确论文与本地重建的证据级别。
- **M00 Phase 2 反馈：** 用户明确决定单一新系统、R1属于Reflection、R3只由R2触发且必须回R2、Ranking不执行科研核查、一个正常Run一个Epoch、候选输入不可改、取消终局R3、G3只作独立科学对照、优先科学评测、少造工程抽象。
- **F1/F2 最终明确选择：** 第一版 `argmax qualified μ`作为Winner；Evolution只从Admission已通过且父代资格充分的候选中选取，不设未准入候选自动修复Mutation。
- **当前指令：** “继续phase 3”，授权整理架构基线与Handoff，不等于授权修改代码或开始M01。

用户指令高于旧文件中的过时目标。Phase1/2修订稿与旧DecisionLog中的旧Epoch重建、终局R3、旧G3兼容、Ranking EvidenceRequest，均只能作为历史决策演变的证据。

## 5. 包内历史材料与优先级

- `reference/M00_PHASE1_REVIEW.md`：第一次源码对照与目标提案，**包括已废止的双轨/自动Epoch提升内容**。
- `reference/M00_PHASE2_REVISION_PROPOSED.md`：用户Phase2修订后，最终F1/F2表决前的设计文档，**F1/F2在该文件中仍是拟议**。
- `reference/06_DECISION_LOG_legacy.md`、`reference/00_COMMON_CONTEXT_legacy.md`、两份Contract等：记录之前真实的科研计划，但含已被用户明确替代的旧要求。
- **本包01–08是唯一的Phase3当前目标入口。** `reference/` 中条款不得用于覆盖新版已定决策。
