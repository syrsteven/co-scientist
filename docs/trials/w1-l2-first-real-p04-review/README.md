# 首次真实P04审阅包

**Codex 初审，待独立人工复核。science_validated=false。**

本包是此前唯一一次获授权真实P04的已保存事实及本轮文本初审；本轮没有模型请求，没有新检索，
没有执行P05–P07、P08、Candidate Ethics或R0。不把成功解析、夹具测试或Codex初审当科学验收。

## 总控从哪里开始

1. 阅读 [逐条对照](codex-initial-review.md) 或机器可读 [JSON](codex-initial-review.json)：
   35项原文字符位置 → 实际P04字段值 → 准确性/遗漏/越界问题/建议。
2. 对照 [实际原文视图](material-original.txt)、[原始模型正文](trial-model-content.txt) 和 [解析结果](trial-p04-result.json)。
3. 阅读 [测试统计与commit](TEST_PROVENANCE.md)；用 [独立人工审阅表](review-form.md)填写自己的判断。
4. 使用SHA256SUMS核对全部文件，并运行只读便携检查。无需本机SQLite、项目安装、网络或凭据。

## 材料与实际执行

- 来源：[Europe PMC PPR1217875](https://europepmc.org/article/PPR/PPR1217875)，DOI `10.64898/2026.03.24.713853`。
  标题：Seeded aggregation of ANXA11 induces prion-like propagation, TDP-43 co-pathology and nucleocytoplasmic transport defects。
- 采用先前W1-L1已保存的真实API响应；本轮不重新核查网络当前版本。
  来源记录为Preprint，版本未报告；不声称同行评议、正式版对应或独立复现。
- 完整`result.abstractText`字段原标记2775字符，机械展平2746字符，视图范围`[0,2746)`。
  含ABSTRACT、文字Highlights/In Brief；**不是论文全文**。Graphic Abstract只是文字标题，没有看图、正文或补充材料。
- 固定view `4613ac8294ed4429a34558f470833ec8`；source acquisition Attempt `5bf8cea903604d87a837108bbed7a3e5`。
- 唯一真实P04 Request `trial-p04-ppr1217875-20261103-gpt61sol-high`；Attempt `ba8d731e9ec14262ab486b358e3b7183`。
  2026-11-03 17:10:16–17:11:08 Asia/Shanghai；HTTP200，finish_reason=stop，完整JSON，解析saved。
- 请求/返回模型均gpt-6.1-sol，reasoning_effort=high、max_completion_tokens=32768、JSON object；
  没有temperature，n=1、stream=false、store=false。显式socket超时600秒，不是严格总墙钟截止时间；无自动重试。
- 输入1477、输出2785（含reasoning1010）、合计4262 tokens；cached_tokens=0、cache_write_tokens=1474。
  [完整usage](usage.json)保留其他供应商字段。费用没有返回，cost=null，不用估算替代实际收费。

## 初审发现与剩余问题

- 三张卡的引文逐字存在于选中视图；没有发现把TDP-43磷酸化偷换成核孔蛋白磷酸化。
- 原文Highlights中的SH-SY5Y/homotypic seeding情境未完整保留；前人患者脑cryo-EM背景也只在限制中部分出现。
- “未知”宜限定为本视图未报告，不能升级为全文未做、干预无效或科学上不可能。
- 第二卡reported_observation把作者induces弱化为“伴随”，author_interpretation仍保留诱导；需人工核对作者声称与独立确认的层次。
- 第三卡作者机制框架解释可由摘要总结句定位，但该句不在该卡自己的supporting_quote内。
- 空negative_findings/negative_quotes只表示视图未报告明确阴性实验；不是没有反证或干预无效。
- 固定Goal的supplied_background仍有早期“仅检索获取，不执行模型阅读”的历史文字；未因后续P04授权篡改固定输入。
  是否影响阅读表现需人工评估；不得静默修订后冒充本次原始请求。
- access/images_seen/negative_state等字段是后端补充，不作为模型自主识别这些事实的能力证据。

原始模型内容和解析结果不被本轮审阅改写；此处没有给科学真实性、完整论文质量或生产能力下结论。

## 文件与事实分层

| 文件 | 来源与用途 |
|---|---|
| material-original.txt / material-view.json | 实际发送的摘要视图与固定身份/访问范围 |
| provider-original-abstract.html / saved-provider-response.json.gz / source-provenance.json | 实际已取得的源字段/原API字节/时间/版本限制；其中preparation计数为历史准备阶段，不是本次调用统计 |
| p04-input.json / p04-messages.json / p04-prompt.md | 实际输入及三条消息；不含审阅/expected/critical_failures；材料及科学Prompt未修改 |
| model-config.confirmed.json / actual-http-request.confirmed.json / actual-http-body.json | 确认的公开配置、实际endpoint/body/timeout及精确body字节；不含Authorization凭据 |
| trial-attempt.json / trial-response-record.json / trial-original-response.json | M15单Attempt及原始供应商响应；保留完整usage/finish_reason、原始字节哈希 |
| trial-model-content.txt / trial-p04-result.json / trial-outcome.json / usage.json | 供应商正文、后端解析结果、执行事实及完整供应商用量 |
| codex-initial-review.* / review-form.md | 操作者审阅材料；没有进入模型，不能当预设科学答案 |
| tests/*.txt / TEST_PROVENANCE.md | 离线夹具/本地HTTP工程检查，不是真实模型输出 |
| manifest.json / SHA256SUMS / verify_review_bundle.py | 版本、文件哈希和无网络的可携带验证 |

Goal制备/Goal Ethics仍来自之前的确定性开发适配器；本包真实部分是文献取得及单次P04调用。
未导出旧SQLite及其替身P04–P07记录，也没有为本次试跑新建seed或研究方向。
所有SHA-256校验只证明文件完整性，不能证明科学真实性或独立复现。

## 获取、校验与复现

本目录随独立PR/分支提交；另提供仓库内附件
`docs/review-bundles/w1-l2-first-real-p04-review.zip`及其`.sha256`，可直接下载，非仅本机路径。
ZIP与本目录内容一致；ZIP不含数据库、密钥文件或.env，不提供自动调用入口。

```sh
# 仓库内：
cd docs/trials/w1-l2-first-real-p04-review
shasum -a 256 -c SHA256SUMS
python3 verify_review_bundle.py
# 或下载ZIP及旁边的.sha256，在该目录先校验再解压：
shasum -a 256 -c w1-l2-first-real-p04-review.zip.sha256
unzip w1-l2-first-real-p04-review.zip
cd w1-l2-first-real-p04-review
python3 verify_review_bundle.py
```

便携脚本仅读本包文件，不导入项目运行器、不读取凭据、不写数据库、不联网。
工程回归在代码commit `796a94b497978e7010cf5f3a2ae5e0cef926085e` 上197项全过（含4项HTTP）；
本PR后续提交只增加审阅/测试证据及STATUS。完整运行命令和历史数量差异见TEST_PROVENANCE.md。
