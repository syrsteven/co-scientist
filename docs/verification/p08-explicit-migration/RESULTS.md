# P08 显式迁移工程验证

基线df78cc8cf37eb6671d9b4842c7fbb6e04f6ff76d，独立worktree `/private/tmp/co-scientist-p08-migration`。
环境Python3.11.4，沿用 `/Users/lemintea/Documents/co-scientist/.venv/bin/python`，无新依赖。

```sh
PYTHONPATH=src python -m pytest -q tests/next
python -m ruff check src/co_scientist_next tests/next
python -m ruff format --check src/co_scientist_next tests/next
node --check src/co_scientist_next/frontend/generation.js
git diff --check
```

最终 **328 passed，0 failed，0 skipped**（301已有 + 27新增），含7项本地HTTP/重启检查，未排除HTTP。
[最终原始日志](next-tests.txt)。首次沙箱内321通过/7失败均为本地端口绑定PermissionError；获准后完整重跑328通过。
早期测试修正了跨Run夹具重复固定引用及缺失记录异常类型；没有真实库修改或模型调用。
全仓Ruff也按CI既有六处导入顺序豁免执行通过；47个新系统/测试文件format、JS、diff检查通过。

新增契约/工程验证：

- 预览零写入：源Task/两个uncertain、错误/实际冻结请求/未知用量保持；只读连接强制禁止写表。
- 全六字段仅候选身份改变，科学Prompt/科学输入差异拒绝；跨Run/seed/来源/ready/packet拒绝。
- 四项确认/预览哈希校验；同源同请求重复确认同Task；换身份不能重复迁移，候选身份预留全局唯一。
- 异常注入事务回滚；两个子进程分别在提交前和提交后`os._exit`，重启后要么完全未创建、要么完整存在；重复确认仅一后继。
- 迁移创建0新Attempt/没有付费授权；需另行显式后继执行授权和真实适配器配置，普通调用/其他未解决调用不豁免。
- 变更历史记录后专属放行失效；新Task不改原Task/Attempts/unknown费用。
- 在另一个子进程ID提交后退出，新进程仅GET同ID完成夹具候选；成功回放/失败/截断/无IDuncertain不自动重发，重复确认仍同一Task。
- 后继M15完整实际请求与preview.actual_submission相等；不包含迁移审阅/预期答案，来源关系另存。
- HTTP预览→不充分确认拒绝→充分确认→重复→刷新/服务重启：旧双uncertain及新ready/0Attempts保持，未付费授权的execute拒绝。

## IAB页面实测（独立夹具，不是原真实Run）

服务127.0.0.1:65340，数据库 `/private/tmp/p08-migration-page-offline.sqlite`。
原Task与两个unknown Attempt均为明确OFFLINE传输测试产生；没有真实模型密钥/发送。
只读预览显示源/新哈希、候选替代、store=true与重复收费风险；确认按钮须四项均勾选。
显式确认仅创建关联后继；未点击执行。整页刷新后仍显示旧两uncertain、新Task“模型尚未运行”、
后继没有Attempt/候选，单独执行授权不存在，付费执行按钮禁用。浏览器warning/error为空。
原预览/长区域截图导出为空白，已移除；只保留人工复核有效的完整页面和后继截图，预览本身由实际操作、HTTP及JSON导出验证。

[确认及刷新后全记录](page-confirmed.png) · [后继任务截图](page-successor.png) · [页面文字](page-text.txt)。

## 真实记录只读导出

[导出清单](../../preparations/p08-explicit-migration/export-manifest.json)记录原数据库前后SHA256一致，
迁移未执行、模型请求0、没有读取模型凭据。
原Task、generation_action、双Attempts的全行内容执行前后比较，以及数据库整体哈希复核通过；
原工作区232项文件内容/index/status指纹保持不变。

本轮未运行：真实迁移、真实模型/Responses调用、真实ASSUMPTION_STRUCTURED或下游科学流程、
科学/伦理有效性与独立专家评审、本机Python3.12、旧G3全量。science_validated=false。
