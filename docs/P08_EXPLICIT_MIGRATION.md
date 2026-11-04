# P08 窄迁移入口

基线main `df78cc8cf37eb6671d9b4842c7fbb6e04f6ff76d`；独立分支 `codex/p08-explicit-migration`，PR不合并。
仅 DIRECT、两次相同冻结请求的 linked uncertain Chat Attempts → 同Run的一个Responses后继Task。
本轮真实库只读预览，未实际迁移、未读取模型凭据、模型请求0次；science_validated=false。

## 操作与约束

1. `MigrationService.preview(run_id, proposal)` 只读，API为POST `/api/generation/migration/preview`（不写事实）。
   严格核对原Task/两个Attempts、同Run/Goal/seed/ready/packet、完整实际消息与科学输入。
   提供原行/冻结请求哈希、新配置/输入/消息哈希、原/新候选身份和替代关系、风险及完整未发送请求。
   非法跨Run/seed、输入/Prompt差异、非DIRECT、第三个原Attempt或已有结果均拒绝。
2. POST `/api/generation/migration/confirm` 需原proposal、preview_hash及四项明确确认：
   旧调用可能已执行/收费、接受重复执行/收费风险、接受store=true保留安排、创建不是付费授权。
   后端重新计算预览；陈旧/改动预览拒绝。`BEGIN IMMEDIATE`一次事务追加Run计划、Task、
   generation_action候选/请求身份预留、唯一迁移记录和确认事实。只改Run执行计划/状态，不改原Task/Attempt。
   source_task_id唯一，同源重复同预览返回同Task；换请求ID/候选/配置不能再创建第二后继。
3. 创建与发送分开，无HTTP、无Attempt、无候选结果。原两Task关系、四项确认和状态在页面展示；刷新只读。
4. 后继仍需单独的显式执行：原 `/api/generation/execute` 额外
   `authorize_migrated_execution=true`，且已有适配器必须已配置/授权，才记录本后继Task专属付费执行授权。
   页面有独立风险勾选和执行按钮，迁移确认不会调用执行API。本轮未对真实记录执行该步骤。
5. 每次继续，只为该后继Task验证并豁免**预览内原两个Attempt身份**；重新核对原Task/action/Attempt行哈希、
   后继身份/配置/输入/Prompt。旧调用保持uncertain；其他未解决调用仍阻断；普通生成仍不可用。
   不给原Task补retry_authorization，不标失败/已解决，也不允许迁移后继再链式迁移绕过新uncertain。
6. 后继使用既有Responses ID原子持久化、同ID显式查询和成功本地应用。无ID仍uncertain，无自动重发。
   进程中断后读取持久事实；完成响应已存时不发送，查询中断只显式GET同ID。
   候选通过原P08契约后仍为“已生成，待Candidate Ethics/R0”，不可变、非准入/科学验证。

迁移冻结配置只剔除 `credential_configured` 可用性标记，所有执行参数/存储选择均参与哈希；
这样无密钥准备后可单独注入密钥。旧action/请求中的原标记不改；普通非迁移任务仍使用原配置检查。
迁移/执行授权没有凭据字段，科学USER仍恰好六字段；除candidate_id_from_caller外完全相同，Prompt版本不变。
store=true标准保留及组织例外见[既有传输说明](RESPONSES_BACKGROUND.md)；本轮未核验实际供应商项目策略。

## 原真实记录交付（未迁移）

[只读预览](preparations/p08-explicit-migration/preview.json) ·
[完整新请求](preparations/p08-explicit-migration/new.actual-request.json) ·
[提议身份](preparations/p08-explicit-migration/proposal.json) ·
[读前后清单](preparations/p08-explicit-migration/export-manifest.json)。

原Task `c1119e1ab4ed431daca848c01811fc37`；两Attempt
`5ad8cea64b1146c7bf2eb80e194e0798`、`86948ac23ee2477cac992b24f6016796`。
原候选 `planned-p08-direct` → 提议 `planned-p08-direct-responses`，新请求身份
`planned-p08-responses-migration-single`。这是未确认提案，不是已创建/已执行身份。
原库前后SHA256 `4ffef4c2e8f257b7ff0e1a8c10332c09bef68176856837e095104c7cc4fc608f` 一致。

只读导出命令（不会初始化Store/更新schema、创建lock或加载模型凭据）：

```sh
PYTHONPATH=src python -m co_scientist_next.migration_export \
  --db /private/tmp/co-scientist-p04-v2/runs/p04-v2-prepared.sqlite \
  --run-id cea909fe8a004010b1896df1c1d98e02 \
  --proposal docs/preparations/p08-explicit-migration/proposal.json \
  --model-config docs/preparations/responses-background/model-config.json \
  --output docs/preparations/p08-explicit-migration
```

通过SQLite `mode=ro` / `query_only`，不复制原数据库。导出目录中SHA256SUMS可复核。
原实现文档PR#12中的“仅迁移方案”属于历史状态；本轮提供上述入口，不追溯改写旧试跑记录。

## 验证与限制

[执行结果及页面证据](verification/p08-explicit-migration/RESULTS.md)：328通过、0失败/跳过；
完整新系统回归、Ruff、47文件format、JS语法、原科学Prompt/输入未改校验。
测试覆盖重复/跨范围/输入差异、同源唯一、事务提交前后退出、历史保护、专属授权、恢复/不重复发送；全部离线夹具。
只支持本次结构的DIRECT双uncertain迁移；非通用重试/迁移平台，无新服务或新Run绕过。
真实迁移、实际Responses请求/供应商表现、模型/科学有效性、专家审阅、本机Python3.12及旧G3全量均未运行。
