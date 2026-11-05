# Candidate Ethics／R0 真实试跑准备（未执行）

状态：**development／非生产、供总控审阅，未获得本轮真实发送授权**。真实模型执行方式与政策成熟度分别记录；真实调用不使本政策成为生产政策。
PR #15固定head `988aabd00743722ae9e622ffd7c519614dbbf15a` 经4项CI成功、无冲突/新增阻断后合并；实际merge及本轮基线 `d6e20cb1744ffad2e844d6ab5e23d9ad55c244e0`。
分支 `codex/candidate-review-real-preparation`，新PR保持未合并。本轮模型请求0、模型密钥读取0、science_validated=false。

## 政策全文和范围

[Candidate Ethics政策全文JSON](candidate-ethics-policy.json)、[R0政策全文JSON](r0-policy.json)、[显式决策配置](decision-policy.json)、[实际拟议用途](intended-use.txt)。
两政策版本为`2026-11-05-v1`，mode均为`development`；这些是本次非生产试验的待审提案，不冻结全项目生产枚举，不是组织伦理批准。

实际拟议用途：**仅用于非临床机制假说的阅读、评议与研究方法开发；不授权患者使用、临床决策、动物或人体实验，也不授权任何实际实验执行。**
该用途是本次P09的独立显式输入；原Goal内历史用途原样保留，不用编辑Goal/候选来迎合本轮用途，不继承Goal pass。

Candidate Ethics政策逐条含义（英文全文以JSON中text为准）：

1. **NP-01** 仅限本候选的非临床假说阅读/评议/方法开发，排除患者、临床、动物/人体和实际实验执行。
2. **NP-02** 独立审查完整候选、拟议干预/假设及实际用途，不继承Goal pass、不补造背景/审批、不改写候选。
3. **NP-03** 新因果桥、弱证据、迁移不确定或新颖性未知本身既不是伦理拒绝，也不应自动构成incomplete；科学问题交科学审查。
4. **NP-04** reject必须定位具体安全风险/用途或干预冲突，引用政策条款和候选/用途事实；概念验证描述本身不等于请求执行受限实验。
5. **NP-05** 安全风险判断的必要信息确实缺失时incomplete，说明缺失及作用；不能默认pass。无效输入/缺政策/API/解析错误属于执行问题。
6. **NP-06** pass仅允许此候选及冻结用途进入本次独立R0，不是组织伦理批准、科学准入、临床/实验许可或R1执行授权。
7. **NP-07** 保存条款、理由、风险和限制；真实模型不会升级非生产政策，技术失败不能变成伦理结论。

决策配置为`CANDIDATE-ETHICS-NONPROD-TRIAL-DECISIONS@2026-11-05-v1`：pass→continue、reject→stop、incomplete→hold。
R0沿用已实现政策：核心明确事实错误必须有可靠可见原文/定位/访问范围及不可缺少的核心性理由；结构门为目标、命题、逻辑和可检验性。
未知、争议、局部失真、弱证据、工具未落实、新颖性未知不自动阻断，记录required_R1_checks，不执行R1或修补候选。

## 原记录与隔离库

源库 `/private/tmp/co-scientist-p04-v2/runs/p04-v2-prepared.sqlite` 仅mode=ro读取/SQLite一致性快照，原文件字节哈希前后相同。
指定隔离试跑库：`/private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite`，**后续只使用这一份库**，不在备份或其他副本执行。

[来源清单](package/origin.json)记录源路径/哈希、Run/Goal/候选/原文内容哈希以及原各表行数/行集合哈希。
源Run `cea909fe8a004010b1896df1c1d98e02`、Goal `goal-38a4a7a321d54c1eb475b9c7646930f0`、生成引用`planned-p08-responses-migration-single`、
候选`planned-p08-direct-responses`保持同一科学身份，存储位置隔离。候选规范JSON SHA256：
`ba61dbc62315e7f5ad2cb360df4aa86da625a40df4b3dfc852d6effceb981fd9`。
完整5份实际来源视图、原Brief/Goal、P04/P05/P07、P08输出、旧两个uncertain及其未知费用均按快照保留，不新建Run绕过调用阻断。
没有用`review_fixture`导入器，也没有合成Goal或Candidate Ethics pass；Goal Ethics仍是源库中原先保存的开发测试事实。

只在隔离库新增准备事实，**没有P09/P10 Task、Attempt、Result或fixture pass**。不向原真实库写入任何测试/审查结论。
新服务仍验证已完成P08的既定窄迁移来源作用域，旧uncertain不改判，不全局放行其他未解决调用。
单库/单身份防常规重复，不宣称供应商绝对exactly-once；不得回滚到提交前快照后重发。

## 完整未发送输入

[完整P09请求](package/P09.unsent-request.json)、[P09实际USER](package/P09.actual-input.json)、[P10输入模板](package/P10.input-template.json)、
[冻结配置/Prompt/政策/身份](package/trial.json)、[SHA256](package/SHA256SUMS)。
准备哈希 `1890c42d8fdea5872f01018a7bb84f302a6ce9b5cc3022369f81647af9ce0951`。

P09使用完整保存候选、固定Goal、源Goal Ethics事实、本次显式用途/政策/decision_policy；无Codex REVIEW、评审答案或fixture Candidate Ethics结果。
完整actual_request为31644字节（现有适配器容量口径），低于262144；消息/材料不裁剪。
科学Prompt仍`w1-candidate-ethics-r0-v1`，P09/P10内容同时冻结；后续Prompt变化须重新审阅准备，不沿用旧包。

配置：[原样继承的公共模型配置](model-config.json)：gpt-6.1-sol/high/32768/JSON object；不传temperature；Responses后台、store=true、stream=false、truncation=disabled；socket和单HTTP总期限均600秒，容量262144。
原有store=true保留安排及组织例外见[传输说明](../../RESPONSES_BACKGROUND.md)；不承诺精确删除日期，不标生产政策。

P10模板内`passed_candidate_ethics_record: null`，`executable:false`。本轮没有完整可执行P10请求，也没有占位真实通过记录。
只有指定P09真实Responses completed且候选契约、pass、Run/Goal/候选内容、用途/政策绑定均成立后，才能组装：

- 从保存的真实P09 Result取passed_candidate_ethics_record，核对remote/M15成功Attempt、实际消息和原始响应，不能仅凭execution_mode标签。
- 固定Goal、不可变候选、5份原始可见材料和访问范围从同一快照冻结输入取值，不读Codex初审、卡片替代品或兄弟内容。
- 绑定该真实P09引用/结果哈希及原用途，加入冻结的非生产R0政策，构成P10五字段；组装完整消息后再查容量，超限停止，不裁剪。
- fixture pass、queued、incomplete/reject、技术/解析失败或无ID uncertain均不允许P10。真实模型执行不改变policy_mode=development。

## 本轮实际运行过的安全命令

以下prepare/inspect只读源库、只写指定隔离准备库/包，不接受凭据或模型执行授权。prepare拒绝已存在目标库，不重复运行覆盖：

```sh
PYTHONPATH=src python -m co_scientist_next.review_trial prepare \
  --source-db /private/tmp/co-scientist-p04-v2/runs/p04-v2-prepared.sqlite \
  --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
  --policies docs/preparations/candidate-review-real-trial \
  --package docs/preparations/candidate-review-real-trial/package
PYTHONPATH=src python -m co_scientist_next.review_trial inspect \
  --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
  --package docs/preparations/candidate-review-real-trial/package
```

本轮还实际验证了`assemble-p10`在缺少真实P09 pass时退出2且不生成输出，这属于预期门控，不是一次失败模型请求。

## 后续执行命令草案——本轮均未运行

**须由总控先确认本PR政策/输入和后续真实执行授权。** 最多1次P09 POST；仅真实P09 pass后，另行显式1次P10 POST。
各阶段只显式查询同一个已保存response_id，不自动轮询、不自动重试或切换；没有ID的uncertain立即停止。
以下使用既定`OPENAI_API_KEY`环境名；本轮未读取其值。凭据不进入请求包、材料或Git。

```sh
# 后续经授权：P09最多1次POST。已有Attempt时不重发，已有ID时只用query-p09。
PYTHONPATH=src python -m co_scientist_next.review_trial submit-p09 \
  --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
  --package docs/preparations/candidate-review-real-trial/package \
  --credential-env OPENAI_API_KEY --authorize-paid-post

# 后续经授权：一次GET同一已保存ID，无ID不会创建POST。
PYTHONPATH=src python -m co_scientist_next.review_trial query-p09 \
  --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
  --package docs/preparations/candidate-review-real-trial/package \
  --credential-env OPENAI_API_KEY --authorize-same-id-query

# 只在真实P09 completed/pass后可成功；本命令不读密钥、不发送。
PYTHONPATH=src python -m co_scientist_next.review_trial assemble-p10 \
  --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
  --package docs/preparations/candidate-review-real-trial/package \
  --output /private/tmp/co-scientist-candidate-review-trial/p10-assembled

# 后续经授权且P09真实pass：P10最多1次POST，不能拿fixture pass代替。
PYTHONPATH=src python -m co_scientist_next.review_trial submit-p10 \
  --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
  --package docs/preparations/candidate-review-real-trial/package \
  --credential-env OPENAI_API_KEY --authorize-paid-post
PYTHONPATH=src python -m co_scientist_next.review_trial query-p10 \
  --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
  --package docs/preparations/candidate-review-real-trial/package \
  --credential-env OPENAI_API_KEY --authorize-same-id-query
```

固定身份为`p09-real-nonprod-single-v1`及`p10-real-nonprod-single-v1`。CLI核对包/DB、Prompt/完整输入哈希，服务拒绝其他试跑request-id或改标production。
创建提交与每次查询均走现有M15，不隐藏底层重试；成功回放不重发，失败/截断/无效输出不能作为pass。
credential_configured可用性不参与试跑模型配置身份；端点/模型/参数/容量/存储等仍全部冻结并核对。

## 状态查看与边界

```sh
PYTHONPATH=src python -m co_scientist_next.workspace \
  --db /private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
  --port 0 --development-test \
  --review-responses-config docs/preparations/candidate-review-real-trial/model-config.json \
  --allow-development-review-policy
```

同库已有本地服务时复用它，勿并开Store。此查看命令不配置凭据、不授权调用；`--development-test`仅对应源Goal历史测试，
`--allow-development-review-policy`仅允许显式非生产政策，**不选择确定性替身**。旧`--development-review`仍明确选择fixture且不能与真实配置混用。
页面分别显示非生产政策、真实适配器未授权、审查记录0及P10条件；刷新不发送、不查询供应商。
页面整体改版不在本轮，只有必要标签/状态提示更新；R1、重生成、候选修补、新检索均未实现或执行。
[验证和截图](../../verification/candidate-review-real-preparation/RESULTS.md)。独立伦理/科学有效性、政策成熟度及真实P09/P10表现仍未验证，science_validated=false。
