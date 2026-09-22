# Co-Scientist 实现审计与研究者验收指南

审计日期：2026-09-17。对象是当前工作区，不是 GitHub 上某个已发布版本。方法：重新核对论文正文/Methods、补充材料 Note 8 伪代码和 Note 9 提示词，并沿实际调用链检查代码、模板及测试入口。本次未调用真实 LLM，也未重新实施论文实验。

## 结论

**确定性工程内核较完整；科研行为是部分实现；尚不能宣称达到原文可用性或性能。** 六个角色能接受和提交结构化结果，不等于六个角色已按原文自主协作。测试通过、完成 Run 和高 Elo 都不能替代科学质量验收。

论文描述了受 Supervisor 管理的异步六角色系统，强调迭代、辩论和反馈。[正文与 Methods](https://www.nature.com/articles/s41586-026-10644-y)。补充材料展示多轮比较、周期性系统反馈与进一步改进的流程；其伪代码不能替代完整实现规格。[Supplementary Information，Note 8–9，PDF 第 56–67 页等](https://static-content.springer.com/esm/art%3A10.1038%2Fs41586-026-10644-y/MediaObjects/41586_2026_10644_MOESM1_ESM.pdf)。

本项目的不可变内容、epoch、raw-first、anchor 与非 decisive 判定是用户要求的审计/可靠性扩展，不应反过来标称为作者逐项实现；保留它们不妨碍实现论文中的科研行为。

## 初始审计时的实际调用链（2026-09-17）

```text
网页保存配置 → CLI execute → resolver 冻结 manifest → CoreRunner
  → Supervisor.bootstrap_run → 初始 Generation
  → Worker 领取任务 / 续租
  → SkillExecutor 组装 prompt 和输入
  → provider → raw artifact → schema + 输入绑定校验
  → AgentResult → Supervisor 领域提交、预算结算、后继任务
  → initial review → PubMed + full review（按 profile）
  → 候选不足时有限 Evolution repair → 子代重新审查
  → Proximity → 准入 → 单次 Ranking / 固定 anchor 对比
  → checkpoint → 有界续赛，或 stopping → finalization

网页 GET 单事务快照 → 角色 / 任务 / 输入 / 输出 / 事件 / 费用
网页已确认控制 → 应用层 → Supervisor（不绕过状态机、不启动 Worker）
```

默认 CoreRunner 是单进程顺序驱动异步任务；有队列和租约不等于多个角色已经并发工作。finalization 是领域收尾，不等于完成了一次科学 Meta-review。

本次浏览器只读核对 `lens-deepseek-008`：已 completed / SEQ 147，Generation 1、Reflection 8、Proximity 2、Ranking 6、Finalization 1，但 Evolution 和科学 Meta-review 均为 0。这直接说明“已完成运行”与“六角色自主闭环”不是同一验收条件；本次未修改该 Run。

## 关键问题（按影响排序）

### 2026-09-18 修复更新：下述两个 P0 的新运行路径

已新增 [Research v1](../research-protocol.md)：五家真实模型新模板启用完整科学正文、摘要上下文和版本化六角色指导；Ranking 获得真实 rubric、内容绑定的分阶段评审/新颖性/来源，并要求 decisive 逐维理由。协议冻结到 manifest 和输入 fingerprint，纳入 epoch evaluation_rules_hash；judge identity 绑定模型配置。缺失正文、错误哈希/计划和不匹配协议被拒绝，固定 anchors 明示为基准定义。

此修复**只作用于启用 research-v1 的新 Run**；下文保留原审计事实作为问题来源。历史 Run、Legacy profile 和原 Replay 不自动升级。该阶段尚未修复 Meta-review 闭环；其后续实现见下方 9 月 19 日更新。条件评审及人工科学反馈等仍待完成，离线验收不能证明真实模型科学质量或论文等效性。

验收：756 项离线 Python 测试通过（3 项在线未运行），25 项 Node 测试通过；新增 30 项协议测试含五家/六角色实际输入渲染、子代重审、冻结恢复、负面输入拒绝和输出评价维度覆盖。六角色离线运行的 release invariants 为零违规。浏览器中旧副本显式选择 Research v1 后通过后端格式/支持范围校验，未保存或启动研究。

### P0：真实研究输入不应退化成 ID / 哈希

`CoreProfile.scientific_context` 默认 false；`core_preview_online.yaml`（OpenAI）、Qwen/Gemini/Claude 旧模板未显式开启。Supervisor `_scientific_inputs` 在开关关闭时不注入 `research_goal` 与 `hypothesis_contents`。DeepSeek 当前模板已开启，不能据此推断其余模板同样完整。

影响：模型可返回合规 JSON，但 Reflection、Proximity、Ranking 等下游任务可能没有科学正文。这样的供应商对比既不公平，也不能评价科研能力。

验收：对每一个**真实研究**模板检查持久化 TaskEnqueued.payload.inputs，断言所需目标、正文和证据内容确实存在，非空、对应哈希。应将合同测试/回放 profile 与研究 profile 分开；不要靠 UI 文案说明已经开启。当前设置校验已有警告，此次没有擅自重写旧 Run 或所有默认科研策略。

证据入口：`application/config.py:CoreProfile`；`supervisor/orchestrator.py:_scientific_inputs`、`_worker_task`；`configs/profiles/`。

### P0：提示词和评估上下文远弱于完整科研任务定义

Generation、Ranking、Meta-review 系统提示词仅几行，主要是 JSON 字段契约。存在 schema ≠ 存在科学方法。Ranking 输入主要是参与者/内容、epoch 与规则哈希；未系统注入双方 review 正文与具体评价 rubric。哈希证明身份，不让模型知道规则内容。

验收：保存实际渲染请求，逐项检查研究目标、用户偏好、候选、双方评审、具体评分规则、引用、反证要求是否进入输入；输入截断需显式记录。原文提示词应转化为版本化策略包，不是只修改 prompt 文件名。

证据入口：`skills/resources/*/prompts/system.md`；`agents/executor.py:build_skill_request`；`supervisor/orchestrator.py:advance` 中 ranking 任务构造。

### 2026-09-19 修复更新：有界科学反馈闭环

新真实模型模板启用 Supervisor 所有的周期 Meta-review；配置冻结总结上限/新增比赛间隔/子代上限，依赖 Research v1、Evolution 和有限调用/比赛预算。只有尚未收敛且未停止的 idle checkpoint 才调度。独立 `ResearchFeedbackRecorded` 绑定来源结果、候选内容、比赛、计划、epoch 和 hash；PubMed 不计入反馈。后续科研任务输入引用反馈版本，每条反馈最多驱动一次 Evolution，子代重新审查和准入。

正常 `CoreRunner.execute` 的离线测试已完成两轮反馈，没有调用 `schedule_exercise` 或手工注入任务。验证了崩溃恢复不重复总结调用、预算/暂停/人工停止优先、安全方向不清晰转研究者，以及新子代真实参赛。新闭环续赛优先较少参赛候选/配对，候选池变更后重新积累排名稳定窗口；暂缺覆盖不判收敛。完整契约和设置入口见 [反馈闭环说明](../research-protocol.md#有界自动反馈闭环2026-09-19-验收)。

这修复了下述 P1 的**工程闭环缺失**，不是科学改进有效性的证明。前端展示的是反馈传入哪些任务和任务完成状态；是否正确回应、是否提高假设质量，仍需检查修改理由并进行真实模型与专家评测。多轮辩论、相似度/cluster 驱动探索、条件评审与人工科学反馈仍未完成。

验收：768 项 Python 离线通过、3 项 online 未运行；26 项 Node/HTTP 通过。新增 12 项闭环测试；未调用付费模型、未改写旧 Run。历史 `lens-deepseek-008` 不会因代码更新补出 Meta-review。

### P1：Meta-review 缺少自主反馈闭环（初始发现；有界路径已接线）

有类型、执行器、领域事件与展示，但检查默认 Supervisor 后继路径，未见周期性 LLM Meta-review 调度，也未见最新 `system_feedback` 被纳入下一轮各角色输入。PubMed 工具复用 MetaReviewResult 格式，不能将这些文献事件计作科学 Meta-review。正常 finalization 只是记录完整性与终态。

`tests/live_full_workflow.py` 为六角色覆盖**显式注入** Evolution 和 Meta-review，报告中也写了 test_protocol。这证明调用链可通，不证明自主策略已完成。

验收：不使用测试注入，常规 execute 至少出现两轮“科学 Meta-review → 后继任务引用反馈版本 → 新内容”，同时能指出哪些新内容回应了哪些反馈；反馈不应被当成免审许可。

证据入口：`supervisor/orchestrator.py:_followup_tasks`、`complete_finalization`；`tests/live_full_workflow.py:schedule_exercise`。

### P1：Evolution 和 Tournament 的探索策略有限（部分修复）

9 月 17 日初始实现仅在准入候选不足时挑选非安全封锁的受阻父代做有界修复。9 月 19 日增加了基于版本化 Meta-review 的合格父代演化及新候选续赛覆盖，但还不是完整的组合、简化、跨机制探索策略。子代独立重审的边界保持不变。

Ranking 仍为单次结构化比较，未实现多轮辩论及独立记录。旧模式初始/续赛主要比较前两个候选；新闭环续赛已优先少参赛候选和未充分比较的配对，并交替左右，但未实现完整的相似度优先、cluster 采样和 top-k 竞争策略，预算有限时仍不保证全部覆盖。非 decisive 不更新 Elo 是正确扩展，但 needs_tiebreaker 不等价于实际执行平局裁决流程。

验收：至少 6 个有效候选，检查每个候选的对手/场次覆盖、左右位置交换、不同 cluster 的采样；拒绝仅反复比较前两个。辩论须有独立 turn、结束判据、预算上限和原始产物；不能只让一次响应自称已辩论。

证据入口：`supervisor/orchestrator.py:_review_repair_task`、`advance`；`agents/payloads.py:RankingResultV1`；`domain/tournament.py`。

### P1：Reflection 策略声明与实际调度要区分

initial 必需、full 根据 profile、独立 NoveltyAssessment、Proximity 不判文献新颖性，这些边界已实现。其余四类 review 有名称和 trigger_rules 配置，但当前 `derive_followup_intents` 仅从新内容生成 required_before_admission 任务，未见按风险/观测/平局信号执行完整的条件触发引擎。

文献支持 PubMed 检索和摘要持久化，仍主要是冻结查询的顺序回退及共享证据窗口；不等于针对每条机制主张主动检索正反证据，也不等于全文核验。文献中没有找到不等于机制新颖。

验收：用明确触发 fixture 逐一证明策略生成、执行及重新准入路径；引用必须绑定具体主张和来源内容。对无摘要、相反证据、无命中与全文不可用，必须保留不确定性。

证据入口：`supervisor/followups.py`；`supervisor/orchestrator.py:_literature_queries`、`_persisted_review_evidence`；`adapters/literature/pubmed.py`；`domain/admission.py`。

### P1：研究者的科学干预还未进入领域闭环

本次加入暂停/恢复调度/请求收尾入口，具有确认、序号校验和领域事件；修改目标走新配置。**人工 review、人工 hypothesis、请求重评、研究方向反馈**没有对应可用命令；不能假装设置里的备注会改变当前 Agent 推理。

所需后续边界：HumanFeedback / HumanHypothesis 独立不可变内容、作者和作用对象、来源与版本、状态待处理/已纳入；Supervisor 决定后继任务；人工假设仍需初审/安全/新颖性审查。实质改变目标应新 epoch 或新 Run，不能混用旧 Elo。

证据入口：`application/commands.py`；`application/cockpit_control.py`；`domain/research_plan.py`。当前任务 payload 仍有 plan version 1 的预览假定，不能宣称已支持网页在线修订计划。

### P1：安全保障不应只看 safety 字段

初审安全状态与准入封锁已有约束，也避免自动改写安全封锁候选；但当前未发现独立的研究目标安全筛选和持续研究方向告警链路，也没有证据显示做过同等级红队评测。领域/供应商安全能力不能由一个 `safety_status=passed` 自证。

验收：用安全、非操作性测试集评估拒绝、误拒绝、跨轮研究方向漂移，以及文献文本中的指令注入；研究者仍负责解释和审查。此开发版不是临床决策或自动实验执行系统。

### P2：模型、定价与比较实验尚有边界

五供应商 adapter 已有；一个 Run 仍选一个模型，不是角色级多模型合作。新目录只是官方参考报价，不能自动证明每个新型号支持当前请求参数。实时 usage 与成本价格版本需要单独接线，unpriced 不等于免费。

固定两个晶状体 anchors 属于内部基线，不是实验证实的真值，也不适用于所有领域。停止策略已组合 anchor/top-k/cluster/novelty/预算；不能据此认定科学发现收敛。

证据入口：`runtime/core_runner.py:_compose`；`application/model_catalog.py`；`domain/anchors.py`；`runtime/checkpoints.py`；`domain/convergence.py`。

## 已有且值得保留的工程保证

| 保证 | 检查点 | 它不能证明什么 |
|---|---|---|
| Supervisor 创建后继任务 | orchestrator / followups，TaskEnqueued.created_by | 调度策略具有科研最优性 |
| 内容不可变、投影独立 | domain/hypothesis、events/reducers | 假设本身正确 |
| 审查证据绑定内容/计划 | domain/admission、NoveltyAssessment | 引用真正支持主张 |
| epoch 冻结比较规则 | domain/tournament、events/reducers | 跨 epoch Elo 可比较 |
| raw-first 与幂等提交 | runtime/external_calls、task_payload、SQLite UOW | 供应商响应可信或便宜 |
| 非 decisive 不改 Elo | domain/tournament、Elo reducer | decisive 判定没有偏差 |
| 正常完成经过 stopping/finalization | transitions、Supervisor、Worker | 自动完成了科学 Meta-review |
| 预算与停止 checkpoint 可追溯 | budget、checkpoints、convergence | 未定价调用被 USD 上限准确保护 |

## 研究者如何逐层审核

### 1. 先审核一次运行的证据链

网页选择数据库运行 → 运行总览 → 阶段 → 任务 → 输入快照 → 调用 → 结构化输出 → 领域事件。至少抽查一个初始候选、一个被拒候选、一个子代、一个比赛和一次停止决策。

每条链都问：谁调度？依据什么？模型确实看到了哪些正文？有没有未返回/校验失败的调用？输出为何被接受？是否写入了正确内容哈希和 epoch？原始引用是否能找到？

不要只看绿色按钮、task succeeded 或 dimension_scores。文献 citation ID 只证明引用身份，不证明内容支持。应抽查原始摘要/合法可访问全文及反证。

### 2. 模块质量验收表

| 模块 | 必须观察到的输出 | 最小挑战用例 | 建议科学/工程指标 |
|---|---|---|---|
| Supervisor | 可追溯任务和合法状态迁移 | 重复结果、过期序号、停止时有在途调用 | 不重复应用；不绕过审查；最终态一致 |
| Generation | 机制、假定、预测、证伪、区分实验 | 同一问题重复采样，限制候选数 | 机制覆盖、重复率、可证伪比例 |
| Reflection | 主张级批评、正反证据、不确定性 | 注入可查证错误、仅题录、无关引用 | 错误检出/误拒绝、引用支持率、置信校准 |
| Novelty | 最接近先前工作与差异 | 已发表机制的改写、不同命名同机制 | 旧机制误判新颖比例、检索覆盖 |
| Proximity | 相似度/机制维度与聚类 | 同义改写和表面相似但因果不同 | 与专家分组一致度、稳定性 |
| Ranking | 具体比较理由，必要时不确定 | 左右交换、长度变化、同一内容不同来源标签 | 位置一致性、专家胜率、不可判率 |
| Evolution | 父代谱系、修改依据、新子代 | 父代错误、重复改写、安全封锁 | 实质改进率、机制多样性、独立复审覆盖 |
| Meta-review | 跨候选问题与下一轮可执行反馈 | 互相矛盾的评审、过时反馈 | 反馈被纳入比例、下一轮是否改善 |
| Evidence / tools | 来源、获取时间、内容级别 | 断网、限流、缺摘要、恶意文献文本 | 可追溯率、恢复率、未支持主张比例 |
| Runtime / UI | lease、raw、usage、事件状态 | Worker 退出、刷新断线、失效操作 | 无重复调用/提交、不过时报在线、无虚假成功 |

阈值应在测试前由你确认，不把本表建议当原论文公布的标准。建议所有领域门禁违规为零；科学评分另行与盲评专家基准校准。

### 3. 晶状体问题的人工评分卡

每项 0–2 分：0 缺失，1 有描述但不可直接检验，2 明确且能用实验区分。总分只能用于组织评审，不是生物学有效性的证明。

1. 五环因果链：手术构型 → 年龄/发育背景 → 早期细胞状态 → 组织形态发生 → 透明度。区分因果因素、调节因素和结果。
2. 最早决定点：具体哪个早期变量、在哪一时间窗先于分歧，而不是用终点纤维化解释纤维化。
3. 最小性：必要假定尽量少，删除某一环后应说明解释能力为何下降。
4. 反事实：相同背景只改变一个候选决定因素，应预测哪些下游结果改变、哪些不变。
5. 竞争解释：至少两个可产生不同观测结果的机制，而不是一组同义名称。
6. 区分实验：有时序、对照、读出、预期不同结果；能区分上游决定因素与伴随标志。
7. 证伪：说明哪种可观察结果足以推翻/收缩主张，不以“也可能”无限补丁保护假设。
8. 证据边界：区分晶状体直接证据、其他组织类比、推测与尚未检验；透明度不能只用单个细胞标记替代。

硬退回示例：只有通路名称；把关联写成因果；没有时间先后；实验在所有竞争解释下都预测相同结果；引用不支持关键机制。模型写出实验设想不等于实验安全、伦理或可行性已获批准。

### 4. 单模型 / 多模型评估协议

先完成上面的输入和策略缺口，再做比较，避免把不同输入信息量误判为模型能力差异。

- 条件 A：单模型单次回答；B：同一模型使用多角色迭代；C：角色分配多模型。C 要等真实路由实现后才能运行。
- 冻结同一目标集、证据截止时间/检索快照、提示词版本、输出要求和终止规则。各组保留重复试验与失败记录，不只挑成功案例。
- 同时报告等调用/等 token/等费用实验；这些不是等价约束。不限成本仍应记录预算，并报告质量—成本曲线。
- 候选匿名化、左右随机或交换，至少两名领域研究者独立评分并记录分歧。自动裁判与生成模型尽量解耦，额外测自偏好。
- 主要终点：可证伪机制质量、引用支持率、机制多样性、专家偏好和区分实验价值。次要终点：schema 成功率、延迟、token/成本。
- Elo 只作同一竞技场内部信号。跨组比较使用共同盲评和固定评价协议，给重复试验分布/区间，不比较不同 Run 的裸 Elo。

对原文性能的复现实验应建立单独数据清单：公开 benchmark 的授权版本/划分、可下载的补充数据、可复现分析脚本；作者私有数据和湿实验验证不得以本地 fixture 冒充。论文的数据/代码可用性说明是起点，不是当前仓库已经完成评估的证据。[原文 Data/Code availability](https://www.nature.com/articles/s41586-026-10644-y)。

## 一次验收的命令与交付物

在项目根目录、已安装开发依赖的环境执行；下列测试不需要模型 API key：

```bash
.venv/bin/python -m pytest -q -m 'not online'
.venv/bin/python -m pytest -q tests/scenario/test_core_release_invariants.py tests/smoke/test_lens_replay_smoke.py
npm --prefix web run check
node --test web/tests/model.test.mjs web/tests/settings.test.mjs
npm --prefix web test
```

最后一个命令还需要本地 HTTP 监听权限。不要运行 `tests/live_full_workflow.py` 当免费测试；它会调用 DeepSeek，且带有显式测试调度。

每次提交一套审计包：代码版本/工作区 diff、配置/模型快照、测试结果、运行导出、失败列表、抽查的输入输出链、专家评分和未解决风险。更改 prompt 或模型后另起可比较协议，不改历史事件。

## 建议下一轮实施顺序

1. 已完成新 Research v1 路径：真实研究 profile 完整输入 + 任务专用提示词/rubric、集成断言；保留 replay 契约。
2. 已完成有界工程路径：周期性 Meta-review、反馈版本、下一轮上下文及子代重审；真实科研改进效果待验证。
3. 公平配对和分级多轮辩论、条件 Reflection、针对主张的证据检索。
4. 人工评审/假设/方向调整的领域接口，再扩展网页入口。
5. 角色级模型路由、价格版本绑定，最后做单/多模型盲评与原文公开 benchmark。

9 月 17 日初始实施仅包含模型目录、监控与有限生命周期控制；后续修复在上述日期化更新中单独记录，其余缺口不因工程测试通过而消失。

## 本轮验证记录

- Python 全量离线：723 passed，3 online deselected，125.75 秒。
- 前端逻辑与直接 request-handler：19 passed，不监听端口；Python 控制测试使用临时 replay 数据库，验证暂停/恢复/请求收尾及拒绝过期操作，外部调用数不增加。
- Ruff、五个相关 Python 文件 mypy、JavaScript syntax、diff-check 通过。
- 浏览器实际确认 DeepSeek/OpenAI/Qwen 目录选择、ID 同步与参考价显示；未保存测试草稿或调用模型。
- 9 月 17 日完整 HTTP 监听测试被审批额度阻塞，已于 9 月 18 日补完，见下方更新。

### 2026-09-18 补充验收（已解除阻塞）

- 24 项 Node 测试全通过，包含真实 HTTP → Python bridge → Supervisor → 临时 Replay SQLite；未调用付费模型。控制测试验证暂停、继续、请求收尾、过期命令/终态恢复拒绝，外部调用数不增加；显式 Replay Worker 后进入 completed。
- 发现并修复 CoreRunner 独立导入时的循环依赖（ResolvedRunConfig 为纯类型引用）；增加三种全新进程导入回归。48 项 Python 定向测试、Ruff/mypy/JS syntax/diff-check 通过，本轮未重复全量 Python 测试。
- 网页服务已重启，浏览器确认旧服务提示消失。`lens-deepseek-008` 保持 completed / SEQ147 / 19 次调用，未对其执行控制；终态按钮按预期禁用。
- 本更新完成的是运行控制工程验收，不改变上述科研行为审计结论。
