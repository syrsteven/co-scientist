# 六Agent完整流程测试

## 测试方法

真实运行：`lens-deepseek-20260916-007`。使用DeepSeek和PubMed，保持晶状体研究目标。
测试入口 `tests/live_full_workflow.py`，配置 `configs/profiles/core_preview_deepseek_full_test.yaml`。
预算：60次外部调用、10个候选、12场比赛；Evolution最多产生2个子假设。

测试入口在初始评审后经Supervisor显式调度Evolution，在首轮比赛后调度LLM Meta-review，
任务输入有test_intervention标记。其余生成、文献、评审、准入、比赛、停止和收尾
使用原有生产Worker与Supervisor实现，不改写评审结论、不放宽准入。
这是六Agent集成覆盖测试，不代表默认自主调度已实现论文全部策略。

```bash
.venv/bin/python -m tests.live_full_workflow \
  --run-id lens-deepseek-20260916-007 \
  --output lens-deepseek-20260916-007-export
```

恢复未完成运行时添加 `--resume`，并为新快照使用尚不存在的导出目录。
所有真实调用都会使用配置的API额度；USD未定价时以供应商账单为准。

## 验收项

- 全部离线测试及静态检查。
- 六类Agent均完成真实LLM调用；文献来自真实PubMed。
- Evolution子内容、血缘、版本、新ID、独立初审/full review、新颖性与准入。
- 同epoch排名、非decisive不更新Elo、冻结预算及停止/收尾。
- raw-first持久化、成本和预算绑定、事件重放及导出完整性。
- 拒绝、崩溃恢复等反例使用离线测试验证，不人为污染真实研究判断。

## 结果

本次六Agent端到端测试通过。运行最终状态为 `completed`，sequence 177，
停止原因 `quality_converged`；实际走过 `created → running → stopping → completed`，
包含独立的 `FinalizationCompleted` 事件。

| 环节 | 真实执行结果 |
| --- | --- |
| Generation | 1次调用，生成4个初始候选 |
| Literature | 1次ESearch、1次EFetch；真实PubMed来源 |
| Reflection | 12次调用：6个候选各自initial/full review |
| Evolution | 1次调用，生成H5、H6两个新子假设 |
| Proximity | 2次调用 |
| Ranking | 6次调用、6场decisive比赛，含固定anchor比较 |
| Meta-review | 1次真实LLM调用，生成跨评审反馈、overview和9项证据缺口 |
| Finalization | 正常完成，无未解决任务 |

H5的父内容来自H1和H2，H6来自H3和H4。两个子假设均通过版本/新ID/血缘验证，
并独立完成初审和full review。H5通过文献新颖性、Proximity及正式准入，
初始Elo明确为1200；H6未通过准入，未被强行用于比赛。
最终主候选为H5（1269.2531）和原候选H2（1162.7469）。

模型的综合意见倾向于将“宿主年龄相关LEC能力”和“囊袋几何/完整性”联合建模，
并建议用年龄×手术构型的因子实验区分解释。这是本次模型生成和内部评审的结果；
模型同时列出了全文缺失、免疫/力学因果证据不足、是否恢复组织化而非仅减少纤维化
等缺口。内部 `quality_converged` 及Elo均不代表科学正确性、临床有效性或论文性能复现。
Meta-review中的具体实验和药理表述未经本次功能测试独立核验，不应直接视为实验操作方案。

## 工程验收

- 完整离线回归：685 passed、3 online deselected，90.41秒。
- Ruff、mypy（71 source files）和diff check通过。
- 25次外部调用全部 `domain_result_applied`：23次DeepSeek、2次PubMed。
- 25/25原始导出文件的SHA-256和字节长度逐一一致。
- 25/25成本条目与外部调用一一绑定。
- 持久化release invariant检查0项违规，涵盖lease、预算、Supervisor任务权威、
  epoch/Elo、投影、raw-first及finalization等约束。
- 终态再次执行worker未增加调用，事件序号仍为177。
- CLI事件重放与持久化状态及状态链一致。
- 本次真实比赛全部decisive；非decisive不更新Elo以及崩溃恢复/错误分支由离线测试覆盖。
- 一次辅助结果查看命令误把ratings字典当列表切片；修正查看方式后完成审计，未改动运行数据。

本次用量为113,611 input + 64,176 output = **177,787 tokens**。
美元费用未配置定价，需查DeepSeek供应商账单，不能把账本中的0理解为免费。

## 交付与边界

完整导出：`lens-deepseek-20260916-007-export/`，包括候选、评审、novelty、
Proximity、比赛、rating、成本、原始响应、任务和事件。
机器可读验收摘要为该目录的 `full_workflow_check.json`；Meta-review全文保存在
`events.jsonl` 的非literature `MetaReviewCompleted`事件及对应raw响应中。

此次真实覆盖DeepSeek和PubMed。其他四家LLM provider的契约由离线测试覆盖，
没有在此次任务中消耗其真实API额度。条件式deep/observation/simulation/recurrent
review没有在这次科学案例中触发，不声称获得这些分支的真实验证。
Evolution和Meta-review由明确标注的Supervisor测试调度触发，默认自主研究策略
的持续演化和系统反馈闭环仍不能据此宣称全部完成。
