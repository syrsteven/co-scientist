# Run010：严格 Ranking 的常规完整流程测试

## 结论

**本次已实际执行到一次科学 Meta-review 及其后续比较，但完整闭环未通过。** 前 7 场 Ranking 成功；第 8 场返回的严格工具参数仍含非法 JSON，系统保留响应和用量后暂停。没有自动重试、补 JSON、修改评分结果或追加预算。

这是常规 CLI/Worker 运行，不是注入六角色任务的覆盖测试，也不是此前的单调用 probe。运行结束于 `needs_attention / provider_output_invalid / SEQ182`，未经过 stopping/finalization，不得称为 completed。

## 配置与范围

- Run：`lens-deepseek-strict-20260920-010`。
- 独立数据目录：`.co-scientist-deepseek-strict/`；历史 Run009 未修改。
- Profile：`configs/profiles/core_preview_deepseek_strict.yaml`，与普通 DeepSeek 模板仅差独立 profile_id 和 `ranking_output_protocol: deepseek-strict-tool-v1`。
- 模型：`deepseek-flash`；thinking enabled、reasoning_effort low、单次 max_tokens 32768、timeout 300 秒。
- 预算上限：40 次计数调用、6 个候选、12 场比较；Meta-review 最多 2 次，Evolution 最多 3 次。不以达到闭环为由增加这些上限。
- 研究目标、Research v1、PubMed 摘要、初审/完整评审/新颖性门槛、固定 anchors、评分及停止策略保持原模板。
- 实际事件时间：2026-09-20 15:29:11 至 15:35:28（Asia/Shanghai，约 6 分 17 秒）。

## 实际到达的阶段

| 阶段 | 持久化结果 | 证据边界 |
|---|---|---|
| Generation | 1 次成功，初始 3 个候选 | 模型假设，未实验验证 |
| PubMed | 2 次调用成功 | 检索与摘要获取，不计为科学 Meta-review |
| Reflection | 10 次候选评审任务成功 | “执行成功”不等于每个科学结论通过 |
| 早期 Evolution | 1 次成功，新增 004/005 两个子代 | 为准入修复，不是 Meta-review 驱动 |
| 子代重新准入 | 004/005 均有独立 initial/full review 和 TournamentEntryCreated | 不覆盖父假设或继承父 rating；后续配对仍受相似度等策略影响 |
| Proximity | 3 次成功 | 候选空间相似度，不是文献新颖性 |
| 初始 Ranking | 4 场候选比较 + 2 场固定 anchor 比较成功 | SEQ128、134、140、146、152、158；均为内部 decisive 判定 |
| 科学 Meta-review | 1 次成功，SEQ166 | 不能把另 2 次 PubMed 上下文也算作该角色的科学调用 |
| 反馈发布 | SEQ167 ResearchFeedbackRecorded v1 | 来源绑定于当时 5 个候选内容和 6 场比赛 |
| 反馈下游 | 后两次 continuation Ranking 输入都绑定 feedback:1 | 第一场 SEQ173 成功，第二场校验失败；传入反馈不代表科学上采纳 |
| 反馈驱动 Evolution | 未生成任务 | 见下方候选余量限制 |
| 最终收尾 | 未开始 | 无 stopping/finalization/completed 事件 |

### 当前候选余量规则的限制

本次已有 5 个候选，配置上限为 6。`supervisor/feedback_loop.py` 的反馈演化规划将子代数限制为 `max_hypotheses - len(hypotheses) - 1`，因此本次可规划子代数为 0。此处额外保留一个名额，实际阻止了本轮 Meta-review 驱动 Evolution。

这解释了为什么出现了反馈但没有反馈子代，不能把早期修复演化当成该分支已覆盖。后续应离线确认额外预留是否必要、是否与预算预留重复；本次没有现场删除守卫、修改 frozen profile 或扩大候选上限。

## 第 8 场 Ranking 的失败证据

- Task：`lens-deepseek-strict-20260920-010:ranking:03-continuation:2`，attempt 1/3。
- Call：`call:lens-deepseek-strict-20260920-010:ranking:03-continuation:2:1:840e4187-7115-42b5-862b-f4fb7e0c88e2`。
- 响应有唯一 `submit_ranking_result` 工具，`finish_reason=tool_calls`；不是 `length` 终止。
- 内部 `arguments` 长 6,010 字符，在零基位置 1,507（第 1 行、第 1,508 列）报 `Expecting ',' delimiter`。
- 错误不是末尾少括号：一个理由字符串结束后又出现冒号和空字符串值，形成非法 JSON 结构。保留原文，没有删字符或重新解释为有效结果。
- Raw：10,224 bytes；SHA-256 `86091fdac622f6889738e020b0e47b508956e8ad6cbc3f2f14a6ca47435c5c81`。
- SEQ181 ExternalCallAttemptFailed → SEQ182 RunNeedsAttention。无第 8 场 MatchEvaluated 或 Elo 更新。
- 该失败调用使用 16,762 输入 + 2,416 输出 = 19,178 tokens，费用/用量未丢弃。

供应商接受严格 schema、返回 `tool_calls`，仍不构成本项目可以跳过本地校验的理由。此前 probe 成功及本次前 7 场成功不能证明协议能够消除非法 JSON。本次与009的候选、上下文和随机输出不同，不将 7/8 当成标准 JSON/strict 的受控可靠率对比。

## 用量、完整性与审计

| 项目 | 结果 |
|---|---|
| 外部调用 / 成本记录 | 26 / 26；含 2 次 PubMed、24 次 DeepSeek |
| 已领域应用 / 校验失败 | 25 / 1 |
| 输入 tokens | 246,719 |
| 输出 tokens | 72,058 |
| 合计 tokens | **318,777**（不含此前独立 probe） |
| 金额 | 未定价；零记账金额不能解释成免费 |
| 预算账本 | 26/40 调用，5/6 候选，8/12 比较（7 完成 + 1 失败任务预留） |
| 原始 raw 完整性 | 26/26 长度与 hash 通过 |
| 导出 raw 完整性 | 26/26 长度与 hash 通过 |
| release 审计 | 26 任务、26 调用、7 比赛，violation_count=0 |

没有跨 epoch 比较、非 decisive 更新 rating、普通 Agent 创建任务、无 finalization 却完成 Run 等已检查的工程违规。但零违规不代表科学质量、推断正确或完整科研流程成功。

独立导出：`lens-deepseek-strict-20260920-010-export/`。包含 manifest、任务、事件、评审、新颖性、候选、比赛、反馈所在事件、成本与 raw_artifacts。Run009 的 calls/costs/hypotheses/tasks/matches/reviews/epochs 与此前 SEQ136 导出逐项一致。

## 后续建议

1. 先离线复现本次严格工具参数错误，评估输出字段设计和可观测诊断；不要用删字符或宽松解析把原响应标为成功。变更输出语义需新协议/epoch，不借重试升级010。
2. 离线核对反馈演化额外预留一个候选名额的规则，并用边界测试确认修订不会突破真实预算。
3. 当前失败任务在原预算内仍具有显式技术重试资格，但本轮没有授权。重试可能再次收费，不能默认持续运行直至通过。

本轮只新增独立 profile 和测试报告，没有改写运行内核、模型结果或历史证据，也没有重复全量离线审查。浏览器页面已创建，但最终 DOM 验证因工具额度审批失败未执行；以上结论来自持久化事件、只读数据库及导出，而非未完成的页面操作。

## 后续离线复查（2026-09-20）

候选余量的额外 `-1` 与 `BudgetPolicy.reached` 在候选数达到上限时触发**全 Run 硬停止**的现有语义有关，不能简单当作多减一次：如果直接使用最后一个名额，子代生成后可能无法完成后续独立评审。是否将新版本上限改为“只限制新增候选，其他处理继续”是需要明确选择的行为变更；在选择前保留原规则，未改写010。

输出侧另增实验性 strict v2，扁平化六维理由但完整保留科学文本和校验。156项Python定向及9项Node设置测试通过，v1契约/hash保持一致；原7份成功结果解码完全相同，第8份仍在位置1507被拒绝。没有在线v2调用、JSON修补或010重试；该改动不改变本报告的完整流程未通过结论。
