# 05｜G3 Reference Preservation & Selective Reuse Plan

**状态：** `M00-G3-REF-v1.0-rc1`，独立对照方案；不要求在新系统正式运行 G3，不要求旧 Run 恢复。  
**参考提交：** [`7313ca032e4f5f0c84578523e0f5639ad038e7af`](https://github.com/syrsteven/co-scientist/commit/7313ca032e4f5f0c84578523e0f5639ad038e7af)  
**树：** `3af0c224d664c3df5d1ba7528323f04041b0d6a1`；2026-10-31 再次查询GitHub main仍指向这一提交。  
**源信息级别：** Phase 1 的静态阅读与本次 GitHub 分支查询；**未运行 G3，未本地执行测试、未复核所有历史实验结果**。

## 1. 核心边界

- **不做双轨。** 新系统只有一个科研控制器，采用新接口与科学工作流，不需要 G3 Controller、Batch2/Batch34/Research-v2 历史分流。
- **不做历史兼容。** 旧 Profile、旧 SQLite Run、旧任务/事件、旧 Pydantic 类型不进入新系统运行合同；不为旧Run恢复保留包级code_identity校验和旧version reader。
- **保留独立科学对照。** 固定 G3 commit、研究问题/模型/配置/Prompt、可获得的真实输出、必要原始日志和可比实验资源信息。M20需要时可在隔离实验环境运行旧代码，但不是新系统依赖。
- **允许迁移少量有价值代码。** 必须先隔离旧Orchestrator依赖，证明在新目标接口下仍正确，再作为新代码的一部分使用。旧测试通过不能替代新科学质量验收。

## 2. 复用与清理分类（候选，不表示代码已验证通过）

| 类别 | 旧模块／文件及函数（固定提交） | 科学价值／复用方式 | 不应迁移的历史负担 |
|---|---|---|---|
| **R1 纯算法候选** | [`domain/bayesian_ranking.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/bayesian_ranking.py) 中 TrueSkill replay／应用 | 数学与确定性顺序更新；提取纯函数和数值测试 | 旧2-valid/6-focal、旧Tournament事件名、旧G3评分恢复 |
| **R1 纯算法候选** | [`domain/population_evolution.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/population_evolution.py) 中 `select_baseline_parents`、算子抽样 | UCB Tournament Selection和70/30演化主体的参考实现 | G3固定槽位、固定代数、旧比较资格与旧策略身份包装 |
| **R2 工具适配迁移** | [`adapters/literature/pubmed.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/adapters/literature/pubmed.py)；`agents/executor.py` | PubMed检索、去重、检索执行边界，构建通用LiteraturePort的一种实现 | 背景root/Claim-only旧profile、标题/摘要锁定、固定源数科学门槛 |
| **R2 来源处理迁移** | [`domain/evidence_units.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/evidence_units.py)；[`domain/source_units.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/source_units.py) | 分开“假说原文来源”和“文献材料定位”的科学语义 | 旧材料片段只title/abstract、多个历史身份层并行 |
| **R2 科学表示迁移** | [`domain/claim_lineage.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/domain/claim_lineage.py) | retained/modified/split/combined/new的表示；用于子代Inventory后的ResolvedDelta | 旧多层目标Hash/任务授权/冻结依赖和V1/V2兼容路径 |
| **R2 运行组件迁移** | [`runtime/worker.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/runtime/worker.py)、`runtime/external_calls.py`、[`adapters/persistence/sqlite.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/adapters/persistence/sqlite.py) | 真实模型请求响应保存、最小幂等、任务恢复、用量记录 | 旧Budget授权、G3 profile判断、历史事件全集和schema版本兼容 |
| **R3 不迁移** | [`supervisor/orchestrator.py`](https://github.com/syrsteven/co-scientist/blob/7313ca032e4f5f0c84578523e0f5639ad038e7af/src/co_scientist/supervisor/orchestrator.py)、`domain/ideation_core_boundary.py` | 仅作为理解历史真实路由、失败模式和重建参考 | G3/Batch/Research-v2分支堆叠、旧运行恢复、超量身份校验 |
| **R3 不迁移** | `release/service.py::code_identity`、`release/resources/g3.yaml`及旧费用包络/发行校验 | 仅固定历史对照身份 | 新科学包不必复刻旧发行或阻止新文件改变历史code_identity |
| **R3 可选研究，不默认迁移** | `supervisor/feedback_loop.py`、旧Proximity/Meta-review/Novelty分支 | M13科学消融研究的对照输入 | 不自动进入首阶段Admission/反馈调度 |
| **R4 必须重建科学能力** | Claim Coverage、材料实际发现与解释分离、Appraisal Rubric、机制级Prior-art、R0–R3闭环 | 需要专家样例、科研评测及独立实现 | 不能把旧Claim Verification V2 改名为新Evidence-grounded R1 |
| **R4 必须重建评价流程** | Admission、单一Epoch、Match非执行反馈、子代增量证据复用、无终局R3 | 满足已定科学边界的新系统设计 | 旧Profile路径“已有能力”不代表G3主线真的在用 |

**区别事实：** 当前源码有独立 Claim Verification V1/V2 与 Claim Lineage/Research-v2 路径，但正式 G3通过Supervisor的早期分流执行，不等于这些模块已组成完整正式 R1。对应源码路径已在 Phase 1 固定版本索引记载。不能在新系统验收时声称旧版本已形成成熟的科学核查。

## 3. 旧G3对照身份：确认与未确认清单

| 证据项 | Phase1静态核实的事实 | 当前保留状态 |
|---|---|---|
| 仓库SHA | `7313ca032e4f5f0c84578523e0f5639ad038e7af` | **身份已核实**；尚未建立独立封存环境 |
| Git tree | `3af0c224d664c3df5d1ba7528323f04041b0d6a1` | **身份已核实** |
| 配置 | `src/co_scientist/release/resources/g3.yaml` | 可通过固定Git SHA定位；未复制到本次对照环境 |
| G3 Profile | `ideation-performance-dev-g3-v1` | 静态审查记录 |
| Search policy | `2608-ideation-search-g3-v1` | 静态审查记录 |
| G3 Ranking | `trueskill_v1`；balanced pairing；旧有效胜负门槛 | **G3历史事实**，非新系统已冻结科学阈值 |
| G3 Evolution | UCB父代选择、70% Crossover/30% Mutation、G0四根槽位/三次两子代转换 | 历史对照日程；不是新系统代际规划 |
| G3 Terminal | 最高合格μ与明确不完整结果 | 供科学对照；新系统F1另已确认，但资格策略须独立验证 |
| 代表性研究输入、原始输出 | 用户历史项目可能持有，M00没有取得确切可独立验收的运行清单 | **未封存**，不得称已建立科学G3对照集合 |
| 本地G3测试及恢复 | 本轮没有执行 | **未验证**，新系统也不要求通过历史恢复测试 |

## 4. M20独立科学对照：合理但不夸大

若做 G3 对照，应优先采用同一研究问题、领域、候选限制、证据访问和可比的专家评议协议。记录模型、资料获取时间、计算用量及检索环境的差别；不同实现无法完全控制的因素必须在报告中声明。

**至少区分三组结论：**

1. **数学／工具迁移验证：** 新实现的TrueSkill数值、UCB候选选择和文献检索是否正确；这是工程测试，不代表科学价值。
2. **科学模块增益：** Claim覆盖、科学证据解释、完整机制评议、位置偏差和子代科学改进是否更优；需要独立专家样例与消融。
3. **端到端科学收益：** 更快发现可验证且有价值的科研假说、实际资源消耗及失败局限；绝不能直接用跨Run的μ值或“生成了更多假说”充当改进。

如果旧G3代表性输出、原始模型版本或材料范围缺失，则对照的相应结论必须标为**不可比较/限制**，不能补造旧实验。

## 5. G3保留步骤：属于后续准备工作，不是本轮已执行

| 具体动作 | 责任 | 本轮是否完成 |
|---|---|---|
| 记录Git commit与固定源链接、历史Profile与算法说明 | M00 | **已完成静态记录** |
| 取得可复现代码/依赖/Prompt的独立外部对照包 | M20（必要时联动M17） | 未实施 |
| 选取代表性真实研究问题和G3科学输出、去标识化并确认使用授权 | M20/研究团队 | 未实施 |
| 与新系统评测设置同一专家质量判定和可比资源记录 | M20 | 未实施 |
| 将旧函数逐一提取、重新测试并记录源commit | 各实现模块 | 未实施 |

**结束条件：** 新系统科学核心无需依赖旧G3 Controller才能运行。G3对照缺失不应迫使新系统保留旧架构，但影响对照结论必须诚实说明。
