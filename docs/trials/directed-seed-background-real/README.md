# 定向seed：一次有界背景准备及不确定P07交付

**P03、三份P04及P05已保存；P07发送结果uncertain，Run blocked，没有readiness决定。**
Codex 初审，待独立人工复核。science_validated=false；Goal Ethics仍为先前开发测试结果，不是真实伦理审查。

起点 `54253eb2e5fac2c672fe9a1461bdc851488a1331`，应用main基线 `378475b2e5a86d1c6504138bc3992dae2c977e81`。独立交付分支 `codex/directed-seed-background-trial`，未合并，应用与既有Prompt未改。
Run `cea909fe8a004010b1896df1c1d98e02`；seed `seed-f87361b21b4f44609dedfa2ac9afc7bc-0`。仅此定向分支；复用原宽阅读，不输入兄弟OPENseed或评审。

## 实际执行与额度

按P03 → 3条显式搜索 → 3份摘要获取 → 3次P04 → P05 → P07顺序执行，无自动循环、重试或模型切换。共6次新模型调用尝试：5次HTTP200/stop/saved，最后1次uncertain；6次公共服务发送均成功（3搜索+3摘要元数据）。

| 步骤 / 固定request-id | 完整请求字节 | 输入tokens | 输出tokens（含reasoning） | reasoning | 状态 |
|---|---:|---:|---:|---:|---|
| P03 `directed-seed-p03-plan-single` | 9710 | 2533 | 2058 | 880 | saved，3条查询 |
| P04 `directed-seed-p04-source-1-single` | 8376 | 1907 | 3891 | 969 | saved，6卡 |
| P04 `directed-seed-p04-source-2-single` | 8789 | 1965 | 5451 | 1019 | saved，11卡 |
| P04 `directed-seed-p04-source-3-single` | 7888 | 1820 | 4049 | 877 | saved，7卡 |
| P05 `directed-seed-p05-packet-single` | 116666 | 30123 | 7796 | 1151 | saved，39卡完整保留 |
| P07 `directed-seed-p07-readiness-single` | 148027 | 未知 | 未知 | 未知 | uncertain，无响应/决定 |

已知5次usage小计输入38348、输出23245（已含reasoning4896）、total61593。**不是本轮完整总耗用**：P07是否已被供应商处理及其消耗未知。所有费用未知/null，绝不将P07填成0。完整供应商usage（含返回的缓存详情）见每项 `*.usage.json`、`*.original-response.json`；P07缺失原因见transport-status，不伪造原始响应文件。

模型gpt-6.1-sol，reasoning_effort=high、max_completion_tokens=32768、JSON object、无temperature、timeout_seconds=600。凭据仅从独立环境变量OPENAI_API_KEY读取，未保存鉴权头或密钥。P04版本w1-l2-p04-context-v2，P03/P05/P07为w1-l2-p03-p07-v1。
按用户此前允许调整容量上限的授权，本轮先显式配置262144字节以容纳累计阅读/搜索事实；不改变模型参数。全部完整请求预检通过，没有静默裁剪/压缩；字节检查不等于精确token上下文证明。每项预检、实际消息、实际请求、配置均单独导出。

## 真实检索、选择与范围

P03最多3查询，保存计划后由操作者通过现有LiteratureService显式逐条执行。每条cursor=null、page_size=5；API返回的全部首屏条目与下一页游标原样保留，没有后续页。3条报告总数分别121、9、184，均只取得5项、scope_complete=false。没有把旧的2条精确ID查询当主题覆盖，也没有把未选/未读条目当阴性。

| 获取来源 | 标题/用途 | 实际视图 |
|---|---|---|
| [PMID41691309](https://europepmc.org/article/MED/41691309) | Impaired nucleocytoplasmic transport in SOD1-mediated ALS；另一ALS背景与救援/阴性情境 | 完整提供商摘要1714字符 |
| [PMID42031697](https://europepmc.org/article/MED/42031697) | Nucleoporin TPR integrates MAPK signaling with mitogen-induced transcriptional programs；核孔蛋白修饰实例，非ALS/mRNA输出证据 | 完整提供商摘要2097字符 |
| [PMID28831067](https://europepmc.org/article/MED/28831067) | The function of the inner nuclear envelope protein SUN1 in mRNA export is regulated by phosphorylation；邻近过程/对象边界 | 完整提供商摘要1188字符 |

`selection-manifest.json`逐条记录15个结果位置（14个唯一来源）的选择/未选原因、原宽背景复用与全部后续页遗漏。本轮请求摘要，不声称新来源全文不可得；正文/图像/补充材料均未获取或阅读。标题相关性用于选择，不是科学评价或证据独立性判定。没有将选中分子指定为答案。

新视图分别 `ef0d631b44e14b2abf8f10443c55d5c2`、`af80cf113c514689a5b9e25ef9f0b193`、`692ca660eef14f86a19318ca2e08d85b`，均绑定该seed、完整范围、cropped=false。
复用 `p04-v2-control-single`（ANXA11摘要/Highlights/In Brief）和 `p04-v2-complement-single`（TDP-43 Results文字片段[33770,41370)，非整篇全文阅读）。P05共5阅读、39卡、5视图，并保留2旧精确查询+3新主题查询。来源/版本/位置/阴性引文见 `source-finding-map.json`；不将39卡当39项独立研究，也不由不同DOI/ID推断独立复现。

## P07不确定状态与可交付依据

Task `55bc66f3e1a44070babcf67db99b0bac`，Attempt `0d9e7d5fd9da4bbea3ddc42608e0c184`，ordinal=1、previous_id=null、retry_authorization=null。
本地记录03:20:22.577406Z开始、03:20:27.613994Z结束，约5秒后记录uncertain；配置600秒，没有依据认定为600秒超时。适配器仅保留脱敏错误“Model send outcome uncertain; credential details withheld”，原始网络原因未保留，不能断言服务没执行、具体失败原因或0费用。

`p07.input.json`、messages、planned-http及Attempt保存了完整SeedBackgroundPacket、39finding引用、实际搜索与requested_specificity。这些是提交给P07的准备依据；没有模型返回的rationale/checks/allowed_specificity，不补造科学决定。当前Run blocked，不是retrieve_more或unable_to_prepare，不等于科学否定。不执行自动recover/重发；任何后续解决须显式授权并保留不确定调用关系。

## 调用后初审与验证

[codex-review.md](codex-review.md)共11项，**Codex 初审，待独立人工复核**。重点：保留核圆度不变、SUN域缺失无影响、S113A较弱恢复及跨体系边界；但P05再次弱化ANXA11作者“诱导”措辞，另将SUN1“导致相互作用降低”改为“伴随”。原结果不修改。P07无响应，无法科学审阅其决定，也不借此判背景不足。

运行只读离线审计（不发请求）：

```sh
python docs/trials/directed-seed-background-real/verify_results.py
python -m ruff check docs/trials/directed-seed-background-real
```

已实际执行：只读DB对照、原有各表行哈希保护、实际请求与原始字节/usage核对、所有39张卡与阴性引文定位、seed/兄弟隔离检查、6次模型尝试额度及顺序、3条首屏/3来源边界、ZIP解压后审计、凭据扫描。全部结果以docs/verification/directed-seed-background-real日志为准。
本轮应用代码未改，未重跑pytest203项新系统工程回归、旧G3回归或浏览器。此前回归结果见历史STATUS，不作为本轮新执行。

本地辅助脚本两项错误也记录：公共响应哈希字段与模型字段不同导致一次导出失败，修正后只读已保存成功事实，无重发；两次过早离线预检被Store活动锁拒绝，无Task/Attempt创建。之后均等待前一步进程结束。

原Run的历史Task/Attempt/Result、P04/P05/P06、Goal/Brief和原视图逐行哈希保持；原用户工作区232项改动保持不变。审阅包 `docs/review-bundles/directed-seed-background-real.zip` 附SHA256，解压后可审计，无需本机DB。
未执行额外检索循环、P08、Candidate Ethics或R0；未进行独立人工/专家审阅、科学有效性或完整科学链验收，science_validated=false。
