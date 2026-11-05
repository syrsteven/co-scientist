# 原P09显式恢复与条件式真实P10

PR17固定head `baa0240a34276123c9e823435674f94ba3716333`、PR18固定head `3a324cea29d9114527e68d7cbe548063513662bb`各4项CI成功且无新增阻断后依次合并。
PR17 merge `468386cdbbf9d25d201d726c1e3084514225def9`；PR18 merge/最终main基线 `9dfd07e8b690a907fce46479fec2f09a3686a572`。
唯一冲突为STATUS，保留两份交付事实；运行代码与PR18原样。合并后main的3.11/3.12 CI也成功后才执行恢复。
[合并与CI证据](merged-baseline.json)。独立交付分支`codex/p09-explicit-recovery`，本轮PR保持未合并。

## 真实结果

| 阶段 | 实际新请求 | 结果 | 供应方最终usage，仅每个ID计一次 |
|---|---|---|---|
| P09恢复 | 1次POST、2次同ID GET | completed / pass | input8611、output1541（含reasoning511）、total10152 |
| P10 | 1次POST、2次同ID GET | completed / proceed_to_R1 | input15668、output2018（含reasoning776）、total17686 |

本轮合计2次新生成POST、4次GET，没有重试/切换模型/其他科学调用。费用均未知；原P09及旧两次P08消耗继续未知，不填0。
cache_write/cached等完整provider_usage与原始响应逐次保存；[用量摘要](summary.json)按每个response_id最后累计usage选一次，不合计GET的重复观测值。
两阶段供应方均未返回finish_reason，交付记“未返回”/null，不补stop。Responses状态completed、无incomplete/error且模块契约通过，不等于科学验证。

[真实P09完整结果](P09/result.json) · [真实P10完整结果](P10/result.json) · [P09原始正文](P09/raw-final-body.txt) · [P10原始正文](P10/raw-final-body.txt)。
P09只允许development非生产政策及冻结用途的独立R0；P10只表示等待后续R1，本轮未执行R1，未科学准入、未评分、未做实验。
science_validated=false。

## 同Task恢复与冻结输入

- 唯一既定库仍为`/private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite`；没有prepare、覆盖、回滚或副本执行。
- [恢复前只读检查](pre-recovery-evidence.json)：原Attempt.response为空、无远端ID；已知本地响应导出亦无可验证完整响应。没有根据传输修复推测ID或重建输出。
- 原Task `250e3e6dea7a430fb07e71080c20a345`，原Attempt `da49fb3eb36c4e8aadee6f34e0757d15`保持uncertain，仅经现有M15新增retry_authorization。
- 新Attempt `69fa1539d29047608a2eb8178126b5eb`的previous_id关联原Attempt，同call_key=`responses.submit`、同target和完整request；原错误/请求/response/unknown usage字段均不变。[原行前](original-attempt-before.json) / [原行后](original-attempt-after.json)。
- P09实际完整请求31644字节，request规范JSON SHA256 `90b0dcdfb22ddb63b9037eb58d2b3899c26919ea60270a5d67c4fe922821b39f`，与原Attempt完全一致。
- P10仅在真实P09 pass和完整M15/Responses来源核验通过后组装，59369字节、包含同一候选/Goal和全部5份原文视图。[组装导出](P10/assembled-before-send.json)。
- 实际执行代码固定于`32abb8f89236ca262a4576d0adea9b506691b1c5`。[窄恢复入口及边界](../../P09_EXPLICIT_RECOVERY.md)，新增11项测试先通过、全量393通过后才执行。

准备哈希仍为`1890c42d8fdea5872f01018a7bb84f302a6ce9b5cc3022369f81647af9ce0951`。候选SHA256仍为`ba61dbc62315e7f5ad2cb360df4aa86da625a40df4b3dfc852d6effceb981fd9`。
配置与科学Prompt原样：gpt-6.1-sol/high/32768/JSON object，无temperature；Responses后台/store=true/stream=false/truncation=disabled；600秒及262144字节。
原Goal Ethics仍历史开发测试，不冒充真实伦理审查。真实模型执行与非生产政策成熟度分别记录。

## 记录索引与审阅

每阶段目录保存action/task、input、binding、messages、actual-request、request-record、每条Attempt与响应、供应方原始JSON/usage、解析结果、执行事实及有界查询日志。
P09 ID `resp_03168064b28562b1006aec5c6a23d087d1a90320f5cd85ba84`；P10 ID `resp_0638e667bacc3d37006aec5cdba82887d185e87622e30e4799`。
每阶段2次查询，间隔分别15.375秒、15.214秒；各自都在20分钟/60次上限内。终态即停止，未取消或重新创建远端任务。
`bounded-observer-used.py`仅为本次授权临时GET操作器原样归档，不是页面/产品自动轮询功能，也不应作为新的执行授权。
`prepared/`为历史冻结准备材料原样副本，其“未执行”描述的是准备时点；当前执行事实以本目录Result/Attempt为准，不得按历史README重新prepare。

[Codex初审，待独立人工复核](REVIEW.md)标明政策适用、未知/局部问题不阻断、来源和阴性覆盖限制。ANXA11诱导措辞及SUN1 leading to被原候选弱化的问题继续保留，不修补候选或原输出，未加入被测消息。
[原候选](candidate.json) · [5份实际原文视图与范围](source-views.json) · [固定Goal](goal-context.json)。只读既得材料，不新增检索。

## 页面与保护

[重启后截图](page/after-restart.png) · [可见文本](page/visible-text.txt) · [持久化证据](page/persistence.json)。
无凭据/无发送授权页面区分P08历史与P09/P10审查，显示原uncertain、新恢复Attempt/previous_id、真实结果、development政策及等待R1。
实际刷新2次并重启，所有逻辑表全行相同，39条Attempt无变化；没有供应商请求。SQLite文件hash可因Store启动写元数据变化，不据此谎称字节相同。
[历史保护](preservation.json)确认原真实库字节hash不变，原试跑库旧行仅允许Run状态/计划、原P09Task执行状态及原Attempt新增授权元数据变化；候选/原材料/旧P08 uncertain不变。
原工作区232项内容/index/status指纹不变。数据库、锁及凭据不进Git。

## 命令与检查

执行的恢复命令见[窄入口说明](../../P09_EXPLICIT_RECOVERY.md)。后续query-p09、assemble-p10、submit-p10及query-p10均使用[既定准备README](../../preparations/candidate-review-real-trial/README.md)命令，唯一库、固定request-id不替换。
现在已成功，所有对应提交只能回放，不能照抄命令再发新请求。

无凭据查看与离线包验证：

```sh
env -u OPENAI_API_KEY PYTHONPATH=src python -m co_scientist_next.workspace \
 --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite --port 0 \
 --development-test --review-responses-config docs/preparations/candidate-review-real-trial/model-config.json \
 --allow-development-review-policy
python docs/trials/p09-recovery-real/verify_bundle.py
```

[检查报告](CHECKS.md) · [文件SHA256](SHA256SUMS)。可下载ZIP及其SHA位于相邻`docs/trials/p09-recovery-real-review.zip`与`.sha256`；不含数据库/凭据。
独立专家审阅、伦理准确性/政策成熟度、机制有效性、R1/R2或科学准入未验证，不以单次输出宣称稳定改进。
