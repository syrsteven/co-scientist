# Strict v2真实验证

## 单次兼容性测试

2026-09-21使用deepseek-flash，thinking enabled、reasoning_effort low。独立固定晶状体anchors测试，不计入科研Run或Elo。

- 001：连接失败（ConnectError），没有收到响应或usage。保留目录`.co-scientist-probes/ranking-strict-v2-20260921-001`。
- 002：获得网络访问后一次请求返回HTTP200，完整严格参数解码、领域schema及内容绑定校验通过，结果needs_tiebreaker、winner=null。
- 用量4671输入+6061输出=10732 tokens；金额未定价，不能当成免费。
- 原始响应31323字节，SHA256 `ea98e66bf2b02d12d9cb79e64c597d56375bf7a664b2d171412e57c2e0e42364`，保存在`.co-scientist-probes/ranking-strict-v2-20260921-002`。
- 单次通过只能证明此请求兼容，不代表输出可靠率或科研质量提高。

## 常规完整流程

Run `lens-deepseek-strict-v2-20260921-011`，数据目录`.co-scientist-deepseek-strict-v2`，配置`configs/profiles/core_preview_deepseek_strict_v2.yaml`。

新运行采用strict-tool-v2与capacity-v2，保留40调用、6候选、12场比较上限，Meta-review最多2轮，Evolution最多3轮。候选达到上限后可继续处理已有候选；其他预算维度保持硬停止。旧运行不升级。

运行在08:44:34至08:51:18（Asia/Shanghai，约6分44秒）实际执行，最终为`needs_attention / meta_review_requires_scientist_input / SEQ174`。没有进入stopping/finalization，完整闭环尚未通过。

共26次外部调用及26条费用记录，全部domain_result_applied；其中24次DeepSeek、2次PubMed。输入249667+输出80841=330508 tokens，加独立成功probe共341240 tokens；金额未定价。

实际阶段：Generation 1、Reflection 12、Evolution 2（准入修复，共3子代）、Proximity 2、Ranking 6、科学Meta-review 1、PubMed 2。6场Strict v2比较均通过本地校验，本次无模型输出解析失败。

候选池由3初始+2子代+1子代达到6上限。最后一个子代在SEQ90创建，随后完成initial/full review，于SEQ114准入并参加排名，验证了capacity-v2达到上限后仍处理已有候选。只有2个科学候选获准入，另有2个固定anchor；不能把6候选当成6个合格假设。

Meta-review在SEQ172发布反馈，将`safety_direction_check`判为`insufficient_evidence`，Supervisor在SEQ174暂停。反馈主要提出机制证据外推、时序/细胞谱系证据不足、比较覆盖窄，以及部分full review的safety_status为not_assessed。注意：对应候选的initial review安全检查均为passed，不能直接把full review未再评安全解释为已证实不安全或准入漏洞；这里存在Meta-review与分层审查职责是否一致的待核查问题。反馈要求比较未准入候选也必须受准入规则约束，不能直接执行。

本轮没有反馈驱动Evolution（名额已在准入修复阶段用完），未完成最终总结；不能声称论文性能复现或端到端成功。下一步应核查Meta-review是否混淆“新假设尚未有直接实验证据”和“安全证据不足”，并明确人工科学反馈入口，不能简单改clear或绕过暂停。

## 证据核验

独立导出：`lens-deepseek-strict-v2-20260921-011-export`。原始raw与按artifacts.json定位的导出raw均26/26 SHA256核验通过；release invariant审计0违规。工程审计不等于科学质量评估。

未修改009/010，未自动重试、追加预算或Git推送。配置与报告通过diff-check；本轮未重复全量离线测试。

## 后续离线诊断

准入实现从内容绑定的initial review读取安全状态（domain/admission.py）；因此full review的not_assessed并不独立撤销初审安全通过。011的原反馈缺少显式准入上下文，称未参赛候选比较覆盖不足，也没有解释这些候选为何尚未准入。现有证据支持“提示说明及上下文存在歧义”，不支持直接宣称全部安全疑问无效。

为新运行增加可选meta-review-loop-v2，区分机制待验证与安全信息不足，附带内容绑定审查记录和当前epoch准入事实；不改变旧反馈、不取消非clear暂停。驾驶舱增加只读人工核查入口。v2反馈协议尚未做付费模型验证，也未实现同Run人工科学改判提交。
