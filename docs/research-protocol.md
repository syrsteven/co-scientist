# Research v1：科学输入与评价契约

2026-09-18 实现。用于修复旧模板缺科学正文、任务提示词过于简略和 Ranking 缺实际评价依据的问题。它是本项目的版本化科研指导，不是原作者未公开提示词的逐字复刻；工程测试不能证明科研性能等效。

## 启用与兼容性

五家真实模型仓库模板和 DeepSeek 六角色测试模板均启用：

```yaml
scientific_context: true
research_protocol_version: research-v1
literature_content: abstracts
literature_sort: relevance
```

网页入口为“设置 → 评审与演化 → 科研指令协议”。从历史 Run 复制的草稿仍为 Legacy；显式升级、新建配置和 Run，不修改旧 manifest。恢复运行继续读取冻结 bundle，不换成代码中最新的科学指令。Legacy 不增加协议字段，不改原 system prompt、epoch 规则或 Replay 请求。内置 Replay trace 只适配 Legacy，Research v1 离线测试使用专用脚本响应。

Research v1 要求非空目标、因果链、产出要求及完整候选科学正文，只支持 research 比赛模式；不把尚未完整实现的 binary benchmark 当成可用开关。协议本身不自动改预算或检索表达式；下方反馈闭环更新显式调整了新模板的演化上限。比较供应商前仍需统一这些参数。

## 指令与内容如何进入实际请求

基础 `skills/resources/*/prompts/system.md` 继续定义 JSON 输出契约。新增 `domain/research_protocol.py` 定义 common instructions、六角色指令、Ranking 六维 rubric 和定性比较规则。resolver 把整个 bundle 与 SHA-256 冻结到 manifest；Supervisor 把对应角色指导写入 `TaskEnqueued.payload.inputs.scientific_protocol`。SkillExecutor 将其序列化到实际 `user_prompt.input`，参与 input snapshot 与 request fingerprint。

| 角色 | 科学内容与要求 |
|---|---|
| Generation | 完整研究目标；最早因果决定因素、方向/时序、竞争解释、干预/对照、预测与证伪实验 |
| Reflection | 当前候选正文与哈希；仅执行请求的 review stage，full review 使用实际文献与独立 NoveltyAssessment |
| Proximity | 两个完整候选；比较机制、干预预测和反证条件，只做相似度/聚类建议，不负责文献新颖性 |
| Ranking | 两个完整候选、各自内容/计划绑定的最新分阶段评审与新颖性、引用来源、实际 rubric 与 epoch 绑定 |
| Evolution | 父正文、评审和证据；修复明确缺陷、解释子代差异、保持计划版本和新 ID，子代仍独立重审 |
| Meta-review | 被引用候选及评审上下文；汇总机制缺口、偏差和区分实验，反馈仅为建议，不能创建任务或改 rating |

新假设若缺少机制链、假设前提、预测或反证条件，在 raw response 落盘后、领域提交前拒绝，不生成一半内容再让后继任务崩溃。缺失候选、正文哈希或计划不匹配、过期评审不满足 Ranking 覆盖，以及协议/epoch 绑定损坏都会拒绝构造新科研任务。

Generation 在 bootstrap 前构造目标输入；Reflection 包含尚待同一事务提交的子代内容。PubMed search/fetch 是工具任务，不套用 LLM 科研协议、不冒充科学 Meta-review。

## Ranking 评价标准

六维为 `goal_alignment`、`causal_specificity`、`evidence_grounding`、`literature_novelty`、`discriminating_tests`、`robustness_and_safety`。采用定性成对比较和明确权衡，无固定数字权重，不把评审旧分数当投票。

只有 decisive 结果必须在 `dimension_reasons` 中覆盖六维、每项非空；缺项的响应保留 raw 但拒绝应用。inconclusive、invalid、needs_tiebreaker 仍允许无 winner，不因缺乏证据被迫选胜者，也不更新 Elo。覆盖校验只检查结构，不证明理由科学正确。

Ranking 输入不包含 Elo/排行榜分数；review_context 去掉旧 dimension_scores，保留 recommendation、安全、缺陷、来源与新颖性。来源缺失显式列在 unavailable_source_ids。固定 anchors 的来源标记为 curated benchmark definition，评审标记为非实验证明；它们不是已经做过的实验。

`evaluation_rules_hash` 纳入完整协议 hash，`judge_profile_hash` 纳入冻结供应商、型号与已有生成配置。因此更换指令/模型会得到不同评价契约。`ranking_prompt_hash` 仍是基础 system prompt 的 hash，不能只检查这个字段就断言两场比赛提示词相同。仍禁止跨 epoch/Run 直接比较 Elo。

## 如何验收

1. 在“任务与产物”展开输入，检查 research_goal、hypothesis_contents、scientific_protocol，Ranking 还应有 review_context 和 evaluation_rubric。
2. 导出 Run，核对 manifest 中的 bundle/hash 和 TaskEnqueued 输入；检查原始响应与 validated/applied 状态，不只看模型是否返回 JSON。
3. 专家对六维理由、引用真实支持度、因果链和区分实验进行盲评；不要用结构校验替代判断。
4. 做模型对照时固定目标、检索、预算、演化策略和评估集，记录协议与模型 hash。当前仍一个 Run 一个模型，没有多模型合作评测平台。

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_research_protocol.py -q
.venv/bin/python -m pytest tests/unit/runtime/test_feedback_loop.py -q
.venv/bin/python -m pytest -m 'not online' -q
npm --prefix web test
```

协议专用离线用例检验五家模板/六角色的实际请求渲染、负面上下文拒绝、decisive 六维覆盖、子代重审、预算停止、冻结恢复与 release invariants。Evolution 和 Meta-review 在该协议覆盖测试中仍由测试驱动显式请求 Supervisor 调度。独立的 `test_feedback_loop.py` 则通过常规 `CoreRunner.execute` 验证两轮自动反馈，不注入调度任务；两类测试都使用脚本响应，不是真实模型推理或湿实验。

## 有界自动反馈闭环（2026-09-19 验收）

五家真实模型新模板使用下列默认设置；旧 Run、Legacy、内置 Replay 和历史六角色测试模板不会被自动升级：

```yaml
meta_review:
  max_rounds: 2
  match_interval: 2
  max_children_per_round: 1
evolution:
  max_rounds: 3
  max_children_per_round: 2
```

`meta_review.max_rounds: 0` 关闭自动反馈。开启时必须启用 Research v1 和 Evolution，且 `budget.max_model_calls` 与 `budget.max_matches` 都须有限。Evolution 轮数是修复任务和反馈驱动任务的共享上限；子代数还受剩余调用/候选预算约束，保守留出重审和比较空间，实际调用仍逐次申请预算。

Supervisor 只在队列空闲、checkpoint 判定尚未收敛、已达到新增比赛间隔时安排科学 Meta-review。它接收真实候选、评审、比较和前一反馈，产出总结、系统建议、覆盖缺口及方向安全判断。预算、科学家停止和质量收敛优先，因此可能少于配置轮数，甚至零轮；finalization 也不冒充科学总结。

科学结果提交时，Supervisor 原子记录不可变 `ResearchFeedbackRecorded`：来源任务/结果、候选内容哈希、比赛 ID、计划版本、epoch、反馈版本和完整性哈希。反馈使用契约及 hash 冻结在 manifest，并进入 epoch 评价规则身份。PubMed 的旧 `MetaReviewCompleted` 事件不会产生此快照，也不计入闭环轮次。

后续科研任务的 `research_feedback` 输入包含同一版本快照。反馈仅为可质疑的建议，不能改研究目标、评价规则、任务绑定或准入条件；安全方向为 `concern` 或 `insufficient_evidence` 时暂停至 `needs_attention / meta_review_requires_scientist_input`，不会自动修复成通过。当前尚无人工科学反馈接口，应查看产物后使用调整后的新运行，不能靠重复启动 Worker 解决科学问题。

每条清晰且有可执行缺口的反馈最多触发一次 Evolution，从反馈涉及的合格父代中选择；子代记录新内容与修改理由，重新经过 initial/full review（按策略）、新颖性、Proximity 和正式准入，获得自己的初始 rating。不会覆盖父代或继承分数。新闭环的续赛优先补足较少参赛候选和较少使用的配对；相同配对交替左右。候选池新增内容后重新积累 top-k 稳定窗口，暂缺 anchor/cluster 覆盖意味着不能收敛，不冒充完整证据。

前端“运行总览 → 反馈闭环追踪”展示最新版本、接收任务数和已完成任务数，点击可查快照。核对 `Evolution.change_rationales`、子代正文和独立评审，才能判断模型是否实际回应了建议；传入版本或任务成功本身不能证明采纳质量。

本阶段 12 项新增闭环用例覆盖两轮自主调度、Meta-review 提交后崩溃恢复无重复调用、子代重审/参赛、预算/暂停/人工停止、安全方向和篡改拒绝。全量离线 768 项 Python 通过、3 项 online 未运行；26 项 Node/HTTP 通过。未调用真实模型，未迁移旧 Run。

剩余缺口：更丰富的探索/配对与多轮辩论、条件 review 自动触发、人工科学反馈、多模型路由及科学基准测试。自动反馈接线完成不代表已复现论文性能。
