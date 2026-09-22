# 显式输出重试（Developer Preview）

适用于 execution-contract-v3、scientific_context 已启用的运行，在供应商响应落盘后因结构/绑定校验失败进入 `needs_attention / provider_output_invalid` 的情况。它是工程恢复入口，不提高模型的科学能力，不是对原论文的额外性能复现证据。

未启用 scientific_context 的旧 fake/replay 配置保持原来的有限租约重试契约，不会被隐式升级；本文的显式恢复入口不支持这些旧配置。

## 使用方法

### 网页入口

在“运行总览 → 运行监控与人工干预”查看“输出失败”面板。面板显示当前失败角色/模型、调用 ID、尝试次数、已用及在途预留预算，以及不能重试的原因。

- “查看原始响应”：只读读取当前 Run 所属调用，完整文件 hash/长度校验后按纯文本显示，不执行 HTML。4 MiB 以上请用 CLI 检查；页面最多显示前 65,536 个字符并标注截断。
- 对 DeepSeek/Qwen 正文或单工具参数、Replay 原文，附带 JSON 语法错误通道/行列/字符位置；只读诊断不改 raw、不调用模型。“可解析”不等于字段、重复键、绑定或科学评审通过。新运行另可选择[Ranking 严格输出协议](ranking-output.md)，不能通过重试升级旧运行。
- “检查并授权一次重试…”：弹出当前 call/sequence 的确认框，费用选项默认未勾选。勾选后才允许提交；取消不写事件，对话框期间暂停自动轮询，防止确认目标被替换。
- 成功回执明确“未启动 Worker”并给出终端命令。网页恢复 running 是队列状态，不等于模型已执行。若提示序号冲突或响应不确定，关闭、刷新并核对事件；不会自动重复提交。
- 导出快照只读；旧服务缺少 capability 时不启用按钮。更新后重启 `node web/server.mjs` 并刷新。科学安全/证据缺口不提供此重试路径。

### CLI 入口

1. 查看运行总览/事件详情，检查 `RunNeedsAttention` 的 reason、task_id、external_call_id，以及对应原始响应。只对当前 `validation_failed` 调用操作。
2. 用 `co-scientist run status RUN_ID --data-dir DATA_DIR` 取得最新 `current_sequence`；核对剩余预算和任务 attempt/max_attempts。
3. 明确接受新调用费用后执行：

```bash
co-scientist run retry-output RUN_ID --call-id FAILED_CALL_ID \
  --expected-sequence N --confirm --data-dir DATA_DIR
```

返回 `worker_started: false`、授权的 attempt、原 call ID 和新事件序号。命令不调用供应商，也不创建成本记录。它将任务重新排队、Run 改为 running；如果另一个 Worker 仍活着，该 Worker 可能立即领取并产生费用。

确认没有仍在运行的 Worker 后，需要时手动执行：

```bash
co-scientist worker run RUN_ID --data-dir DATA_DIR
```

Worker 继续该 Run 的正常流程，不只执行一条重试任务。后续所有任务仍受原预算和停止规则控制。再次失败会重新进入 needs_attention，不自动尝试直到成功。

如果序号冲突，刷新状态后再判断，不盲目循环重试。命令回复丢失时先检查事件：重复旧序号会拒绝，不会发起第二次授权。

## 不变约束

- 同一任务、幂等键、科研输入快照、prompt、provider/model、计划版本和评价标准保持不变。修改模型/提示词应走新配置/新运行，不借重试改变 epoch。
- 旧 ExternalCall 保持 validation_failed，raw 和已记录 usage/费用保留。新 attempt 获得新 ExternalCall 和 raw，并通过 `parent_call_id` 指向旧调用。
- 重新经过 raw-first → 校验 → AgentResult → 领域应用。不能添加 JSON 括号、替模型选择胜者或将原失败结果手工标为通过。
- Supervisor 命令在单个 SQLite 事务内校验状态/序号、失败 call、预留、费用、预算和次数，撤销旧租约并记录授权、TaskRequeued、RunResumed。旧 Worker 的写入能力随租约撤销失效。
- 同一 task-scoped reservation 累计各次调用的真实 usage，结算时包含失败响应；科学产物/比赛不会因技术重试重复预留或重复应用。
- 授权时检查预算，Worker 领取时再次检查。授权不是费用豁免，也不会增加 frozen budget 或 max_attempts。
- 当前要求 `max_model_calls` 有限且有剩余；尝试总数还受任务 max_attempts 限制（默认 3，包括第一次和响应前失败的恢复尝试）。额度不足时原失败仍保留，不能无限点击扩容。
- token/USD 限额按已落账用量和任务估算检查。当前任务没有准确的未来 token/USD 估算，真实供应商美元费用也仍未计价，不能保证单次调用不超 token/美元余额；硬账单上限需在供应商账户设置。确定性上界首先来自调用次数与尝试次数。
- 科学安全问题、needs_more_evidence、领域已应用结果、缺 raw/费用证据，不属于此入口。普通 resume 和过期租约恢复不能绕过 needs_attention。

## 可复核证据

`TaskOutputRetryRequested` 保存授权者类型、策略版本、原 raw 引用、请求指纹、失败/授权 attempt、预留 ID、旧租约指纹及当时预算用量/额外估算。它不是 Agent 输出。

导出中的 `events.jsonl`、`tasks.json`、`external_calls.json`、`costs.json`、预算预留与 release 检查可用于追踪重试链。历史无效响应只有在原 raw、授权、重新排队、后继领取及新 call.parent 完整匹配时才被认作合法历史关联，不能忽略全部失败调用。

主要代码：`application.commands.RetryInvalidOutput` → `application.output_retry.submit_output_retry` → Supervisor → `SqliteUnitOfWork.requeue_invalid_output`。CLI 与 Web 共用该提交函数；Web 使用独立 `cockpit_retry` 桥接，只以 rw 模式打开已存在数据库，不构造 CoreRunner 或执行迁移。

HTTP：`POST /api/runs/:id/retry-output` 接受 `{external_call_id,expected_sequence,confirmed:true}`，强制同源 JSON 与请求大小限制，不接受额外字段、路径或 Run ID。`GET /api/runs/:id/calls/:callId/raw` 只读；两者都由服务器目录解析真实数据库并校验调用归属。预算/状态冲突 409、非法参数 422、缺失目标 404、raw 超大 413；raw 内容以 JSON 字符串返回，由页面 textContent 展示。

离线验收：

```bash
.venv/bin/python -m pytest tests/scenario/test_explicit_output_retry.py \
  tests/scenario/test_failure_recovery_audit.py -q
```

覆盖重试后成功、反复失败达到次数上限、预算不足、并发/重复授权、旧租约失效、坏 raw、伪造历史关联、混合网络恢复，以及模拟 DeepSeek Ranking 失败后由独立 Worker 完成正常流程。测试使用合成响应，不调用真实模型，也不改历史 Run009。
