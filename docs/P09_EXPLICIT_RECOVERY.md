# 原P09同Task的一次显式恢复

本轮起点main `9dfd07e8b690a907fce46479fec2f09a3686a572`。PR17/18固定head分别合并为`468386cdbbf9d25d201d726c1e3084514225def9`与`9dfd07e8b690a907fce46479fec2f09a3686a572`；只解决STATUS冲突，保留两份事实，运行代码与已审查PR18相同。

限定试跑库仍为`/private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite`，固定准备包不变。
仅支持Task `250e3e6dea7a430fb07e71080c20a345`、原Attempt `da49fb3eb36c4e8aadee6f34e0757d15`、request-id `p09-real-nonprod-single-v1`。
不是通用重试开关，不支持P08/P10或其他Run；不创建新Task/Run，不允许数据库副本。

1. 只读验证包/数据库路径、准备哈希、Goal/候选/完整消息/实际请求/Prompt/政策/用途/模型配置；原响应存在时拒绝新POST，先人工检查已有证据。
2. 必须显式接受原执行/收费未知、重复执行/收费及store=true，并另外给出paid-post授权。缺任一项不写授权、不读凭据。
3. 同一Store排他锁下保存唯一`p09_single_retry_reserved`事实，并调用M15 `authorize_uncertain_retry`；授权与事实一起提交，原Attempt只增加retry_authorization，状态/错误/请求/未知usage不改。
4. 调用现有`retry_task`恢复同Task执行资格。仅Review的窄授权钩子允许原Attempt进行一次追加；M15沿用responses.submit、原target/完整请求，新Attempt的previous_id为原Attempt。
5. “一次已使用”由已提交的第二条Attempt事实判定；在提交前崩溃可以继续同一授权，提交中崩溃则只按Task范围将第二条in_flight转uncertain，不会第三次POST，不全局恢复其他任务。
6. 已有ID时仅供现有显式query-p09查询；已保存终态响应可以无凭据本地应用。成功不重发，失败/截断/再次uncertain均停止。
7. 普通submit-p09仍拒绝已有Attempt；P08默认拒绝重发逻辑不变。P10仍要求同候选真实completed/pass及完整Responses/M15来源。

```sh
# 本轮明确授权的专属命令；不是日常重试模板，不得在其他库/身份上替换使用。
PYTHONPATH=src python -m co_scientist_next.review_trial recover-p09 \
 --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
 --package docs/preparations/candidate-review-real-trial/package \
 --original-attempt da49fb3eb36c4e8aadee6f34e0757d15 \
 --authorize-paid-post --accept-unknown-prior-execution --accept-duplicate-charge --accept-store-true \
 --credential-env OPENAI_API_KEY
```

真实执行前：新增11项离线回归覆盖缺授权、改变请求、同Task同请求谱系、授权幂等/中断回滚、再次uncertain、提交中进程崩溃、已有ID跨进程只GET、保存响应后崩溃的本地应用、其他未解决调用不能放行。全量393通过、0失败/跳过。
UI仅标明P08调用历史与P09/P10独立审查Attempt及previous_id；无页面自动查询/发送。
完整请求不裁剪，gpt-6.1-sol/high/32768/JSON/无temperature/Responses后台/store=true/truncation=disabled/600秒/262144字节均不变。
每阶段人工授权的有界查询只在临时操作器运行，15秒间隔/60次/20分钟，不进入产品刷新或后台自动循环。
science_validated=false；不执行R1、检索、重新生成或修补候选。
