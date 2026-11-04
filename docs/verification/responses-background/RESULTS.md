# Responses 后台传输验证

基线 db37b47598c167d586b743f51f6a078e3c2b0cf6；独立工作树 `/private/tmp/co-scientist-responses`。
Python3.11.4，解释器 `/Users/lemintea/Documents/co-scientist/.venv/bin/python`。
没有安装新依赖，没有加载真实模型凭据；真实模型/公共文献发送均0次。

## 执行命令与范围

```sh
PYTHONPATH=src python -m pytest -q tests/next
python -m ruff check src/co_scientist_next tests/next scripts/export_p08_responses.py
python -m ruff format --check src/co_scientist_next tests/next scripts/export_p08_responses.py
node --check src/co_scientist_next/frontend/generation.js
PYTHONPATH=src python scripts/export_p08_responses.py
PYTHONPATH=src python docs/preparations/p08-unexecuted/verify.py
git diff --check
```

最终新系统 **301 passed、0 failed、0 skipped**（267原有 + 34新增）。
包含原5项HTTP验收和新增1项后台HTTP，未排除HTTP测试。
首次无提权运行291通过/6失败，仅因沙箱不允许绑定本地端口；获准后297通过。
后续新增无ID HTTP错误、未知远端状态、完成后跨进程回放、终态等待时长及Python3.12 HTTPS参数兼容检查，最终301通过。
初期离线开发失败也发现并修正ID事务INSERT列数、测试顺序假设；以上均不涉及真实发送。
全仓Ruff（沿用CI的6处旧导入顺序豁免）、44文件format、JS语法、原P08准备包与新请求导出校验、diff检查通过。
最终日志保存为 [next-tests.txt](next-tests.txt)。

## 核心证据

- 精确 Responses HTTP 字段、无temperature、high/32768、六字段与原科学消息一致。
- ID与M15响应原子持久后才可能查询。独立子进程在ID落盘后 `os._exit`，新进程GET同ID，POST始终1次。
- 另一独立子进程在completed响应/usage落盘后退出，新进程只应用完整候选，HTTP为0；候选仍immutable。
- 中断的GET通过既有recover/authorize_uncertain_retry、同key、同请求与previous_id继续一次显式只读查询；无新POST。
- queued/in_progress不产生候选；failed/incomplete/cancelled、空正文/不完整JSON/错误契约拒绝候选。
- 未知远端状态但有ID保留ID；无ID提交为uncertain，未知用量为null；HTTP错误也不自动改判为可重发。
- 查询断连/身份错配不替换ID、状态或候选；显式查询才能发下一GET。
- 截断保留incomplete_details和32768输出/32760 reasoning_tokens夹具计数；不当真实消耗。
- 连接/响应头/读正文错误阶段、单调耗时、慢速正文总期限与凭据回显/异常保护均离线验证。
- 日志只含允许字段；真实原始两Attempt/Task/请求SHA256见inspection.json，执行前后完全不变。

## 页面验证（IAB，全部为独立离线夹具）

在127.0.0.1:63780，独立 `/private/tmp/responses-page-only.sqlite`：
打开已保存Run → 可见开发替身、固定Prompt、waiting_remote、resp_OFFLINE1、queued、已等待时间。
显式“查询同一远端任务”一次，注入断连 → query_failed，原ID/queued仍在。
完整刷新 → 相同两Attempt（提交succeeded+查询failed），没有新POST/GET、没有候选。
浏览器warning/error日志为空。

[页面文本](page-text.txt) · [局部截图](page-detail.png) · [完整页面](page-query-failure.png)。
该页面的准备/阅读/种子与传输全是标识明确的夹具，不属于真实Run结果。
API测试另做服务进程退出/重启，读取仍保留相同ID/错误/Attempt数。

## 未运行与限制

真实 Responses 提交/查询、实际网络代理路由、供应商留存/组织策略核查、本机Python3.12、旧G3全量回归均未运行。
后台模型行为/科学内容/真实候选、独立人工科学评审未验证；science_validated=false。
Python DNS阻塞无法保证被600秒硬中断；墙钟等待时间只供展示。
本PR只提供迁移方案，原两次uncertain仍阻断，未实现/执行授权迁移入口；不能将改API当相同请求重试。
