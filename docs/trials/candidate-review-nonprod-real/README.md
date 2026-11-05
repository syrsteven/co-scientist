# 真实P09非生产试跑：提交不确定，P10未执行

PR16固定head `77a0aca200cb640d29d7f044d6773076476581b6` 重新核对4项CI成功、clean无冲突、无评论或审查新增阻断后合并。
实际merge/本轮main基线 `b677c7f94f588aa71c3f453a13620f4e6bb0ad6c`；独立分支`codex/candidate-review-real-results`，本轮交付PR不合并。

## 本次实际结果

**P09发送结果不确定，无response_id；没有完成的伦理决定。P10未创建、未组装、未发送。**
严格按授权停止，没有重试、切换模型、查询未知ID、重生成、检索或R1。
唯一提交发生于2026-11-05 16:53:14.114722（Asia/Shanghai），M15结束于16:53:16.767239；单调耗时2.649582998秒。
错误允许列表记录`transport / response_read / TRANSPORT_ERROR`；根因未知，不能断言是模型拒绝、超时或供应商未执行。
没有保留下来的完整响应，因此原始响应、provider usage、解析结果、finish_reason均为null；不是人为补造`stop`或零用量。
POST尝试次数1不等于供应商执行次数已确认。供应商可能已执行和收费。

[完整摘要](summary.json) · [冻结请求](P09/request-record.json) · [实际HTTP配置和body](P09/actual-request.json) · [完整实际消息](P09/messages.json) · [实际输入](P09/actual-input.json)。
[Attempt原记录](P09/attempt-row.json) · [安全错误](P09/error.json) · [完整可得usage](P09/usage.json) · [执行授权/发送事实](P09/execution-facts.json)。
[原始响应：未取得](P09/raw-response.json) · [provider usage：未取得](P09/provider-usage.json) · [解析结果：不存在](P09/parsed-result.json) · [P10未执行原因](P10/not-executed.json)。

固定身份：

- Run `cea909fe8a004010b1896df1c1d98e02`；候选`planned-p08-direct-responses`。
- 请求`p09-real-nonprod-single-v1`；Task `250e3e6dea7a430fb07e71080c20a345`；Attempt `da49fb3eb36c4e8aadee6f34e0757d15`，status=uncertain，未改判。
- 准备包SHA256 `1890c42d8fdea5872f01018a7bb84f302a6ce9b5cc3022369f81647af9ce0951`；候选SHA256 `ba61dbc62315e7f5ad2cb360df4aa86da625a40df4b3dfc852d6effceb981fd9`。

模型配置未变：gpt-6.1-sol/high/32768/JSON object，无temperature；Responses后台、store=true、stream=false、truncation=disabled；socket/总期限600秒、262144字节上限。
实际请求31644字节，与已审查完整导出相同，无裁剪。政策仍`development`/非生产，真实执行标识`real_model`；模型请求不使政策成熟。
本次没有GET，观察窗口和15秒间隔未启动，因为没有可查询的ID。无重复GET usage可累计；费用及token全null，历史未知消耗亦未计0。

## 指定数据库与历史

唯一试跑库仍为`/private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite`，没有重新prepare、覆盖、回滚或副本执行。
仅inspect验证后执行既定入口；本轮原真实库只读哈希核对，字节仍为`a1414816be01c06535e9493f9eaa62d40ee892ad45cf024af61dc7776ab7a2b9`。
[历史逐表保留对照](preservation.json)确认原试跑快照全部旧行不变，唯一Run的plan/status允许随本次P09执行变化；候选、Goal、来源、P04/P05/P07及旧两个P08 uncertain行不变。
原工作区232项内容、index、status指纹不变。没有数据库、锁文件、凭据或鉴权头进入Git/审阅包。

[候选原文](candidate.json) · [固定Goal](goal-context.json) · [实际5份来源视图及范围](source-views.json) · [冻结政策/用途/Prompt/配置副本](prepared/package/trial.json)。
`prepared/`是当时准备材料的原样导出，只供审计；其中“未执行”的文字描述的是历史准备时点，本次实际状态以summary/Attempt为准，不能重复prepare执行。

## 实际执行命令

在独立工作目录，使用现有conda coscientist Python3.12.11；凭据仅由现有入口从OPENAI_API_KEY读取，不打印、不写Git：

```sh
PYTHONPATH=src python -m co_scientist_next.review_trial inspect \
  --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
  --package docs/preparations/candidate-review-real-trial/package
# 以下本次已执行过一次，禁止照抄作为重试；已有uncertain且无ID，停止。
PYTHONPATH=src python -m co_scientist_next.review_trial submit-p09 \
  --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
  --package docs/preparations/candidate-review-real-trial/package \
  --credential-env OPENAI_API_KEY --authorize-paid-post
```

inspect在提交前后均已执行并验证冻结包；所有query-p09、assemble-p10、submit-p10及query-p10本轮均未运行。

## 页面、审阅与离线复核

[Codex初审，待独立人工复核](REVIEW.md)说明无响应情况下可核实的输入与未验证项，不编造伦理/科学判断。
[无凭据页面重启后截图](page/after-restart.png) · [可见文本](page/visible-text.txt) · [持久化证据](page/persistence.json)。
页面显示真实适配器、非生产政策、1条审查尝试、无ID停止；没有R0结果。刷新2次并重启服务后全部33条Attempt行相同、无新增供应商请求。
试跑库文件哈希在服务重启时改变；Store启动含SQLite初始化，不以字节一致作为此项证明。原真实库字节未变。

查看命令不含凭据或发送授权：

```sh
env -u OPENAI_API_KEY PYTHONPATH=src python -m co_scientist_next.workspace \
  --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
  --port 0 --development-test \
  --review-responses-config docs/preparations/candidate-review-real-trial/model-config.json \
  --allow-development-review-policy
python docs/trials/candidate-review-nonprod-real/verify_bundle.py
```

[检查结果](CHECKS.md) · [文件SHA256](SHA256SUMS)。审阅ZIP和其SHA256位于相邻`docs/trials/candidate-review-nonprod-real-review.zip`及`.sha256`，包含本目录全部脱敏证据，不含数据库/密钥。
science_validated=false；真实P09判断质量、真实P10表现、政策成熟度、独立专家审阅均未验证。没有因失败修补政策、科学Prompt或原候选。
