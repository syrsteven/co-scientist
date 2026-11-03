# P04 v2：新 Brief/Run 与待执行材料

状态：**准备完成；本轮真实模型请求0，P04解读0，P05–P07未执行，science_validated=false。**
起点main：`87668c8ee84a52aa3109830cd7dbef02d0a32f28`。
模型表现、科学准确性及伦理分类准确性均未验证；此包是公开开发材料，不是盲测。

## 新输入与固定身份

- 新Project `def2c9881bdd4fe690c06a3ecea15acf`
- 新BriefRevision `997d55886d634f289612ba79e1755f16`
- 新Run `cea909fe8a004010b1896df1c1d98e02`
- 新数据库：`runs/p04-v2-prepared.sqlite`，可从本包prepared.sqlite.gz恢复。

[new-brief.json](new-brief.json)保持原科学问题、两项明确约束和偏好；新背景只保留Goal为开发者转述的来源说明，
移除“仅检索、不执行阅读”的历史操作文字。没有回写旧Brief/Run或首次试跑的请求、原始输出。
[Goal](new-goal-context.json)与[Goal Ethics](development-goal-ethics.json)来自**明确开发模式的确定性适配器**，
只用于工程通路准备，不是真实伦理审查；开发政策没有成为生产默认。

这是全新库，不是旧库备份：1 Project、1 BriefRevision、1 Run；2个本地Goal开发替身Attempt、5次真实公共请求；
没有旧替身阅读、背景包、seed或readiness，也未预创建P04任务。原始历史试跑仍在
[首次审阅包](../../trials/w1-l2-first-real-p04-review/README.md)，未修改。

## 两份实际材料

| 材料 | 实际取得 / 当前选定视图 | 选择理由与限制 |
|---|---|---|
| 对照：[PPR1217875](https://europepmc.org/article/PPR/PPR1217875)，Seeded aggregation of ANXA11… | 新Run重新取得完整abstractText，2746字符，`[0,2746)`；与首次摘要逐字相同，含Abstract/文字Highlights/In Brief | 保留首次输入对照与互补实验情境。预印本，provider版本未报告；不是正文、图像或补充材料 |
| 互补：[PMID35112738 / PMC9016352](https://europepmc.org/article/MED/35112738)，Disease-linked TDP-43 hyperphosphorylation suppresses TDP-43 condensation and aggregation，2022，DOI10.15252/embj.2021108443 | 实际取得125363字符完整JATS机械展平文本；仅选Results小节`embj2021108443-sec-0010`，`[33770,41370)`，7600字符；未选范围明确记录 | 小节含HeLa/U2OS条件、核输入/RNA调控未受影响的报告及作者对其他RNA靶标/细胞类型不能排除效应的限制。不是ANXA11播种实验的直接反驳、核孔蛋白磷酸化证明或独立复现 |

互补材料有原文明确的无差异/未受影响报告，不是把“没报告”编成反证。各实验的条件、对照和终点需按原文分别读取，
不得把磷酸模拟等同所有真实磷酸化、把HeLa/U2OS结果外推到所有神经元或把不同系统合并。
本次只选择1篇新增原始研究，未为凑数虚构第二篇反证，也不声称已独立评审其研究可靠性。

完整来源、作者、出版时间、provider版本限制、访问层级、原文SHA、请求时间、实际取得范围、选择理由和未选范围见
[material-manifest.json](material-manifest.json)。互补论文版权为©2022 The Authors，CC BY4.0；
JATS/来源元数据及许可原文保留在acquisition/实际响应中。此包标明机械展平与显式选段，没有看图或补充材料。

两个源的发现/选择由开发者人工完成，随后执行身份查询：`EXT_ID:PPR1217875 AND SRC:PPR`、
`EXT_ID:35112738 AND SRC:MED`。不是Agent自动规划，也没有执行P03。
新Run真实公共发送共5次（2 search、2 metadata、1 fulltext），每次通过M15留实际请求/原始响应/时间及可用用量；
完整所得文本也压缩保留，未选部分没有被静默删去。搜寻时参考的其他网页未作为材料导入；没有绕过访问验证。

## P04新版本与输入隔离

新P04版本：`w1-l2-p04-context-v2`；P03、P05–P07仍为原版本，科学输出结构不扩充。

- 检查选中视图中Abstract/Highlights/In Brief的互补情境，逐实验关联体系/条件/终点，不把摘要重复句计独立证据。
- 缺失细节写“当前视图未报告”，不升级成全文未做、干预无效或科学上不可知。
- reported_observation忠实标记**作者报告**的诱导/相关措辞；独立证据限度另放not_established，不为表达怀疑而加强或弱化原意。
- author_interpretation、transfer_assumptions、not_established分别区分作者解释、模型外推和视图未建立关系。
- 负结果必须有原文/条件/终点；未报告不等于无效；摘要、选段和图注文字都不能冒充看过全文/图像/补充材料。

requests/每份导出均由实际BackgroundService组装，USER只含goal_context、source_view、seed_brief=null。
没有评审答案、expected/critical_failures等；本README和operator选择说明不是模型输入。
新任务提交时固定Prompt版本；旧数据库升级只添加版本身份列，缺失版本按原v1解析，不重写历史请求、响应或结果。
保留v1原文使旧pending任务恢复仍构造原消息，已有成功调用回放不重新发送；新增跨进程测试验证这一点。

## 待执行配置（本轮不运行）

[model-config.json](model-config.json)：openai，`https://api.openai.com/v1/chat/completions`，
`gpt-6.1-sol`、reasoning_effort=high、max_completion_tokens=32768、JSON object；**没有temperature**。
显式timeout_seconds=600（socket操作超时，不是严格总墙钟截止）；n=1、stream=false、store=false，无隐藏重试。
max_request_bytes=64000；对照/互补计划请求分别8374/13815字节，均完整组装，没有容量裁剪。
reasoning token包含在生成上限和供应商completion总用量中，未执行时用量/费用不能填成真实0。

prepared库只保存材料视图，不冻结“未配置凭据”的P04任务；之后获授权时另行提交新任务。
导出阶段使用api_key=None、authorized=False，**没有读取OPENAI_API_KEY或其他模型密钥**。
credentials只在将来明确执行时独立读取，不写入配置、材料、Prompt或数据库。

## 无网络核对、恢复和页面启动

```sh
# 现有满足项目依赖的Python环境即可；不强制.venv
python docs/preparations/p04-context-v2/verify_preparation.py
# 只恢复新文件；已有文件时拒绝，绝不覆盖旧Brief/Run
python docs/preparations/p04-context-v2/restore_preparation.py --output runs/p04-v2-review.sqlite
PYTHONPATH=src python -m co_scientist_next.workspace \
  --db runs/p04-v2-review.sqlite --port 8788 --development-test \
  --reading-model-config docs/preparations/p04-context-v2/model-config.json
```

页面：`http://127.0.0.1:8788/#run=cea909fe8a004010b1896df1c1d98e02`。
本命令不传凭据/调用授权，也不启用新的公共检索；页面显示已装载真实适配器配置但未授权/无凭据，明确Goal/Ethics开发模式。
显示当前新任务Prompt版本、历史任务固定版本及材料范围/片段限制；刷新只读，不执行、不重发。
已取得不等于已解读；初始已保存阅读数与真实模型Attempt数均为0。

以下是**之后另获授权才可执行的单次P04命令，本轮未运行**。每个视图需独立固定身份，重复发送不是重试策略：

```sh
PYTHONPATH=src python -m co_scientist_next.background_trial \
  --db runs/p04-v2-review.sqlite --run-id cea909fe8a004010b1896df1c1d98e02 \
  --view-id 75bf96a0e25b4e6aa10e54f6781a5382 \
  --config docs/preparations/p04-context-v2/model-config.json \
  --request-id p04-v2-control-single --credential-env OPENAI_API_KEY --execute-real-call
# 互补视图如另获授权：view-id=876e76bb00f84e928a89cbea813dacad，使用不同固定request-id
```

本轮未执行任一P04命令，不安排P05–P07或后续科学模块。独立专家审阅/真实模型对新Prompt的遵从性均未验证。
