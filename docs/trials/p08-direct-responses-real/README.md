# P08 DIRECT：真实迁移与单次 Responses 后台生成

2026-11-05，基线 `9f7ca42f5aca6344df2467faa08a569b483d800e`；分支 `codex/p08-responses-real-single`。独立PR不合并。
本次用户单独授权同Run唯一迁移、接受旧两次可能执行/收费及重复收费风险、store=true保留安排，以及后继一次真实POST和有界同ID查询。未执行ASSUMPTION_STRUCTURED或任何下游科学模块。

## 实际结果

- 原Run `cea909fe8a004010b1896df1c1d98e02`，原Task `c1119e1ab4ed431daca848c01811fc37`。
- 后继Task `175a05d2d2aa4830a6e1bd974907e0dd`；request `planned-p08-responses-migration-single`；候选 `planned-p08-direct-responses` 替代提议原身份 `planned-p08-direct`。不是原调用的同配置重试。
- response ID `resp_0880c479f87ca5bf006aebe66dbbe887d297c8a8e4104c3708`。
- **1次POST + 4次同ID GET**：queued → in_progress → in_progress → in_progress → completed。每次查询后间隔均超过15秒，在20分钟窗口/最多60次限制内到终态即停止；未取消、未重发、未切换模型。
- 本地候选契约通过，Task succeeded，Run awaiting_candidate_ethics；“已生成，待Candidate Ethics/R0”，未准入、未评分、science_validated=false。
- 输入39126、输出8543（其中reasoning_tokens1034）、总47669；供应商另返回cache_write_tokens39123、cached_tokens0，全部原样保留。费用未知。GET中重复的同一任务usage不能相加算为多次生成消耗；早期queued/in_progress usage为null，旧两次消耗也为未知。
- Responses没有返回Chat格式finish_reason，本包保留null/缺失事实，不补造stop。以status=completed、无error/incomplete_details、完整正文及现有候选契约作为本次保存条件。

[候选全文](CANDIDATE.md) · [原始模型候选正文](candidate-model-text.json) · [候选JSON](candidate.json) · [完整最终响应](final-provider-response.json) · [完整usage](final-provider-usage.json) · [Codex初审](REVIEW.md) · [22条原文对照及位置](review-comparison.json)。

核心输出是条件性“持续异常核孔蛋白真实磷酸化→成熟mRNP核孔释放延迟→mRNA输出下降→部分后续损伤”猜想，不指定具体分子、位点或模型。未知桥接、适用情境和选择性干预/测量能力未建立。初审发现来源因果措辞弱化，详见REVIEW；没有改写任何模型输出。

## 输入与来源

迁移前通过既有`migration_export`只读导出，preview_hash=`f494fa73f7d66e26d12fb3c75b1aa95104fa46e73982da5aecc5afd4fb445c71`。
[新预览](preflight/preview.json)与已提交准备包逐对象一致。实际消息/Prompt版本`w1-p08-single-v1`不变；六字段科学输入只改既定candidate_id_from_caller，不加入审阅或兄弟内容。

[实际HTTP请求](actual-http-request.json) · [精确发送body字节](actual-http-body.json) · [M15完整提交请求](preflight/new.actual-request.json) · [六字段输入](frozen-input.json) · [配置](frozen-config.json)。HTTP请求145411字节≤262144；完整M15审计封套291377字节因同时保留messages和actual_request而重复，并非实际HTTP body。无静默裁剪。

固定gpt-6.1-sol/high/max_output_tokens32768、JSON object，无temperature；background=true、store=true、stream=false、truncation=disabled；socket与单HTTP总期限各600秒。无隐藏重试、工具、previous_response_id或额外科学步骤。

[固定5份视图](source-views.json)和[原SeedBackgroundPacket](seed-background-packet.json)包含39张原卡片，绑定[同seed readiness](readiness.json)：

| 来源 | 实际可见范围 | 限制 |
|---|---|---|
| PPR1217875，ANXA11 | Abstract/Highlights/In Brief [0,2746) | 非全文；SH-SY5Y与iPSC神经元分开 |
| PMID35112738，TDP-43 | 125363字符原文的Results片段[33770,41370) | 7600字符；其余未读；图注仅文本 |
| PMID41691309，SOD1 | 摘要[0,1714) | 无全文、无磷酸化直接证据 |
| PMID42031697，TPR | 摘要[0,2097) | 非ALS的位点/信号响应，不建立本假说 |
| PMID28831067，SUN1 | 摘要[0,1188) | 内核膜/LINC对象，不是核孔蛋白自身 |

未新增检索或获取；未访问图像像素或补充材料。实际版本元数据按原视图保留。精确ID查询不代表主题覆盖，多张卡/同研究多条件不等于独立复现。

## 迁移、历史与可复核记录

[备份来源及哈希](backup-provenance.json)：对原真实库作SQLite一致性备份，仅保存在仓库外；SQLite backup的页布局哈希不同于原字节哈希，不声称是原文件字节副本。执行只在原库，绝不在备份执行。原始源库SHA256为`4ffef4c2e8f257b7ff0e1a8c10332c09bef68176856837e095104c7cc4fc608f`。

[用户授权范围](operator-authorization.json)、[仅创建后状态](migration-created-state.json)、[四项确认](migration-confirmed.json)和[含单独执行授权的迁移](migration-after.json)分别保存。重复同预览确认复用同一后继且创建时0 Attempts/0网络发送，没有用迁移本身代替付费授权。

[历史前](historical-before.json)与[历史后](historical-after.json)逐对象相同；原Task/action/双uncertain Attempts的请求、错误、previous_id、授权和null用量都未改。[12张表原行保护](historical-preservation.json)对备份内每个原行核对仍存在且全字段不变，包括P04/P05/P07、原文、Brief、Goal和所有旧调用。只新增迁移/后继事实并依法推进Run计划/状态。

[每次Attempt](attempts/)内保留M15请求、最终HTTP请求、原始HTTP响应字节/哈希、响应封套、完整供应商usage与本地Usage投影；无鉴权头或凭据。查询属于同一远端生成的状态观察，不是四个候选。原远端调用是否执行/收费仍未知。

[提交状态](submission-state.json)、`query-01-state.json`至`query-04-state.json`、[有界观察记录](observation-window.json)、[执行事实](execution-facts.json)、[总结](summary.json)可逐次复核。UTC02:14:03开始，02:16:51终态（北京时间10:14:03–10:16:51），约168秒；页面164秒从保存POST响应后计，不是供应商计算/收费时长。

后台同ID查询语义按[官方后台指南](https://developers.openai.com/api/docs/guides/background)复核。store=true标准保留安排及组织例外沿用已审查配置；本次未读取供应商项目控制台，不能声称ZDR、精确删除日期或已删除。没有将有界人工操作循环接入产品刷新/自动轮询。

## 页面与检查

本次启动新的无凭据/无模型执行授权页面进程连接原库，显示原uncertain及后继关系、completed和不可变候选。浏览器实际刷新和额外3次GET后原库字节哈希及Attempt计数不变；[核验](page-readonly-verification.json)、[页面文字](page-generation-text.txt)、[截图](page-candidate.png)。只读查看不设置真实API密钥：

```sh
PYTHONPATH=src python -m co_scientist_next.workspace \
  --db /private/tmp/co-scientist-p04-v2/runs/p04-v2-prepared.sqlite \
  --port 57984 --development-test \
  --generation-responses-config docs/preparations/responses-background/model-config.json
```

已有该数据库进程时先复用页面，不并开Store；此命令不执行、不恢复、不加载密钥。页面刷新不POST也不GET供应商。

离线检查命令及结果：

```sh
env -u OPENAI_API_KEY PYTHONPATH=src /Users/lemintea/anaconda3/envs/coscientist/bin/python -m pytest -q tests/next
# Python3.12.11 / pytest8.4.2：328 passed,0 failed/skipped，42.97s；含7项loopback HTTP及跨进程恢复夹具
PYTHONPATH=src /Users/lemintea/anaconda3/envs/coscientist/bin/python scripts/verify_p08_direct_responses_trial.py
# 核验本包哈希/实际输入/仅1POST/4同ID GET/间隔/历史/用量/候选/初审位置/刷新
/Users/lemintea/anaconda3/envs/coscientist/bin/python -m ruff check src tests scripts \
  --per-file-ignores 'src/co_scientist/_migrations/env.py:I001' \
  --per-file-ignores 'src/co_scientist/_migrations/versions/*.py:I001' \
  --per-file-ignores 'src/co_scientist/adapters/persistence/migrations.py:I001'
node --check src/co_scientist_next/frontend/generation.js
```

[最终回归日志](regression-project-python312.txt)。首先误用了base Python3.11.5/pytest7.4.0（263 passed/65 setup errors，旧pytest将模块helper `setup`误作xunit调用），没有修改测试/源代码，改用现有项目环境后328全通过；不隐藏首次错误。base环境也没有Ruff，最终使用已有coscientist环境的Ruff0.16.6。本次未对Python3.11另建/安装环境复测。

没有改变运行时或科学Prompt，仅增加离线证据核验脚本。原工作区232项内容/暂存/状态指纹保持。未运行旧G3全量、独立人工/专家审阅、科学实验、完整科学链或方法优劣比较。科学有效性、伦理分类与实验可行性均未验证。原M00 Accepted/W1 Proposed状态不变。
