# 架构

这是已验证科研内核的可安装封装，不是重新实现 Agent。

`RunService / CLI → CoreRunner → Supervisor → Worker → AgentExecutor → NativeJSONProvider`
执行外部请求前经过 TaskBinding、fence、permit、预算和 BoundedTransport；
HTTP evidence durable capture 在 interpretation 之前，随后 domain raw、usage/accounting
和 Supervisor application 分别校验。SQLite 原生事件和原始 artifact 构成恢复来源。

科学流程：Directive Ethics → 4 roots 的 Query Planning V4（承接 V3）、PubMed、
Source Review V2、Sol Generation P1 → Candidate Ethics → Reflection → Ranking/TrueSkill。
G1–G3 使用累计合格池、UCB tournament、0.7 crossover / 0.3 mutation，每代 2 槽位。
R/P 区分、2-valid/6-focal、committed-match rating 顺序、UCB=μ+σ、最终 argmax(μ)
全部沿用原内核。safe redesign≤1、重复内容、失败不补位和 G3 barrier 同样保留。

Release 新包 `co_scientist.release` 提供命令、独立 Run 生命周期、文件锁和独立授权。
它不计算新的排名，不修补模型科学输出，不产生 fake authority（Mock 模式除外）。
`MOCK_ONLY` 与 `LIVE_SINGLE_DISPATCH` 计划不可互换；后者含原生显式 bounded retries，
“single dispatch”指每个独立 call/attempt 的一次 permit，不表示整个 Run 只能一次请求。

仅两项原运行代码部署适配：tokenizer resource URI 到实际文件的映射，
PubMed 联系邮箱从冻结 operator 设置接入。科学源代码其余保持逐字节相同。
运行中快照和终态导出分目录，以保留原生不可覆盖保护。

凭据只从执行进程环境注入，不存入 manifest 或日志。请求可能含私人研究内容；
输出不是公开匿名数据，操作人员应保护 Run 目录。
停止是操作控制，产生 PARTIAL，不改变科学评分或强行选择 winner。
