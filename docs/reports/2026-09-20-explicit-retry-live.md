# Run009：原预算内显式重试与真实续跑

## 范围与起点

- Run：`lens-deepseek-20260919-009`；沿用冻结的 `deepseek / deepseek-flash`、Research v1、计划与epoch，不修改输入或模型。
- 用户在前端重试入口完成后要求继续。此次只授权当前失败Ranking的一次新尝试，然后由常规Worker继续同Run；再次输出无效则停止，不自动重复授权。
- 起点：`needs_attention / provider_output_invalid / SEQ123`，18外部尝试、17成本记录、0比赛、0科学Meta-review；142,178 tokens（95,657输入、46,521输出）。美元费用未定价，不解释为免费。
- 冻结上限：40计数调用、6候选、12比较；账本起点17调用、5候选、1比较预留。失败任务attempt1/3。
- 失败call：`call:lens-deepseek-20260919-009:ranking:01-opportunistic:1:1:0abd54e5-3d1c-4ec9-84ca-6881edd13fb3`。
- 原raw：24,752 bytes，`sha256:476808aa7788d79f5c0cd5ce6eb4abe7c33fbac4ac8fc06f96adf12460298136`。重试命令会重新验证完整性；保留该响应和费用，不修补JSON或指定胜者。
- 预检未发现研究Worker；前端Node服务与研究执行相互独立。原始失败导出`lens-deepseek-20260919-009-export/`保持不变。

## 执行结果

**原失败任务恢复成功，但真实闭环仍未通过。** Worker最终返回`needs_attention / provider_output_invalid / SEQ136`，没有finalization。此次新增两个DeepSeek调用：原第一场比赛的第二次尝试成功，随后第二场比赛的首次调用返回坏JSON。没有继续授权第二场重试或自动重复请求。

| 阶段 | 持久化证据与结果 |
| --- | --- |
| 显式授权 | SEQ124 `TaskOutputRetryRequested` → 125 `TaskRequeued` → 126 `RunResumed`，仅授权第一场任务attempt2 |
| 重新领取 | SEQ127，独立新Call的parent_call_id指向原失败Call |
| 第一场恢复 | SEQ129 `MatchEvaluated`，decisive；SEQ130/131更新rating；SEQ132结算同任务原失败与新成功的合计usage |
| 后继正常执行 | SEQ133/134领取第二场任务并预留预算；不是另一次技术重试授权 |
| 第二场失败 | SEQ135 `ExternalCallAttemptFailed`，SEQ136 `RunNeedsAttention`；无第二场比赛或Elo更新 |

第一场模型比较偏好hyp-004（1216），hyp-001为1184。仅一场内部偏好比较，没有完成固定anchor比较、科学Meta-review、反馈驱动演化或停止收敛检验，不能据此声称稳定排名、因果解释正确或原论文效果复现。

### 新失败的具体诊断

- Call：`call:lens-deepseek-20260919-009:ranking:01-opportunistic:2:1:4dc2718b-2d2b-4bbb-8823-108aecbee005`，是第二场任务的attempt1，不是第一场任务重试失败。
- 供应商外层JSON可解析且`finish_reason=stop`；内层`message.content`长4,628字符，解析报`Expecting ',' delimiter`，零基位置4,627（最后一字符）。
- 尾部`unresolved_disagreements`数组的最后字符串之后直接出现`}`，缺少关闭数组的`]`。没有自动补字符、提交原结果或替模型作出科学判定。
- 新失败raw为14,537 bytes，SHA-256：`d4fb80d9dcfaf39bcc5b16c40295920ac41b4de568f6db135f35f97688d47868`。
- 成功重试raw为35,523 bytes，SHA-256：`096f1ed7e068139d9db452d94f6ed3dce4c784515cc0806dc9440f5b4b7ced0a`；内层JSON可解析，最终状态`domain_result_applied`。
- 当前适配器源码已在DeepSeek请求中设置`response_format: {type: json_object}`。所以不能仅以“加JSON模式”当成已经解决，也不能从`stop`推断结构有效；此次没有改变请求构造或冻结配置。

### 用量与证据完整性

| 新调用 | 输入tokens | 输出tokens | 合计 |
| --- | ---: | ---: | ---: |
| 第一场attempt2，成功 | 15,254 | 7,840 | 23,094 |
| 第二场attempt1，无效 | 15,254 | 3,297 | 18,551 |
| 本轮新增 | 30,508 | 11,137 | 41,645 |

- 累计126,165输入 + 57,658输出 = **183,823 tokens**；20外部尝试、19成本记录。美元仍未定价，不报告虚构费用。
- 预算账本19/40计数调用、5/6候选、2/12比较（1已完成、1失败任务预留）；没有增加上限。账本计数与包括历史响应前失败的20外部尝试不同。
- 原18条ExternalCall记录与17条成本记录逐项对照旧导出均不变；原候选内容和冻结profile也保持相同。仅增加授权、调用、正常比赛及后继失败事件。
- 原始响应19/19长度与hash通过；通过只读RunReadModel导出后，新包19/19 raw文件再次校验通过。
- `verify_core_release_invariants`：22任务、20调用、1比赛，**violation_count=0**；这证明已检查的工程约束成立，不证明科学质量或闭环完成。
- 状态链：created → running → needs_attention → running → needs_attention。Worker进程已结束，CLI退出码0只表示命令正常返回，运行本身未完成。
- 浏览器自动更新至SEQ136/1比赛/20调用/183823 tokens，显示新的第二场失败call和attempt1/3，没有误显示第一场仍失败或Worker仍在线。

## 导出与后续

本次新增证据包：`lens-deepseek-20260919-009-retry-20260920-export/`；原`lens-deepseek-20260919-009-export/`仍是SEQ123失败时点的冻结快照，未覆盖。

建议下一步先离线定位Ranking输出格式可靠性与供应商结构约束兼容性，使用合成边界用例验收，再决定是否用新版本配置做有界在线验证。涉及提示词/请求语义/模型或评价身份的实质改变不能借重试写入009；不得为得到成功结论继续无条件付费重试。

此次没有修改产品代码、执行全量离线回归或Git提交/推送。上轮离线测试不能代替本轮真实失败结论。按planning-with-files保留阶段记录，区分“技术恢复通过”“完整闭环未通过”和“科学有效性尚未验证”。
