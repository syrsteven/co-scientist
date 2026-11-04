# 真实P08：DIRECT不确定停止，无候选

**DIRECT唯一新Attempt为uncertain；ASSUMPTION_STRUCTURED未执行。没有生成成功候选，无法开展科学初审或比较方法输出。science_validated=false。**

源main `db37b47598c167d586b743f51f6a078e3c2b0cf6`；独立结果分支 `codex/p08-real-trial-review`。应用代码/Prompt/原设计与历史结果不改，不合并main。

## 执行范围及原库检查

仅在原真实数据库 `/private/tmp/co-scientist-p04-v2/runs/p04-v2-prepared.sqlite` 执行，不在备份库或开发演示库发送。
Run `cea909fe8a004010b1896df1c1d98e02`；seed `seed-f87361b21b4f44609dedfa2ac9afc7bc-0`；readiness `directed-seed-p07-readiness-single`；packet `directed-seed-p05-packet-single`。

先只读查询原库目标任务：没有这两个request-id或candidate-id。随后既有Store做必要的追加式P08表初始化，未重写历史行。
本轮首轮预检与已验收 `docs/preparations/p08-unexecuted/` 完全一致：输入、消息、Prompt、配置、HTTP envelope和来源绑定均匹配。USER恰为6项。两方式除mode和候选身份外科学输入相同，未混入示例答案、审阅或兄弟候选。

| 方式 | 固定request-id / candidate-id | 完整请求字节 | 实际结果 |
|---|---|---:|---|
| DIRECT | p08-real-direct-single / planned-p08-direct | 145327 | 1次新Attempt，uncertain，停止 |
| ASSUMPTION_STRUCTURED | p08-real-assumption-single / planned-p08-assumption_structured | 145357 | 仅预检导出；0新Task、0发送 |

两份完整输入/消息/计划请求见对应文件。预检中的model_sends=0/credentials_read=false是发送前阶段事实；最终总计是1次真实调用尝试，并非成功调用。
Prompt `w1-p08-single-v1`；gpt-6.1-sol/high/max_completion_tokens32768/JSON object，无temperature，timeout_seconds600、max_request_bytes262144。没有裁剪、更改参数、自动重试、修复输出或切换模型。DIRECT凭据仅通过独立OPENAI_API_KEY读取，不写入记录。

## 不确定事实

Task `c1119e1ab4ed431daca848c01811fc37`；Attempt `5ad8cea64b1146c7bf2eb80e194e0798`，ordinal1、previous_id=null、retry_authorization=null。
安全诊断：`http_protocol / request_open / REMOTE_DISCONNECTED`。request_open涵盖连接/发送/等待响应头，不能据此证明请求没到达供应商。没有取得可保存响应，不是“空正文”或“JSON不完整”的模型返回，也不是科学否定。

HTTP状态、finish_reason、原始响应、完整usage、候选均不可得，保持null/缺失；不能伪造原始响应文件或将费用/token记0。供应商是否执行和收费未知。
原Task/Run blocked，候选身份只是已预留，**不是已生成候选**。第二方式按用户失败即停止规则未提交，不为完成两方式比较而绕过阻断。

记录时间：2026-11-04T10:03:07.776095Z至12:35:20.227391Z，时间戳跨度9132.451296秒，明显长于配置600秒。现有urllib timeout是socket操作超时参数，未设置独立整次deadline，且没有保存单调计时。此跨度不能单独证明实际根因（例如网络行为、调度或时钟变化），本轮不修改代码或重试。完整说明见 `transport-notes.json`。

## 历史保护与页面

只读原库逐行哈希核对原23Tasks/25Attempts/23Results、11背景动作、10文献动作、5视图、Goal/Brief及50原执行事实均保持；Run仅追加本次generation.P08计划并转blocked。没有重跑P03/P04/P05/P07、没有检索或其他下游模块。
原候选/响应不存在，因此没有不可变成功候选需要展示。页面展示已预留DIRECT身份及“发送不确定，已停止；不自动重发”，没有科学主张或假候选；生成按钮禁用。原库页面进程不载入模型凭据且未授权真实发送，刷新只读。
IAB打开原Run、刷新读回，仍仅1个生成动作/1个Attempt，无第二任务；截图与核对见 `docs/verification/p08-real/`。Goal Ethics仍为历史开发测试结果，不是真实伦理审查。

## 交付文件及离线检查

- `*.input/messages/planned-http/request/binding.json`：两种方式发送前与审查导出相同的材料；第二方式仅计划，不能称实际已发送。
- `direct.action.json`、`direct.attempts.json`、`direct.outcome.json`：唯一真实发送尝试、实际请求、来源绑定、安全错误和未知用量。
- `assumption_structured.not-executed.json`：停止原因；不创建伪Task/Attempt来填数。
- `runtime-audit.json`、`protected-row-hashes-before.json`、`run-before/after.json`、`facts.json`：原库只读审计及历史保护。
- `codex-review.md/json`：7项科学审阅标准全部无法评估。Codex只核对工程事实，科学初审未开展，不推断方法优劣。
- `SHA256SUMS`及 `docs/review-bundles/p08-real-stopped.zip` / `.sha256`：可移交的证据包，无凭据。

```sh
python docs/trials/p08-real/verify_results.py
PYTHONPATH=src python docs/preparations/p08-unexecuted/verify.py
python -m ruff check docs/trials/p08-real/verify_results.py
```

实际执行：审查包哈希/当前请求一致性、容量、原库已有任务、逐行历史保护、M15实际请求/状态/用量对照、仅1Attempt/第二任务不存在、IAB页面及刷新、导出/解压审计、原工作区232项保护。
应用代码未改，本轮未重跑267项新系统回归、旧G3回归、本机Python3.12或完整浏览器回归。没有科学输出可评审，独立人工/专家科学验收未运行。

后续若恢复，必须另外显式授权接受可能重复执行/收费，并沿原Task/call_key/冻结输入及既有authorize_uncertain_retry机制处理。本轮不执行该动作，不改判原Attempt、不新建Run/任务绕过blocked。
