# P08一次显式关联重试：再次uncertain，停止

用户在原DIRECT不确定、费用未知报告后明确要求“再次尝试”。本轮只授权一次关联重试，成功后才允许原计划中未执行的第二方式；实际重试再次uncertain，因此第二方式仍未提交或发送。

- 源应用main：db37b47598c167d586b743f51f6a078e3c2b0cf6。
- 原结果提交：f62e03408a677b7f13d75aac6030af06768f3593；原试跑文件原样保留。
- 本轮分支：codex/p08-explicit-retry，不合并；应用/Prompt/配置不改。
- 唯一执行数据库仍为原库，不在副本执行；页服务先停止释放Store锁，结束后以无凭据/未授权模式恢复。

## 原Task与新旧Attempt

Task c1119e1ab4ed431daca848c01811fc37；request-id p08-real-direct-single；candidate-id planned-p08-direct；call_key=model。
原Attempt5ad8cea64b1146c7bf2eb80e194e0798：仍uncertain、原错误/未知用量不变，只经authorize_uncertain_retry追加本次接受可能重复执行/收费的授权理由。
新Attempt86948ac23ee2477cac992b24f6016796：ordinal2，previous_id关联原Attempt，无进一步retry_authorization。仍uncertain，Run/Task blocked。

调用前只读确认原库没有匹配请求的完整保存响应。然后使用Store.recover/authorize_uncertain_retry/retry_task和原GenerationService.execute，没有直接SQL改状态、新建DIRECT Task或新Run。
完整冻结请求与原Attempt、已审查导出完全一致：Prompt w1-p08-single-v1；gpt-6.1-sol/high/32768/JSON object、无temperature、600秒、262144字节上限；实际145327字节，无裁剪。

## 本次结果

安全诊断再次为http_protocol / request_open / REMOTE_DISCONNECTED。没有取得可保存的HTTP响应、finish_reason、原始响应、usage或候选。原请求和重试是否被供应商执行/收费均未知，不能记0，也不判为科学否定。
本次driver单调计时156.412865秒；保存起止2026-11-04T13:54:41.732836Z至13:57:18.072574Z。600秒配置没有修改；本次连接关闭不是已确认的超时或凭据错误，不推测根因。

ASSUMPTION_STRUCTURED（p08-real-assumption-single / planned-p08-assumption_structured）仍只是已审查的导出，未创建Task、未发送。没有继续重试、修复输出、切换模型、检索、重跑P03–P07或其他下游执行。
没有候选可审阅，不能比较输出差异或方法优劣，科学初审/独立专家评审未开展，science_validated=false。

## 证据和检查

before.json是恢复前快照；direct.attempts.json完整保留两次调用及原始请求；retry-authorization.json记录风险授权和所用API；request-consistency.json/对应input/messages/planned-http证明冻结内容不变；runtime-audit.json逐行核对原库；direct.usage.json=null，不伪造响应文件。
两方式科学输入除mode/候选身份外相同；第二方式没有模型调用，不能将其计划请求称为实际发送。

受保护历史行哈希保持；原generation action不变，原Attempt仅授权字段改变。原工作区232项改动及暂存/status指纹保持。
页面后端GET确认1个generation action、2个uncertain Attempt、0候选、生成禁用；页面进程没有模型凭据/发送授权。浏览器自动复核本轮因控制工具不可用未完成，不沿用旧截图冒充新页面验证。

```sh
python docs/trials/p08-retry-real/verify_results.py
python -m ruff check docs/trials/p08-retry-real/verify_results.py
```

实际执行只读DB/保存事实对照、冻结请求/关联关系/历史哈希/凭据扫描、便携导出及解压检查。应用代码未改，267项新系统回归、旧G3、本机Python3.12、浏览器完整回归、科学有效性检查本轮未运行。
ZIP为docs/review-bundles/p08-retry-stopped.zip，附SHA256。后续如要恢复，必须另行显式授权最新Attempt；本轮不再执行任何模型请求。
