# DeepSeek 晶状体真实运行：修复与验证记录

日期：2026-09-15。模型：`deepseek-flash`。运行：`lens-deepseek-20260915-003`。

## 当前结论

已真实完成候选生成、PubMed 检索与题录获取，并收到两份 full review 的模型响应。
尚未完成候选全部审查、Tournament 或最终科学综合；不得将此运行作为论文性能复现结果。
当前状态为 `needs_attention`，原因为 `provider_output_invalid`，事件序号 44。

## 修复内容

- DeepSeek 输出上限、thinking、reasoning effort、超时可配置并冻结进 manifest；新示例输出上限为 32768。
- 检索不再只能使用整个研究标题：profile 可冻结最多五条检索式，空结果由 Supervisor 调度下一条，每次独立记录 raw、任务和预算。全部为空时明确失败，不凭空生成证据。
- 新启用 `scientific_context` 的任务携带假设正文、机制链、研究目标和 full review 的文献题录；新任务的 initial review 排在 full review 之前。
- `needs_more_evidence` / `reject` 且无引用的负面评审可以正常提交。已声明引用必须属于实际检索结果；“通过”仍必须有相应证据和新颖性评估。
- 负面必需审查会阻止进入比赛；违反输出契约的 live 响应会保留 raw 并暂停，而不是无约束地重试付费调用。
- 旧 manifest、任务和原始响应未被改写。新字段不会自动补到历史运行中。

## 真实观测

1. 生成成功：2 个真实模型候选，另有 2 个系统预置 benchmark anchors；两者不得混算。
2. PubMed search、summary 均成功且领域提交完成。
3. H1 第一次 full review 返回“需要更多证据”、无引用且无 novelty；旧校验器将其误拒绝。修复后的重试已正常提交同类负面结论。
4. H2 full review 返回“通过”，但引用为空且无 novelty；这是不满足契约的响应，仍被正确拒绝。
5. 运行已暂停；两项 initial review 仍未执行。此 run 的任务在初审排序修复前已冻结，因此保留历史顺序，不声称已验证新顺序的真实执行。

运行共 4 次 DeepSeek 调用：14,655 input tokens、13,886 output tokens，合计 **28,541 tokens**，包含失败评审的消耗。另有 2 次 PubMed 调用。未获得供应商实际账单金额，不能把缺失金额记成零费用。

## 证据边界与下一步

目前文献层只有 PubMed 题录，没有摘要或全文。返回非空 PMIDs 只证明检索接口工作，不能证明文献相关、机制正确或假设新颖。H1 的负面评审指出检索题录相关性不足、年龄维度不完整等问题，这些仍需要研究者核验。

下一阶段应补充主题受限的检索、摘要/可获取全文，以及明确传给模型的通过/不确定输出要求，再在新 run 中验证初审、full review、比赛和最终综合。不能放宽证据门槛来制造“跑通”。

完整本地导出位于项目根目录 `lens-deepseek-20260915-003-export/`，包含 manifest、events、tasks、external calls、usage、候选及原始响应；该目录被 Git 忽略，没有推送。

## 验证

- 检索降级、全部为空、提交后崩溃恢复且不重复调用、负面评审和错误输出暂停均有自动化回归。
- 真实检索与题录调用通过；真实 DeepSeek 调用与原始响应已留存。
- 最终全离线回归 **657 passed，3 online deselected**；Ruff、mypy（71 source files）和 diff check 通过。
