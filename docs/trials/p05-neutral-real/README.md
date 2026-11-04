# 单次真实P05中性背景综合：结果与离线初审

**Codex 初审，待独立人工复核。science_validated=false。**

基于当前P04结果提交d66051418192e66d900a36d5773623010668ec8b；应用代码与既有P05 Prompt不改。
使用原Run `cea909fe8a004010b1896df1c1d98e02` 和原独立准备库，未重新制作或手工改写P04卡。
Prompt版本为既有`w1-l2-p03-p07-v1`，模式NEUTRAL_ORIENTATION；不是P04 v2版本号。

## 输入、容量与执行

- 明确选择p04-v2-control-single与p04-v2-complement-single两份真实P04结果，全部15卡（7+8）及2视图（2746+7600字符）。
- reading_records与原Run已存P04 artifact逐项相同，仅由既有接口加record_ref；source_views与原视图完全相同。
- 没有旧开发替身阅读、手工修卡、Codex审阅、问题清单或预期答案；保留原Run的已执行两次人工精确ID查询历史，不新增检索。
- 完整HTTP body52164字节；含endpoint/timeout的实际request envelope52256字节，低于配置64000上限。
  未调整容量上限、未静默裁剪任何卡、原文、阴性结果或阅读记录，omitted_readings={}。
- 配置：gpt-6.1-sol/high/max_completion_tokens32768/JSON object，无temperature、timeout600秒；n=1、stream=false、store=false。
- 固定request-id：p05-neutral-15cards-single；Task bf7acff7506542f8aab38e92410fef4a；Attempt120e5978efdd40479c0a161c6a91aa60。
  **1次新请求，HTTP200，finish_reason=stop，完整非空JSON，解析saved。** 无自动重试或模型切换。
- 供应商usage：输入12685，输出4529（含reasoning512），total17214；cached_tokens0、cache_write_tokens12682。
  所有可用供应商字段保留；费用未返回，cost=null，不填为0或估算费用。

输入/消息/实际请求逐字段核对一致；调用后对P04 action/task/attempt/result的序列化哈希与调用前相同。
当前Run背景动作仅P04、P04、P05；没有P06/P07、P08、Candidate Ethics或R0，也没有新公共文献请求。
Goal制备/Goal Ethics仍为先前确定性开发测试，不是真实伦理审查；Run的background_saved不表示科研完成。

## 输出与引用

[原始模型正文](model-content.txt)、[原始供应商响应](original-response.json)、[完整M15记录](attempts.json)、
[usage](usage.json)、[解析结果](parsed-result.json)、[引用关系](reference-graph.json)。

模型返回15个finding_refs和14条类型关系（12 observation、2 author_interpretation）；4条competing_explanations另列为可能解释。
引用有效、卡片齐全属于工程事实，不证明引用在科学上充分支持每条叙述。

**区分来源**：retained_contexts、source_views、selection_manifest等由后端从输入附回；模型自己的overview、
competing_explanations、knowledge_edges等才是待审阅的综合叙述。不能把机械保留15卡等同模型理解/覆盖完美。

## 离线初审

[13项逐条对照](codex-review.md) / [结构化JSON](codex-review.json)，全部在调用后制作，未进入模型。

- 本次保留了主要阴性结果、HeLa定位24h/自调节48h、核输入50min/重复、EMSA两底物、SKAR/Bim挽救、稳定U2OS等边界；不把未报告当无效。
- 没有把两份材料写为同条件直接反驳；明确TDP-43磷酸化、模拟替换、Nup分布与Nup磷酸化不同，也没有将卡片数当独立研究数。
- **R02**：作者及P04的“诱导TDP-43转化”在P05边中弱化为“相关实验中出现”；独立证据限制应另列，不能改写作者报告力度。
- **R01**：作者解释已有类型，模型可能解释另列；但这些猜想没有逐条finding引用或kind=hypothesis标记，角色结构化仍有边界。
- **R08/R10**：P04某体系误配/缺失范围歧义没有在本次综合叙述中直接重复，但原卡问题仍在retained_contexts里；不能声称问题已从数据层消失。
- **R09**：播种与传播具体测定体系仍需细读，不能将并列结果自动当同一实验；不是已确定的错误结论。

本次只是一次P05与Codex初审，不是独立专家验收、稳定纠错或科学有效性验证。没有回写原始P04/P05结果。

## 文件与核对

- input.json/messages.json/planned-http-request.json：调用前导出；actual-request.json为M15实际请求，二者已核对一致。
- action.json/attempts.json/outcome.json/parsed-result.json：真实身份、原始响应、解析及完成状态；original-response.json为保存的响应原始字节。
- sources/：原两份P04输出及视图的原样副本，非Codex纠错版本。
- source-finding-map.json/reference-graph.json：原15卡→P04→来源映射与模型生成的关系；不是独立证据评级或新知识图谱服务。
- runtime-audit.json/p04-preservation-before.json：只读数据库审计，证明原P04记录未改；preflight.json记录调用前0新请求状态。
- codex-review.*：操作员审阅文件，不能当模型输入、预期答案或已完成专家结论。

公开来源仍为PPR1217875摘要和PMID35112738/PMC9016352的指定Results片段；完整出处/许可在已验收准备包。
这里的后者是机械展平的片段/图注文字，不是全文阅读或图像/源数据/补充材料访问。
互补文献：Gruijs da Silva等，2022，DOI10.15252/embj.2021108443，©2022 The Authors，CC BY4.0。
[source-metadata.json](source-metadata.json)保留作者/许可/来源及选段信息；文字经既有适配器机械展平，没有改写研究原文。

本目录随独立结果分支提交，另提供docs/review-bundles/p05-neutral-real.zip与.zip.sha256，可仓库下载。

```sh
shasum -a 256 -c p05-neutral-real.zip.sha256
unzip p05-neutral-real.zip
cd p05-neutral-real
shasum -a 256 -c SHA256SUMS
python3 verify_results.py
```

便携脚本只用标准库读文件，不导入模型客户端、不读凭据、不写数据库、不联网。
本轮已执行只读原库审计、实际输入/响应/usage/引用/审阅定位与包哈希核对、Ruff/format及独立解压校验。
应用代码不改，未重跑既有203项工程回归；独立人工科学审阅、稳定性验证均未运行。
