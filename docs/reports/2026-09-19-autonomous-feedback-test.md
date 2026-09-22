# DeepSeek 自动反馈闭环真实测试

后续记录：2026-09-20在原预算内显式重试的结果见[独立续跑报告](2026-09-20-explicit-retry-live.md)。原SEQ123导出与本文当时失败结论保留；新续跑不是覆盖旧结果。

## 目的与固定边界

运行 `lens-deepseek-20260919-009`，使用用户已配置的 `deepseek-flash` 和真实 PubMed。
本次检验常规 Supervisor 调度，不使用 `tests/live_full_workflow.py` 或手工插入演化/总结任务。
研究目标仍为微创手术后透明与纤维化晶状体再生的因果机制。

```bash
.venv/bin/co-scientist run execute \
  --run-id lens-deepseek-20260919-009 \
  --goal examples/lens_regeneration_goal.yaml \
  --profile configs/profiles/core_preview_deepseek.yaml \
  --provider deepseek --data-dir .co-scientist-deepseek
```

冻结配置以运行 manifest 为准：Research v1、摘要证据；最多 40 次计数调用（含文献任务）、
6 候选、12 比较。Meta-review 最多 2 轮、间隔至少 2 场新增比较、每次反馈最多 1 子代；
Evolution 总计最多 3 次、每次最多 2 子代，反馈路径另受 1 子代上限限制。
预算/收敛/科学安全边界优先，不保证触发所有角色，不追加预算追求成功。

## 验收口径

- 从实际持久化输入/响应和事件判断角色执行，不把初始化 anchor 事件计为生成或模型评审。
- 区分文献工具的 MetaReviewCompleted 与科学 ResearchFeedbackRecorded。
- 检查后续任务中的反馈版本、演化修改理由、独立子内容及必需重审；父代不得被覆盖。
- 检查实际准入/比赛，不把 review 的 pass 或任务成功等同于准入。
- 核对原始响应、成本记录、release invariants、状态链及终态导出。
- 前端只读实时核对；旧 Run 不修改，密钥不打印或导出。

## 实际结果

**本次真实闭环验收未通过。** 最终为 `needs_attention / provider_output_invalid`，
SEQ 123；不是 completed，也没有 finalization。第一场 Ranking 响应不能解析为 JSON，
系统保留原始响应并停止，未写 MatchEvaluated、未更新 Elo，尚未触发科学 Meta-review。
没有为了获得成功结果另开 Run、追加预算或修改模型判断。

| 环节 | 实际结果 |
| --- | --- |
| Generation | 1 次成功，3 个初始候选 |
| 文献 | ESearch 首次连接失败；租约到期后正常恢复，重试 ESearch 与 EFetch 成功；10 个来源，9 篇含摘要 |
| Reflection | 10 次成功，5 个候选各自 initial/full review |
| Evolution | 1 次 Supervisor 自动 repair，生成 hyp-004、hyp-005；不是 Meta-review 驱动 |
| Proximity | 2 次成功，正式准入候选为 hyp-001 与子代 hyp-004 |
| Ranking | 第 1 次返回无法解析的 JSON；另 5 个任务未执行，无有效比赛 |
| Meta-review | 0 次；没有 ResearchFeedbackRecorded，也没有反馈驱动子代 |

hyp-002、hyp-003 的完整评审为 needs_more_evidence，准入不足触发了 repair。
两个子代均保留新内容与父引用，并独立执行初审和完整评审；hyp-005 的完整评审仍为
needs_more_evidence，没有强行通过。上述判断属于模型产物，未独立验证生物学正确性。

### 两次阻塞的处理

1. PubMed `ConnectError` 发生在响应前，DeepSeek Generation 已成功保存，不重跑。
   无密钥 HTTP GET 诊断恢复到 200 后，首次 Worker 继续了独立初审；旧租约自然到期后
   再用正常 Worker 恢复文献任务。没有手工改租约、事件或证据。
2. Ranking 外层供应商 JSON 合法，内层 message.content 不是合法 JSON。长度为 4,838
   字符，解析报 `Expecting ',' delimiter`，零基位置 4,837（末字符）。供应商
   `finish_reason=stop`，并非报告 token 上限截断。未补括号、未替模型选择胜者、未自动重试。

该 Ranking raw 的 SHA-256 为
`476808aa7788d79f5c0cd5ce6eb4abe7c33fbac4ac8fc06f96adf12460298136`。
可在导出 `external_calls.json` 找到唯一 validation_failed 调用及对应 raw_artifacts 文件。

## 工程与可观测性核验

- 18 次外部尝试：15 次 DeepSeek（14 applied、1 validation_failed），3 次 PubMed
  （2 applied、1 failed_before_response）。失败前响应的调用没有伪造 raw。
- 17 份已收到的 raw 均持久化并导出；逐一校验原始和导出文件的字节长度/SHA-256，17/17 一致。
- 17 条成本记录覆盖 17 个返回响应，包括无效 Ranking 响应，usage 没有因校验失败丢弃。
- 累计 **95,657 input + 46,521 output = 142,178 tokens**。美元仍未定价，不把零金额解释为免费。
- 所有任务由正常 Supervisor 调度，test_intervention 数为 0。数据库中共有 22 个任务；暂停后仍保留未解决任务与审计痕迹。
- 浏览器自动更新到 SEQ123，显示“需要处理”、5 候选及 142,178 tokens；没有虚构科学反馈卡。
  Ranking 任务行仍反映持久化 running/待核对心跳，不意味着 Worker 仍在执行。
- 暂停后再次执行普通 Worker 立即返回同一 needs_attention/SEQ123，没有继续请求供应商。

### 在线测试结束时未通过的两项审计检查

在线测试结束时，旧版 `verify_core_release_invariants` 报告 **2 项违规**；该时点不能宣称零违规：

1. `projection_mismatch_count=1`：导出/验收使用的 `_RUN_EVENT_STATES` 未包含
   RunNeedsAttention；真实数据库为 needs_attention，但重放 state_history 只到 running。
   原始暂停事件存在，问题在状态投影映射，不能靠修改历史事件消除。
2. `external_call_without_reservation_count=1`：文献第一次失败调用的 execution_context
   引用原 reservation；同任务恢复到 attempt2 后，reservation 当前关联第二次调用。
   校验器要求每个历史 call 都与该当前关联相等，和既有重试复用预留实现冲突。
   需用真实重试路径及伪造反例确定历史关联的审计规则；未在本次测试中放宽检查。

其余审计计数为零，包括 raw-first、Supervisor 创建权、跨 epoch Elo、非 decisive
更新与正常完成前 finalization 约束；这些不抵消上面两项未通过。

完整证据保存在 `lens-deepseek-20260919-009-export/`。这是未完成运行的冻结审计快照，
不是成功结果包。该导出原样保留，后续读侧修复不会回写它。任何新在线验证需使用明确的
新配置/预算，不能把本次结果洗成成功。

### 同日后续离线修复（Phase18）

- 补入 `RunNeedsAttention → needs_attention` 的导出/重放映射，不增加或更改历史事件。
- 历史预留关联只接受无 raw、usage、结果或领域应用的 `failed_before_response` 调用，
  且同任务、请求、冻结执行契约和预留必须匹配；每次跨 attempt 必须有完整且有序的
  TaskLeaseClaimed → TaskLeaseExpired → TaskRequeued → 下一次 TaskLeaseClaimed 证据。
  仍拒绝错绑、伪造租约、缺失/错序恢复链和其他失败状态，并非忽略失败调用。
- 新增 `tests/scenario/test_failure_recovery_audit.py`，14 项测试覆盖一次/连续两次正常
  恢复、11 种伪造反例，以及 DeepSeek 外层正常结束但 Ranking 内层 JSON 损坏的失败链。
  坏响应必须保留 raw/usage、暂停且不更新 Elo；再次 Worker 不自动发请求。
- 使用修复后的只读校验器复查原009：审计计数为 **0**，重放状态链为
  created → running → needs_attention；仍为 SEQ123、18 次调用、0 场有效比赛。
  没有调用在线模型、修改 SQLite 写侧、旧 raw、模型判断、预算或已保存导出。

审计修复只解决了读侧误判和状态遗漏，**没有修复供应商生成坏 JSON 的能力问题**，
也没有把本次真实反馈闭环改判为成功。自动纠正 JSON 或付费重试尚未在此轮引入。

复查本轮修复不需要 API key：

```bash
.venv/bin/python -m pytest tests/scenario/test_failure_recovery_audit.py -q
.venv/bin/python -m pytest tests/scenario/test_core_release_invariants.py -q
```

前者经过真实 Worker、HTTP adapter 模拟响应和临时 SQLite；不读取研究者009的私有
科学正文作为测试 fixture。后者保留既有发布约束的独立篡改负例，防止为通过本案例而放宽审计。

最终验收：14 项新增回归及 90 项定向测试通过；完整离线 **782 passed / 3 online
deselected**（160.77 秒）。Ruff、目标模块 mypy 和 diff-check 通过；没有在线调用或费用。

内部排名和反馈不是科学有效性、临床效果或原论文性能的证明；本次甚至尚无有效排名，
因此不能比较单模型/多模型科研性能，也不能验证 Meta-review 改善效果。

### 同日后续显式恢复入口（Phase19，离线）

新增 CLI `run retry-output`：只对当前技术校验失败的 call 明确授权一次原任务重试。
事务内检查原 raw/成本证据、冻结任务、剩余预算、max_attempts 和 sequence，撤销旧租约；
命令不启动 Worker。新 attempt 用新 ExternalCall/raw，parent_call_id 指向原失败，
原 call 的 validation_failed 状态和费用保持不变。入口和限制见[操作说明](../output-retry.md)。

模拟 DeepSeek Ranking 坏 JSON 的回归现包含显式命令后由独立 Worker 继续到 completed：
新结果重新校验并仅应用一次，原坏 raw/cost 不变。这是合成响应的工程验收，
不是将本报告的真实009改成成功，也不证明真实模型会在重试后成功。

此次只读核对原009仍为 needs_attention / SEQ123 / 18 calls / 0 matches / 0 audit violations。
没有对009提交授权、调用供应商、重写旧导出或修改科学结论。

Phase19最终工程验收：新增31项用例；47项异常路径/旧契约定向测试通过；完整离线
**813 passed / 3 online deselected**（137.92秒）。Ruff、6个模块mypy、diff-check通过。
