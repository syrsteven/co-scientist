# Co-Scientist Web Workbench 0.4 — 后端接口契约建议

基线：`syrsteven/co-scientist` `main@21213ed0d7863547aff5c081e75bfb0c4f875ec6`，Release 0.1.1。本文件定义**尚未实现**的未来 HTTP API，不应当被解读为真实可用的接口。

## 设计原则

- 前端只提交 `project_id/run_id` 等逻辑 ID，不允许浏览器指定服务器任意磁盘路径。
- Web API 包装正式 `co_scientist.release.service.RunService`，不得重新实现 CoreRunner、科学评分、TrueSkill、Evolution、Raw/ledger/fencing 或硬预算。
- v0.1.1 的 G3 Frozen Profile 必须保留为可追溯默认配置。动态模型、代数、预算组合只有在经过版本化 Config Builder、合法预算规划、模型能力验证和完整离线 Mock 后才允许上线。
- Draft 与 Run 分离：Draft 可编辑，Run 的 Goal、Profile、配置身份、版本和授权一旦冻结不可变。变更必须创建新 Run。
- 模拟任务与付费任务严格隔离。浏览器任何页面都不应访问或回显 API Key。
- 原生 `stop()` 是终止请求，会关闭为 PARTIAL；并非可继续的暂停。只允许在原生恢复条件满足时调用 `resume`。
- 原生 Trace 的数据源是事件、SQLite、Raw 和 budget ledger，不得按文件名/候选名称推断父代、代数或者正式 winner。

## 端点（提议）

| Endpoint | 方法 | 用途 |
| --- | --- | --- |
| `/api/v1/health` | GET | 服务器、数据库、Tokenizer、Runner 可用性（不暴露密钥） |
| `/api/v1/projects` | GET/POST | 列表与创建项目（真正服务器持久化） |
| `/api/v1/projects/{projectId}` | GET/PATCH | 项目元信息（与运行配置分离） |
| `/api/v1/drafts` | POST | 保存可编辑研究目标和运行配置草稿 |
| `/api/v1/config/defaults` | GET | 返回已验证配置模板及允许编辑的字段 |
| `/api/v1/config/models?role={role}` | GET | 返回**当前执行器已适配**、账户可用性验证状态及其来源；仅目录展示不得当作已适配 |
| `/api/v1/settings/status` | GET | 返回 `{openai_configured, deepseek_configured, pubmed_email_configured, backend_connected}` 等布尔状态；**绝不返回密钥** |
| `/api/v1/settings/credentials/{provider}` | PUT/DELETE | 经身份认证及安全传输，分别保存/撤销 OpenAI、DeepSeek 凭据；只返回是否已配置 |
| `/api/v1/settings/pubmed` | PUT/DELETE | 保存或撤销 PubMed 联系邮箱；后端在**新建 Run 时**冻结该字段 |
| `/api/v1/settings/validation` | POST | 用户显式请求服务端检查账户配置/模型权限；需注明是否可能产生调用费用 |
| `/api/v1/config/models` | GET | 返回实际适配完成且允许选择的模型角色/能力组合 |
| `/api/v1/config/preflight` | POST | 不付费的科学配置、模型能力、成本和权限检查，返回错误定位及配置 hash |
| `/api/v1/runs` | POST | 按通过的 preflight 冻结一个全新 Run，返回 run_id |
| `/api/v1/runs/{runId}/authorize` | POST | 二次确认本 Run 的预算上限和未知计费风险 |
| `/api/v1/runs/{runId}/start` | POST | 在后台 durable job 中启动；幂等防重 |
| `/api/v1/runs/{runId}/status` | GET | 原生 state、工作进度、费用估算和 reservation |
| `/api/v1/runs/{runId}/events?after={sequence}` | GET | 增量事件（无运行前数据库时返回空集） |
| `/api/v1/runs/{runId}/stream` | GET | SSE 事件，重连后按 sequence 补发 |
| `/api/v1/runs/{runId}/leaderboard` | GET | 由已提交 TrueSkill 事件构建轻量排名 |
| `/api/v1/runs/{runId}/candidates/{id}` | GET | 完整候选及 Reflection、父代、评级来源 |
| `/api/v1/runs/{runId}/lineage` | GET | 原生 parent_id → child_id，带版本序列 |
| `/api/v1/runs/{runId}/rankings` | GET | 历史真实配对、胜负和 μ/σ 更新 |
| `/api/v1/runs/{runId}/stop` | POST | 明确确认的终止请求，标记 PARTIAL |
| `/api/v1/runs/{runId}/resume` | POST | 符合恢复条件的原 Run，绝非重开终态 |
| `/api/v1/runs/{runId}/exports` | POST | 创建一致性 Native Trace 快照；忙时返回可重试错误 |
| `/api/v1/runs/{runId}/exports/{exportId}` | GET | 受控下载原生五项 Trace / 项目备份 |

## 用户设置与密钥处理（v0.4 新增）

本地网页已实现“设置”入口、OpenAI / DeepSeek API Key 的密码输入、显示/隐藏、覆盖与清除、PubMed 联系邮箱和可选研究者显示名。**本地版只保留在当前标签页的内存中，未实现任何网络请求、持久化或实际 API 验证**。刷新后 API Key 会消失，且不会进入 localStorage、研究草稿、Markdown/JSON 导出或 Native Trace。

生产接入应满足：

1. 只允许从受信任来源、受保护的本地后端或 HTTPS 认证会话更新 API Key；不允许普通静态网页将明文密钥发送给任意外部地址。对于本地工作台可优先使用 OS Credential Store / 受控密钥管理；远程部署必须具备权限隔离、静态密文保护与审计。
2. 禁止通过 `GET`、日志、错误响应、SSE、事件导出、工作流配置或前端 localStorage 回传/保存明文密钥。`status` 仅提供布尔值，不提供密钥尾号（可选），任何情况下不显示完整凭据。
3. 后端运行器在受控执行进程中将凭据映射为 `OPENAI_API_KEY`、`DEEPSEEK_API_KEY` 与 `CO_SCIENTIST_PUBMED_EMAIL`；不将密钥写入 manifest、Plan、Raw 或浏览器可下载的任何结果。PubMed 邮箱属于可追踪运行参数，`RunService.create()` 会将其冻结到该 Run 的 Plan；修改设置只影响新 Run。
4. 模型目录包括发行版默认的 `gpt-6.1-sol` 与 `deepseek-flash`；下拉中的其他选项来自仓库 `application/model_catalog.py` 的 **2026-09-17 快照**。这不是账号可用模型列表，也不意味着具备本次 G3 科学流程的调用能力。生产下拉需依角色、API 适配、模型权限和预算预检动态返回可选择项。
5. 后端预检应在用户明确触发时执行，不得用付费的生成调用假装无费用账户检查。Mock 模式无需密钥。选择自定义模型时不得悄悄改成默认模型。

## Config Builder

草稿请求建议拆为：

```json
{
  "goal": {
    "title": "...",
    "goal": "...",
    "required_causal_chain": ["..."],
    "required_outputs": ["..."]
  },
  "run_config": {
    "template_id": "continuous-g3-r2-default",
    "generation_model": "gpt-6.1-sol",
    "review_evolution_model": "deepseek-flash",
    "root_slots": 4,
    "reproduction_transitions": 3,
    "reproduction_slots_per_transition": 2,
    "risk_ceiling_usd": "60",
    "wall_minutes": 120
  },
  "mode": "MOCK_ONLY"
}
```

预检响应至少包含：`configuration_id`、`configuration_hash`、`runner_compatible`、`supports_full_terminal_evaluation`、`capability_checks[]`、`resource_checks[]`、`conservative_reservation_usd`、`user_risk_ceiling_usd`、`estimated_dispatch_bounds`、`diagnostics[]`。**不得直接把页面计算的候选槽位、费用估计当作可授权的预算计划**。不同代数可能需要更新 Supervisor 的代际规则、Ranking 工作量和连续恢复策略，不能仅修改 `reproduction_transitions` 字段。

## Leaderboard Read Model

建议每条投影返回：`hypothesis_id`、`title`、`claim_summary`（严格由原文派生，注明来源）、`generation_index`、`scientific_parent_ids`、`operator`、`mu`、`sigma`、`valid_decisive_matches`、`rating_status`、`created_sequence`、`last_rating_sequence`。按 μ 降序排已达到预设最低比较数的候选，未达标者分组显示。所有中间结果为临时榜单；仅原生 terminal barrier 的 `FINAL_WINNER` 是正式结果。

SSE 事件可以是 `run.status`、`candidate.created`、`rating.updated`、`ranking.evaluated`、`generation.completed`、`export.ready` 和 `runner.attention`，每条必须绑定 source sequence；禁止以 UI 动画完成代替真实事件。

## 错误、权限及一致性

- Run 执行进程应独立于 HTTP 请求，浏览器关闭不能停止任务；每个 Run 至多一个驱动。需要 durable job 管理和启动幂等键。
- 状态机返回明确权限和允许操作集合，前端依此启用/禁用按钮。
- 配置失败 `422`；身份/并发冲突 `409`；正在生成快照 `409/503` 可重试；服务器授权失败 `403`。
- 0.1.1 的 `trace_snapshot` 可检测数据库、ledger、artifact 并发变化。导出冲突应提示“忙，请稍后重试”，不应判定科研任务失败。
- Web API 必须绑定安全数据根目录和用户权限；禁止目录穿越、任意绝对路径和直接的数据库 URL。
- 原始 Trace 可能包含个人或未发表研究数据，生产下载必须带访问控制与审计。
- Web 观察服务建议独立包部署，避免变动已冻结 Run 的 `code_identity()`。旧 v0.1.0 Run 继续依其原环境恢复。

## 非目标

本阶段不包含专家干预、在线多用户协作、实验有效性认证、跨版本直接继续旧 Run，或对旧 Cockpit 进行隐式兼容映射。
