# P07同Task授权恢复与安全传输诊断

**恢复成功：原Task返回ready，原Attempt仍uncertain。Codex初审，待独立人工复核；science_validated=false。**

PR基线为重新核实的远端main `378475b2e5a86d1c6504138bc3992dae2c977e81`，诊断代码提交 `909107b7a00227e70ed11f8cff1e1ab2d4eb385a`；分支 `codex/p07-transport-recovery`，保持未合并。
本PR基于main，仅纳入4个代码/测试文件和本次恢复证据；旧背景试跑记录仍原样保留在[原结果提交fcf2cf9](https://github.com/syrsteven/co-scientist/tree/fcf2cf98abc8e0a2f9ada7b53a28cd81e1c93936/docs/trials/directed-seed-background-real)，不重写原包。

## 原状态检查

Task `55bc66f3e1a44070babcf67db99b0bac`，原Attempt `0d9e7d5fd9da4bbea3ddc42608e0c184`，Run `cea909fe8a004010b1896df1c1d98e02`，seed `seed-f87361b21b4f44609dedfa2ac9afc7bc-0`。

只读检查原库中完全相同请求的Attempt及20个已知试跑/响应文件，未发现可关联的完整响应；没有扫描凭据文件、原始应用日志或会话记录。检查范围、路径和哈希见 `unassociated-response-inspection.json`。这是限定范围的本地检查，不证明供应商未执行或未收费。
原状态/冻结配置/调用事实见 `before.json`。原Attempt仍为uncertain、response=null、原错误不变、各用量null；只通过既有授权方法追加retry_authorization，不将其改判失败、成功或0消耗，也不事后猜测传输错误类别。

## 最小诊断补丁

`reading_model.py`把credential-bearing传输异常转换为固定消息加3字段：`category`、`phase`、`code`。字段按固定类型/允许列表生成，URLError仅在reason为异常对象时解包，绝不格式化原始异常文本。分类覆盖timeout/connection/TLS/DNS/HTTP协议/通用传输；阶段为request_open、response_read、response_metadata、response_close，缺省unknown。安全码如ETIMEDOUT、ECONNRESET、CERTIFICATE_VERIFY_FAILED、INCOMPLETE_READ，未知码归TRANSPORT_ERROR。

`contracts.py`的TransportUncertain只投影允许字段，额外字段、任意文本/代码丢弃；`calls.py`仅对该类型保存固定错误记录。原始异常字符串、鉴权头、密钥和请求正文不进入**诊断记录**；既有M15实际请求/响应记录仍按原要求保存。本补丁不建日志服务，不改Prompt/模型配置、成功回放、费用未知、uncertain/授权或自动重试语义。

request_open涵盖urllib建立连接、发送和等待响应头，不表明“尚未发送”；任何分类仍是uncertain，不赋予安全重发保证。旧错误没有可恢复的原始分类，新成功也不说明原失败原因。

## 实际恢复

本次用户明确授权接受原请求可能已执行、重复执行及重复收费风险。仅调用：

1. Store.recover(run_id)：新runtime读取现状，不重新发送。
2. Store.authorize_uncertain_retry(原Attempt, 明确风险授权理由)。
3. Store.retry_task(同一Task, 恢复理由)。
4. BackgroundService.execute(原request-id)：最多1个新Attempt，无直接SQL改状态或新建Run/Task绕过blocked。

新Attempt `a283b83163334165a902a00362b49c2d`，ordinal=2，previous_id指向原Attempt，call_key仍 `model`。新Attempt无进一步retry_authorization。
完整call request、HTTP envelope、消息、冻结输入、Prompt版本、model_config和target均与原Attempt完全相同，见 `request-consistency-before-send.json` 及 `attempts-after.json`。实际148027字节≤原冻结262144上限；没有裁剪、改上限或改模型参数。

配置gpt-6.1-sol/high/max_completion_tokens32768/JSON object、无temperature、600秒；Prompt `w1-l2-p03-p07-v1`，密钥仅独立环境变量OPENAI_API_KEY。不复制密钥或鉴权头。

HTTP200，finish_reason=stop，完整JSON，M15 succeeded，P07结果saved、decision=ready。新调用输入40396、输出3224（其中reasoning876）、total43620；完整供应商usage含返回的缓存详情原样保存。原Attempt所有消耗仍未知，因此两次尝试的完整总量及费用未知，不把原消耗算0。

没有重跑P03/P04/P05，没有新增检索/获取/视图；Run1/Task23/background actions11/literature actions10/views5数量均不变。受保护的历史行逐一哈希保持。系统状态awaiting_generation只是实际能力边界，未执行P08、Candidate Ethics或R0。

## P07逐项依据与初审

输入仍为原39张卡、5个原文视图、既有实际搜索和SeedBackgroundPacket。`input.json`、`frozen-seed-background-packet.json`是原冻结输入的可读导出，不是重跑P05。`frozen-call-request.json`和`frozen-http-request.json`保留实际请求，`messages.json`保留完整消息。

[readiness-evidence-and-review.md](readiness-evidence-and-review.md)逐项列出6个met=true的模型判据、原始why和实际record_refs；JSON版将每个引用解析到原卡/原文字符范围、固定Goal/seed、实际查询或背景包。原文/作者解释/模型判断分开。

模型允许的具体程度限于条件性探索：不预选分子/模型、不把核孔蛋白磷酸化及ALS因果桥当已证事实、不保证实验参数/可行性/新颖性。未知桥接没有被要求先证明；“近邻检索尝试过”没有被写成穷尽或全球没有证据。

Codex初审仍指出：P05弱化ANXA11作者诱导及SUN1“导致相互作用降低”的措辞，既有TDP-43体系归属也待复核；P07未主动指出这些问题，因此其ready不是独立阅读准确性或科学有效性验收。原输出不改，Goal Ethics仍为明确开发测试结果，不冒充真实伦理审查。

## 检查与交付文件

- `before.json`、`facts-before/after.json`、`task-after.json`、`action-after.json`：恢复前后及授权/任务恢复事实。
- `attempts-after.json`：新旧关系、冻结请求、响应/错误和用量；原Attempt只有retry_authorization变化。
- `original-response.json`、`model-content.txt`、`usage.json`、`parsed-result.json`：完整新响应、原始内容、完整usage和解析结果，原始字节hash在Attempt中。
- `runtime-audit.json`与`protected-row-hashes-before.json`：只读数据库对照、历史记录保护及无新科学任务/检索。
- `readiness-evidence-and-review.*`与`source-finding-map.json`：6项依据及调用后Codex初审，未进入模型输入。
- `SHA256SUMS`：本目录文件哈希；`docs/review-bundles/p07-recovery-real.zip`附独立SHA256，可解压后审计。

使用现有Python3.11.4环境，不新增依赖或强制建venv：

```sh
PYTHONPATH=src python -m pytest -q tests/next/test_transport_diagnostics.py tests/next/test_reading_model.py tests/next/test_background.py tests/next/test_runtime.py
PYTHONPATH=src python -m pytest -q tests/next
python -m ruff check src/co_scientist_next tests/next
python -m ruff format --check src/co_scientist_next tests/next
python docs/trials/p07-recovery-real/verify_results.py
```

实际结果：聚焦102通过；最终新系统239通过、0失败/跳过（原203+新36）。新增离线测试覆盖四传输阶段/敏感异常、任意代码/字段丢弃、同Task授权恢复、新runtime不重发、previous_id/请求一致、原uncertain保留、成功回放及截断/再次不确定停止。最终src/tests Ruff检查、35文件format通过；便携导出/ZIP解压、只读DB对照、凭据扫描、原工作区232项保护通过。日志见 `docs/verification/p07-recovery/`。

未运行旧G3全量、本机Python3.12、浏览器、独立人工/专家审阅或科学有效性验证。新真实调用只有本次P07一次，不用于证明诊断分类的真实世界覆盖率；诊断类别为离线替身验证。
