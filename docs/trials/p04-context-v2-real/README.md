# P04 v2 顺序真实试跑与离线审阅

**Codex 初审，待独立人工复核。science_validated=false。**

基线：`378475b2e5a86d1c6504138bc3992dae2c977e81`。应用代码未修改。
使用已验收的新Run `cea909fe8a004010b1896df1c1d98e02` 及原独立准备库
`/private/tmp/co-scientist-p04-v2/runs/p04-v2-prepared.sqlite`，没有从空快照另开副本重复调用。
执行前已检查此库及已知页面副本均无对应background动作；原库事实与准备快照一致。
准备包SHA、两份材料/输入/消息/HTTP与已审查版本逐项相同，版本均为w1-l2-p04-context-v2。

## 实际执行事实

| 顺序/材料 | 固定request-id | Attempt | 结果 | 输入/输出/reasoning tokens |
|---|---|---|---|---|
| 1 对照摘要2746字符 | p04-v2-control-single | 3d4c827fad69481c90ceebf5caa3f7f8 | HTTP200 / stop / saved；1次 | 1749 / 4273 / 1024 |
| 2 互补Results片段7600字符 | p04-v2-complement-single | e8dc9d52845e4fb0b713410a2ba0a724 | HTTP200 / stop / saved；1次 | 3328 / 6326 / 2563 |

第一份保存为成功后才开始第二份，M15起止时间已核对。每份ordinal=1、previous_id=null；无重试、模型切换或截断。
模型请求和返回名均gpt-6.1-sol；high、max_completion_tokens32768、JSON object、无temperature、timeout600秒。
单响应正文非空且为完整JSON，现行解析/引用契约通过；不代表所有科学表述准确。
用量合计：输入5077、输出10599、总计15676；reasoning3587已包含在输出中，不重复相加。
费用未返回，cost=null；完整缓存/其他供应商字段在*.usage.json和原始响应内保留。
[execution-summary.json](execution-summary.json)只统计本轮两次，不混历史v1、Goal替身或准备阶段文献获取用量。

对照view：75bf96a0e25b4e6aa10e54f6781a5382；互补view：876e76bb00f84e928a89cbea813dacad。
对照只读已得Abstract/文字Highlights/In Brief；互补只读已得全文本的[33770,41370)Results小节，含图注文字。
没有看图、补充材料或其他未选区段，不执行模型定向reading_requests。

Goal制备/Goal Ethics仍为此前确定性开发测试，不是真实伦理审查。
最终原库只有2个background.P04动作（共8个Task、9个Attempt：原有2Goal替身+5文献+本轮2模型），无P05–P07/seed/readiness。
没有执行P08、Candidate Ethics或R0，没有新公共检索，没有候选生成。
已保存成功事实仅被本地读取/核对，未通过重复CLI命令重新发出请求。

## 离线审阅

[20项原文→实际字段→初审对照及6项v1比较](codex-review.md)；[可机器读取版本](codex-review.json)。
原始模型正文和解析结果未做修正。审阅在两次调用结束后生成，不进入任何模型输入；
互补请求同样与预审导出一致，没有夹带对照输出、评审答案或预期结果。

本样本观察：

- v2摘要保留SH-SY5Y补充情境、作者诱导措辞、关联与In Brief作者概括的层次，缺失条件更多限定为当前视图。
- C-08：一处限制句可能把TDP-43表型误配至神经元，和模型另卡“体系未报告”存在张力，需复核/以后修订。
- 互补结果区分磷酸模拟与真实位点磷酸化，分别记录HeLa定位、输入报告、48h自调控、体外EMSA、SKAR/Bim挽救、稳定U2OS定位/自调控。
- M-09：部分“其他RNA序列/processing events未报告”的范围措辞有歧义，不能遗漏同一视图已报告的UG12、其他剪接/自调控读数。
- M-08：U2OS统计方法/SD/P范围等可见信息未完整保留；不能因未列效应量就宣称没有任何统计信息。

仅各一次摘要比较，且新Brief背景/Run/Prompt均改变，不是单变量AB或重复验证；不宣称稳定提升。
首次v1的3卡与本次7卡只是组织/覆盖差异，不是科学准确性分数。互补8卡也不等于8项独立研究。
独立专家审阅、底层研究真实性及科学有效性均未验证。

## 文件层次与访问

- views/、*.reviewed-p04-input.json、*.reviewed-p04-messages.json、*.reviewed-planned-http.json：本次实际视图与经预审导出，和M15实际请求已核对一致。
- *.attempts.json：完整M15身份/请求/响应/错误/用量/时间；*.action.json：Task/绑定/版本与应用状态。
- *.original-response.json：供应商原始字节；*.model-content.txt：其原始正文；*.parsed-result.json：后端解析投影；*.usage.json：完整供应商usage。
- 互补原始正文额外返回access_scope，现行契约未将该额外字段复制到artifact，原始响应/正文中完整保留；其他后端访问元数据不计模型自主能力。
- run-facts.json：只读导出的当前Run/Task/计数；preflight.json为调用前记录，不是调用后的计数。
- approved-material-manifest.json、acquisition/：准备阶段来源/作者/版本/许可/原响应与完整所得文本的原样副本。其5次公共请求不是本轮新请求，原“准备时0模型”状态仍按历史保留。
- baseline-v1/：首次v1的原始输出/消息/解析/用量副本，仅用于比较，不进入v2请求，也不计本轮用量。
- codex-review.*：操作者独立文件；不能当已完成独立人工复核或预设答案。

新增互补来源：Gruijs da Silva等，2022，[PMID35112738 / PMC9016352](https://europepmc.org/article/MED/35112738)，
DOI10.15252/embj.2021108443，©2022 The Authors，CC BY4.0；机械展平/选段已明确，完整出处及许可原文见来源包。
它与ANXA11播种摘要条件不同，不是对其直接反驳或独立复现，也不替代核孔蛋白磷酸化证据。

## 可携带离线验证

本目录提交到独立结果分支，并附仓库内ZIP：docs/review-bundles/p04-context-v2-real.zip及.zip.sha256。
不依赖本机DB、模型凭据或网络即可读取和核对：

```sh
# 下载ZIP与旁边.sha256后：
shasum -a 256 -c p04-context-v2-real.zip.sha256
unzip p04-context-v2-real.zip
cd p04-context-v2-real
shasum -a 256 -c SHA256SUMS
python3 verify_results.py
```

SHA用于文件完整性，不代表科学真实性。verify_results.py仅使用标准库读取文件，核对原始字节、usage、版本、输入/视图、审阅定位；不会导入模型客户端或发送请求。
本轮应用代码未改，未重跑203项工程回归；该基线已验收的回归与本次真实阅读/文本初审是不同证据。
