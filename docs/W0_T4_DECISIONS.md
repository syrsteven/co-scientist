# W0-T4 已接受修订与采用范围

日期：2026-11-03。依据 M00 Accepted 和本轮用户明确决定。
`docs/design/w1-method-v0.4-proposed/` 的七个文件原样保留为 Proposed；本文不把 W1 整包升级为 Accepted。
本轮只实施 Goal制备、目标筛查、M12条件推进、M15窄调用接入和最小页面。

## 1. P08 与完整示例一致性（仅文档）

采用后的完整文档示例：`docs/examples/w1-v04-adopted-worked-input.json`。
其 `TransportSeedModelInputRendering.example_rendered_user_message` 必须能直接解析成 JSON，
字段恰为以下六项，与本段采用的 P08 USER字段一致，不使用旧的扁平别名或混合组装：

| P08 USER字段 | 唯一组装来源 |
|---|---|
| goal_context | TransportSeedBackgroundPacket.goal_context |
| seed_brief | TransportSeedBackgroundPacket.seed_brief |
| readiness_record | TransportSeedBackgroundPacket.readiness_decision |
| actual_frozen_seed_background_packet | 完整TransportSeedBackgroundPacket，保留实际材料表示/上下文/限制 |
| mode | 调用方显式选择 DIRECT 或 ASSUMPTION_STRUCTURED |
| candidate_id_from_caller | 调用方分配的候选身份；文档使用SIM-TRANSPORT-v04 |

实际渲染为上述对象的 JSON，不拼接隐藏兄弟候选、评审 expected 或 NegativeControlsReference。
完整示例保留其来源转述/未执行/非科学验证声明；没有请求被发送到模型。
此处没有实现生成器或背景调研。

## 2. 单次生成方式的名称

仅用 `DIRECT`、`ASSUMPTION_STRUCTURED` 表示两种**单次**生成方式。
后者可在一次调用的公开产物中组织假设与可检验桥接；不能把一次调用称为已实现多轮迭代。
原提案中的旧名及描述保留为历史原件；采用后示例和本说明使用新名称。
没有依据工程测试宣称任何方法更优、真实独立分支已运行或科学效果已验证。

## 3. R0政策（记录，不实施）

R0保留明确事实错误初审能力：核心前提存在可靠依据支持的明确错误时可以阻断。
局部错误、争议和科学未知交给R1；不能以“尚未证实”自动阻断。
只有助手转述时，不以“原文明确反驳”为由作确定性阻断；模型记忆不能是确定性阻断的唯一依据。
须记录候选关键前提、证据及访问范围，不把摘要/转述谎称已读原文方法。
本轮没有R0执行器、事实判定器或R1任务，也不修改已保存候选。

## 4. Goal Ethics完成决定是二态

用户已决定：完成的Goal Ethics仅为 `pass/reject`，必须保存理由、政策标识/版本与实际政策文本。
待澄清、缺少政策、风险判断信息不足、输入无效、解析错误和调用失败都是准备/执行状态，不增加第三个伦理结论。
未完成的筛查记录没有decision字段；技术异常由M15/M12记录，不能伪装为科学未知或通过。
Candidate Ethics的决策空间不随该决定改变；本轮未实现Candidate Ethics。

## 5. 本切片的实际条件边界

Run计划只有 `goal.prepare.v1 → goal.screen.v1`。
prepared可创建screen任务；关键歧义不创建screen；只有完成的pass到达 `awaiting_background`。
reject到 `goal_rejected`；缺政策/待补风险信息/无效输出等保持各自执行状态；异常为failed或blocked。
没有背景任务、占位生成器或科研完成状态；背景调研必须后续真实接入后再讨论Generation。
刷新与后端重启均不调用recover或执行任务；只有显式POST恢复操作可处理未收尾事实。

示例政策和确定性适配器仅在显式开发测试模式启用；它们不形成生产默认政策或真实模型能力。
M00既定科学顺序不变。本实现验证工程保存、绑定与控制流，不验证伦理分类或科学有效性。
