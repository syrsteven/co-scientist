# P08 Responses 后台传输（工程切片，未进行真实请求）

基线 `db37b47598c167d586b743f51f6a078e3c2b0cf6`，分支 `codex/responses-background-transport`。
原科学 Prompt 仍为 `w1-p08-single-v1`，六字段 USER、材料、历史记录不改。
本轮模型调用 0 次，未加载已有凭据，science_validated=false；非科学/伦理验收。

## 官方依据与配置

2026-11-04 核对 [Sol 模型页](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
确认 Responses、high 与足够输出容量；
[后台指南](https://developers.openai.com/api/docs/guides/background)说明 background 提交后按 ID 查询；
[参数参考](https://developers.openai.com/api/reference/resources/beta/subresources/responses/methods/create)
说明 max_output_tokens 包含可见输出及推理 token，store=true 的标准保留至少30天（受数据保留例外影响），
truncation=disabled 超限失败而非删除输入。实际使用正常 `/v1/responses`，不加 beta 参数。

显式映射：messages → input（每个角色/content 原样）；reasoning_effort → reasoning.effort；
max_completion_tokens → max_output_tokens；response_format → text.format。
固定 gpt-6.1-sol/high/32768/JSON object，不发送 temperature，不启用工具/多轮/previous_response_id。
完整[未执行实际请求](preparations/responses-background/direct.actual-request.json)、
[配置](preparations/responses-background/model-config.json)、[哈希清单](preparations/responses-background/SHA256SUMS)。
离线导出命令：`PYTHONPATH=src python scripts/export_p08_responses.py`。

**存储选择是新配置，不能当旧授权延续。** 本实现只接收显式 store=true 与 retention_ack；
用于需要跨进程、人工间隔查询的场景。本地不自动清理材料/响应/usage；由操作者另行管理。
官方后台指南也允许 store=false，但仍为异步查询暂存约10分钟；本窄实现不支持此模式。
组织级保留例外/实际项目设置无法在本轮无请求核查中确认，不声称 ZDR 或准确删除日期。
采用此配置进行真实提交前，需另行确认供应商存储及保留安排。旧 Chat 请求 store=false 原样保留。

## 可确认的传输事实

[只读核查](verification/responses-background/inspection.json)列出当前 urllib 发现的脱敏代理配置、
两个原 Attempt 及 Task 哈希。当前未发现有效代理条目；不证明过去或宿主网络没有代理/中间层。
旧 urllib 使用默认环境/OS代理发现、禁跳转、无 SDK 重试；request_open 混合连接与等响应头。
两次仅确认 REMOTE_DISCONNECTED，无可关联响应/已知用量。不能据此确定网络、代理或供应商根因。
第一次只有墙钟时间；第二次驱动记录单调156.413秒，均不能反推服务执行或收费情况。

新适配器沿用 urllib 代理发现/系统 TLS 验证、禁止跳转，无隐藏重试。
connect 包括 DNS、TCP、代理 CONNECT（若有）与 TLS；request_send 为请求写入；waiting_headers
为等待响应头；response_read 为读正文。安全错误只含既定类别/阶段/错误码与有限非负单调耗时。
成功响应保存累计 connected_seconds、headers_seconds、elapsed_seconds；不打印密钥、原始异常或鉴权头。
完整请求/供应商响应只保存在 M15，不流入运行日志；凭据独立注入，已知凭据若出现在输入则拒绝，响应意外回显则脱敏并拒绝应用。

socket timeout 与 total_wait_seconds **分别显式设置600秒**，均是每次 HTTP 操作而非远端计算总时限。
总期限使用单调时钟、socket shutdown 看门狗及逐块读取检查，避免慢速持续响应无限延长。
Python stdlib DNS 解析不能强制中断：DNS 返回后检查期限，故不宣称覆盖 DNS 阻塞的硬性600秒退出保证。
页面跨重启的“已等待”使用UTC差值（并非单调计时、供应商计算时长或收费时长）；终态在最后观测时间冻结。

## 状态和 M15/M12 边界

1. 用户显式执行 → M15 `responses.submit` Attempt 持久为 in_flight → 至多一个 POST。
2. 可用 JSON ID 一旦识别，M15 成功响应/完整 usage 与 remote_generations ID 同一事务落盘。
   写盘失败保留 in_flight/blocked，不再发 POST。成功回放也重建 ID 关联而不发送。
3. queued/in_progress → Task/Run waiting_remote，无候选。未知/缺失状态但有合法ID → unknown，
   仍保留ID，可显式查询；不能认定正在计算或应用候选。
4. 仅显式 POST `/api/generation/query` 执行一次 GET `/v1/responses/{saved_id}`，M15另记每次查询。
   刷新、重启、执行按钮遇已有 ID 均不创建/自动查询。查询失败保留 ID、最近观测状态和失败记录；不改成提交 uncertain。
5. 查询过程中进程中断，可显式继续读取同一 ID：原 GET Attempt 通过现有 recover 转 uncertain，
   明确记录只读恢复授权，新 GET 同 key/请求并以 previous_id 关联。这是显式查询，不是生成 POST 自动重试。
6. completed 且完整非空 JSON、无 refusal/incomplete_details、候选契约/绑定合法，才应用不可变候选；
   停在“已生成，待Candidate Ethics/R0”。failed/incomplete/cancelled、空正文、契约错误均无候选，保留远端原状态/错误/截断原因与完整可获 usage。
7. POST 未获得可用 ID（含断连、非2xx、无效响应）仍 uncertain，不改成零消耗或自动重发。
   收到但无法定位的原响应可保留；没有收到的数据不能重建。GET 身份错配/HTTP错误仅为查询失败。

每次 HTTP 都通过 TaskCalls；响应上限16MB是防护上限，超限明确拒绝应用，不能声称保存了未接收到的其余字节。
完整 provider_usage 保留推理/缓存/总 token 等供应商字段；共享 Usage 投影 input_tokens/output_tokens，未知 cost/tool_units/null 不填0。
本切片没有后台轮询服务、队列框架、取消接口或第三方幂等保证。

## 历史迁移方案（**仅方案，本PR不执行/不提供绕过入口**）

原 Run `cea909fe8a004010b1896df1c1d98e02`，原 Task `c1119e1ab4ed431daca848c01811fc37`，
Attempt `5ad8cea64b1146c7bf2eb80e194e0798` 和 `86948ac23ee2477cac992b24f6016796`
均保留 uncertain、原冻结请求和未知费用。原第二次授权记录也不增补。
[原第二次交付分支的不可变材料](https://github.com/syrsteven/co-scientist/tree/f3f7c314a214cea24b3b26f930ad98d3982dede8/docs/trials/p08-retry-real)
供审查；本轮只读哈希不改变这些文件/库。

下一次需要总控另行确认：是否接受原两次重复执行/收费风险、采用新API及store=true保留。
届时先在同一 Run 增加明确的迁移决策事实，关联 source_task_id、两source_attempt_ids、
旧冻结请求哈希、新execution_config哈希、原六字段/Prompt一致性、候选身份与替代关系。
应使用**新的执行配置与新Task身份**（非原call_key相同请求的retry），原Task/Attempt不改判，
需要一个单独审阅的显式迁移入口处理此特定未解决调用的风险；不能直接改数据库状态或伪造已解决。
若更换候选ID，须明示其与 planned-p08-direct 的替代关系并重新导出唯一身份字段。
不新建Run/数据库副本绕过阻断，不宣称原服务未执行。新Task必须仍绑定原Run/Goal/seed/ready/packet。

**当前代码故意不接受此旧Task换API执行，也不允许创建新Task绕过uncertain。**
没有执行上述迁移，没有授权第三次请求。未解决历史的生产迁移仍待单独授权和窄入口实现。

## 启动与验证

使用现有Python3.11/3.12环境即可，无新依赖。只读配置启动（无密钥、无发送授权）：

```sh
PYTHONPATH=src python -m co_scientist_next.workspace \
  --db /path/to/operator-selected.sqlite --port 0 \
  --generation-responses-config docs/preparations/responses-background/model-config.json
```

本轮**不运行**带 `--credential-env OPENAI_API_KEY --allow-real-model-calls` 的命令。
不可对历史库直接换配置点击执行；固定配置检查和未解决调用阻断会拒绝。
真实供应商后台提交、实际代理路由、模型生成与科学有效性均未验证。
离线回归/页面证据与实际命令见[验证记录](verification/responses-background/RESULTS.md)。
