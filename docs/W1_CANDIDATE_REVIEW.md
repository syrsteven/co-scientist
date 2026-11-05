# Candidate Ethics／R0 最小切片

起点：PR #14 固定head `cd815066dba167fc6c7faa016226719c7fe468be`，4项CI成功、无新增阻断/冲突后合并。
实际merge及开发基线 `c90ce9365fa3c90f25e52bb77ee9fc551073a669`；新分支 `codex/w1-candidate-ethics-r0`，新PR不合并。
原工作区232项与原真实库保持；本轮真实模型请求0、不读取模型密钥、science_validated=false。

## 本轮采用的语义

M00固定Candidate Ethics→仅通过才R0→R1的顺序，不固定Candidate Ethics完整决策枚举。
接口图的通过/拒绝/技术未知是状态轴；历史M01/M02提案的pass/reject/incomplete不是Accepted生产枚举。
Goal的二态决定不扩张到Candidate Ethics。本切片要求每次显式`decision_policy={id,version,routes}`：
仅`pass:continue`，其他已配置值只能`stop`或`hold`。开发示例明确采用pass/reject/incomplete三种，
分别继续/停止/待补充；不是冻结生产全局枚举。调用失败、无效输出、缺政策、缺决策配置、未配置模型均是执行问题，无伦理决定。
只有真正completed且同候选绑定的pass允许显式建立R0；没有继承Goal pass，也没有自动执行下一步。

政策必须显式提供`id/version/mode/text`，没有生产默认值或自动开发兜底。
声明production是操作者提供政策的范围声明，不代表系统替其认证政策已获组织批准；组织政策管理不在本轮。
开发政策只在显式development_review启用，开发适配器不能产生production决定，开发pass不能放行production R0。
拟议用途在P09独立显式提交并冻结，不由Goal pass推断；页面可编辑初始用途，改变用途必须重新P09。

P09/P10使用W1英文开发者Prompt原文加版本化最小结构补充，标识`w1-candidate-ethics-r0-v1`。
P10补充明确采用用户已接受的核心事实错误政策，覆盖旧Proposed仅限来源误表述的窄句；设计原件不改。
Candidate/政策/材料都置于USER数据，不得覆盖SYSTEM/DEVELOPER。没有Codex REVIEW、expected或评审答案字段。

## 后端与绑定

`CandidateReviewService`分别创建P09/P10 Task、冻结input/binding/config/version；新增一张窄`candidate_review_actions`表。
候选从已成功generation Result读取，检查同Run/Goal/候选身份/原输入及P08契约；不接收调用方上传的候选正文替换。
绑定候选内容SHA256（规范JSON）、用途SHA256、政策及decision_policy SHA256；P10额外绑定已完成P09引用及结果哈希。
每次执行/查询重新组装比对；跨Run、候选、内容、Goal、用途或政策的结果不得复用。成功结果幂等，不改候选、不产生修复身份。

P09 USER恰为：goal_context、fixed_candidate、goal_ethics_record、intended_use、approved_policy_id（含版本/mode）、approved_policy_text、candidate_ethics_decision_policy。
P10 USER恰为：goal_context、fixed_candidate、passed_candidate_ethics_record、actual_visible_source_views、r0_policy_version（完整配置）。
P10使用候选生成时真正冻结的原文文本、定位、访问层级、裁剪/未读范围；不是仅ID、卡片或助手综述。
只有实际取得的范围，不检索新材料，不把摘要/片段说成全文或已看图像。

R0输出包含candidate_id、disposition、goal_alignment、blocking_defects、scientific_unknowns、required_R1_checks、limitations。
只允许`proceed_to_R1/blocked`，非空阻断列表与blocked对应。缺陷必须定位候选JSON pointer及原句，说明不可缺少的核心性。
事实类`source_direct_contradiction/core_factual_error`还必须引用实际原文视图、半开字符区间、逐字quote、access及可靠性理由。
字符区间相对本次view.text，原文全局范围仍在view.character_range。助手转述、模型记忆、缺失/错位quote不能作为确定性事实阻断依据。
结构类为目标硬约束违反、无可辨命题、同情境必要关系矛盾或完全不可证伪，依据必须定位Goal/候选的实际输入。
未知桥接、无直接研究、跨情境争议、局部措辞、弱证据、未落实工具与新颖性未知不是阻断类别，交required_R1_checks。

这些是**可追溯性和输出契约检查**，不能机械证明来源可靠、矛盾成立、核心性或科学正确。该判断仍由评议者承担并需专家复核。
测试中的明确反例使用新身份`OFFLINE-FALSE-CORE-COUNTEREXAMPLE`，故意把原文“全部恢复剪接”写成“12D不能恢复”，
验证能保存定位阻断并保持候选不变；绝不是声称真实DIRECT候选存在该错误。

## M12／M15／恢复

明确操作链：已保存候选→显式P09→pass时awaiting_r0→显式P10→awaiting_r1或candidate_r0_blocked。
其他伦理结果按显式路由停止或hold，执行问题为candidate_review_problem。不会创建/执行R1、M03 Inventory、R2或Admission。
单进程Store和现有Scheduler按模块结果机械推进；模块负责解释结果，未建立通用工作流。

沿用TaskCalls/Attempt/Result及Responses远端ID表；只将原窄RemoteP08传输的operation按P09/P10记录，并以stage-specific finish应用审查结果。
成功响应先持久化ID再显式GET；queued/in_progress/unknown等待、completed且完整合同才应用，failed/incomplete/解析无效无审查决定。
提交无ID仍uncertain、不自动重发；查询失败保留ID，不创建新POST。完整请求/原始响应/可获usage、错误、previous_id沿用M15。
成功回放不发送；刷新/重启只读，不调用recover、执行或查询供应商。实际请求超出容量明确停止，不静默删材料。

已成功P08若来自显式迁移，审查操作只可验证并沿用**该生成候选的已完成迁移来源作用域**，豁免预览指定的旧Attempts；
每次校验原历史行/新生成关联，不修改旧uncertain，不全局解锁。新增的其他未解决调用仍阻断，反例测试覆盖。

## 页面与启动

候选主张、关键假设、区分预测直接展示；每份实际来源可展开原文/访问范围。
独立显示Candidate Ethics、政策/版本、理由/风险/缺少信息，以及R0问题、原文定位、科学未知和下一步R1事项。
调用/配置/usage等技术内容折叠；最新审查状态与候选历史分开；开发模式及替身声明始终可见。
显式创建/执行、已有ID查询、执行中恢复按钮均使用既有后端入口；没有自动轮询、刷新发送或隐式生产政策。

创建全新的隔离开发夹具（**只读取Git内公开试跑文件，不打开原真实库**；拒绝已存在DB并原子预留新文件）：

```sh
PYTHONPATH=src python -m co_scientist_next.review_fixture \
  --db /private/tmp/my-candidate-review-dev.sqlite \
  --trial-directory docs/trials/p08-direct-responses-real
PYTHONPATH=src python -m co_scientist_next.workspace \
  --db /private/tmp/my-candidate-review-dev.sqlite --port 0 \
  --development-test --development-review
```

夹具保留原候选身份/内容/源Run与Goal、来源视图；同ID仅用于隔离副本，以`development_candidate_import`事实和development_fixture_import来源标明。
不会导入原uncertain、远端任务或真实调用为可执行状态；Goal pass也是明确的开发夹具。禁止把此导入当原Run的真实审查或用于production政策。
界面点击“明确填入开发测试政策”，显式P09，再显式R0。可通过API独立保存请求和执行，不要求页面自动串联。

真实适配器后续只可显式使用`--review-responses-config <public-profile>`，另由操作者按既有独立凭据配置及授权决定是否发送。
本轮不运行带凭据/真实授权的命令。缺政策、缺模型/凭据/授权不会自动改用开发替身。

API：GET `/api/candidate-review?run_id=...`、GET `/api/candidate-review/attempt?attempt_id=...`；
POST `/api/candidate-review`（run_id/request_id/request），POST `/execute`（request_id/recover），POST `/query`（request_id）。
P09 request字段：operation/generation_ref/intended_use/policy/decision_policy；P10：operation/generation_ref/ethics_ref/policy。额外字段拒绝。

## 完整未发送请求与限制

[请求/输入/开发替身结果/哈希](preparations/candidate-ethics-r0-unsent/)：真实DIRECT候选内容SHA256
`ba61dbc62315e7f5ad2cb360df4aa86da625a40df4b3dfc852d6effceb981fd9`完全保留，P09/P10请求29504/53714字节。
使用既有gpt-6.1-sol/high/32768/JSON/no temperature、Responses background/store=true/truncation=disabled、600秒/262144上限渲染，**没有发送**。
P10包含已保存的开发替身P09 pass，绝不伪造production pass。生产政策/decision_policy待配置，原真实Run没有新P09/P10 Task或结论，不能拿开发导出直接宣称生产放行。
导出工具`python -m co_scientist_next.review_export --help`仅mode=ro、无凭据加载/联网，并校验实际候选、绑定及完整容量。

原P08中ANXA11诱导→相关、SUN1导致→伴随等措辞问题见[原初审](trials/p08-direct-responses-real/REVIEW.md)，没有修补原候选或注入被测输入。
开发替身仅检验工程，不能得出这些实际问题“已获R0认可/科学正确”的结论。
[运行验证与页面证据](verification/candidate-ethics-r0/RESULTS.md)；生产政策、真实P09/P10表现、独立伦理/科学专家复核、R1及完整科学链均未验证/未实现。
