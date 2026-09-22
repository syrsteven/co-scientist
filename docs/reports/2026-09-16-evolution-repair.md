# 有限 Evolution 开发验证

## 实现范围

Supervisor 在合格候选不足时，按冻结 profile 调度有限的评审反馈修订。
默认 DeepSeek 配置为一轮、每轮最多两个子假设；其他 profile 默认关闭。
修订任务包含父假设、持久化评审反馈和同一次运行的文献证据快照。

结果验证要求新 hypothesis/content ID、非空且属于指定父候选的血缘、
不超过分配的候选数、不覆盖父内容。子假设重新通过策略要求的初审、
full review/novelty（若要求）、Proximity 和正式准入，初始 Elo 1200。

达到轮数上限或预算不足时不再自动修订；仍不合格时保留 needs_attention。
当前硬预算在达到上限时停止探索，因此候选调度保留一个名额以容纳后续审查。
此实现补的是评审失败后的修订触发；尚非论文中对 tournament 高排名候选
持续进化的完整策略，也未新增每个子假设的独立文献检索。

## 验证

- 定向测试：24 passed。
- 最终完整离线回归：685 passed，3 online deselected，95.79 秒。
- Ruff、mypy（71 source files）与 diff check 通过。
- 脚本化 provider 通过真实 Worker、raw-first 持久化、Supervisor、评审和准入。
- 覆盖正/负子评审、初始 rating、轮数限制、候选预算不足、ID/血缘/数量拒绝。
- 模拟 Evolution 响应已提交而领域应用前中断，重启后完成恢复，只调用一次 Evolution。

## 真实验证

### Run 005：Evolution 输出暴露版本混淆

运行 `lens-deepseek-20260916-005`，模型 `deepseek-flash`。首次网络尝试受到
沙箱 DNS 限制，未收到模型响应；网络授权后按既有任务租约恢复。
随后生成4候选、取得文献摘要、完成8评审，并触发一次最多1子的Evolution。
模型把结果及子假设的ResearchPlan版本写成2，冻结版本实际为1。
系统保存raw并拒绝领域应用，停在 `needs_attention / provider_output_invalid`。
已修正新任务的显式计划版本输入和prompt；不得随子假设迭代递增。
同时澄清初审筛查内部逻辑/可证伪性/safety、full review负责文献证据的职责。

005共10次收到响应的DeepSeek调用，78,884 tokens；另有一次响应前网络失败和2次PubMed。
保留导出 `lens-deepseek-20260916-005-export/`。该运行没有成功的子假设准入。

### Run 006：主流程运行至预算停止和收尾

运行 `lens-deepseek-20260916-006`，模型 `deepseek-flash`，最终sequence 183。

| 项目 | 实际结果 |
| --- | --- |
| 新候选 | 3，另有2个冻结anchor基线 |
| 评审 | 3项初审、3项full review |
| 准入 | H2、H3通过；H1因证据不足排除 |
| Proximity | 2项候选比较 |
| Tournament | 12场，包括首轮6场及后续6场 |
| 最终状态 | completed，无未解决任务 |
| 停止原因 | hard_budget_reached（12场比赛上限），不是quality_converged |
| 状态链 | created → running → stopping → completed（含FinalizationCompleted事件） |
| 外部调用 | 21次DeepSeek、2次PubMed；23次均domain_result_applied |
| 模型用量 | 63,186 input + 53,332 output = 116,518 tokens |

主候选最终内部排名：H2（年龄相关的上皮干性与炎症预激机制）1261.10，
H3（术后早期细胞状态转换机制）1226.44。这些是模型提出并评估的假设，
以及同一epoch内的相对Elo，不是已建立的生物医学结论或外部质量验证。
全部候选落在同一建议cluster，多样性条件未满足。

首轮6场后发现Core固定调度留下空队列running。已修复为在有限调用/比赛预算
内逐场继续，交替候选和固定anchor比较，每场重新建立停止检查点。
检查点只在有新科学/预算证据时重建；重复anchor比较保留独立match ID，
使用每个冻结anchor最近的已验证比较，仍拒绝重复ID和错误epoch绑定。
同一运行从首轮检查点恢复后完成收尾，没有重跑生成、检索或评审。

完整导出：`lens-deepseek-20260916-006-export/`，包含raw、任务、假设、评审、
文献、新颖性、比赛、rating、预算、停止记录与事件。CLI事件重放确认终态一致。
导出不包含额外一次LLM Meta-review综合报告；本文件为实际运行说明。

本次006因两候选已合格而没有触发Evolution。成功的子假设重审/准入链已通过
离线脚本化provider验证，尚未在真实模型响应上完成成功验证。
两次真实验证合计195,402 tokens；美元费用仍未定价，不能把记录中的0当成免费。
这些是开发功能验证，不是论文结果复现或单/多模型对照实验。
