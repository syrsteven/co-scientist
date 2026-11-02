# W0-T2 最小公共契约

本轮仅采用用户指定的 M09a、M11a、LiteraturePort 最小表示与结构检查。
M00 仍是 Accepted 设计基线，W0 原包保持 Proposed，原文件未重写。
代码与固定反例不实现科学准入、排序、演化、真实检索或完整科研流程。

## M09a：固定引用与独立资格

`co_scientist_next.admission.AdmissionRecord` 保存 Run、候选科学内容、Goal、
政策、Ethics、Inventory、Dossier、FinalReflection 的固定引用、M09 给出的决定与理由。
决定区分 `admitted / blocked / incomplete`；仅 admitted 带 Epoch 且必须具备全部审查引用。
blocked/incomplete 可保留已有审查引用，不冒充完成。

`EligibilityRecord` 由 M10 提供，显式区分 `parent / final`，每项状态独立为
`not_assessed / eligible / ineligible`。已经评估的资格必须提供依据引用。
准入既不自动授予父代资格，也不自动授予终局资格；两种资格彼此也不自动推导。
`check_eligibility` 只拒绝引用错配和未准入却声称 eligible 的组合，不授予资格或选父代。

`check_comparison_refs` 只检查不同候选、不同 Admission、双方已准入以及相同
Run/Goal/policy/Epoch 引用。它不创建 Match、计算评分、登记 Epoch 或判断 Winner。
同一 Run 只有一个 Epoch 的持久注册与多代追加仍归后续 M09/M12。

记录采用 frozen dataclass 和不可变字符串/元组，防止对象内原地改写。
调用方可把 `dataclasses.asdict` 结果交给已有 M15 记录实际输入；无新增服务或数据库表。
这不是全局身份注册器：不能证明引用存在、引用内容永不被外部覆盖、审查实际完成或判定正确。
同 ID 被上游重新绑定等持久一致性仍由对象所有者负责。

## M11a：先提案，后解析，复用另判

- `DeltaProposal` 由 M11 在新子代创建时记录父代、算子和修改意图，不含虚构的子代 Inventory。
- `ResolvedDelta` 由 M03 在真实子代 Inventory 建立后提供，绑定提案、子代与 Inventory。
  `ClaimChange` 区分 retained、modified、removed、split、combined、new。
  父代 `ClaimRef` 用候选、Inventory 与本地 Claim ID 定位；同名 Claim 不会自动成为同一来源。
- 结构检查覆盖关系基数、重复子代映射、提案/子代错配、提案之外父代、同父代混用不同 Inventory。
  它不读取完整 Inventory，也不判断语义相似性或 Claim Coverage。
- 无法可靠解析时使用空 changes 与明确 `unresolved_reason`。本最小表示保守地不宣称局部关系
  已解析；M04/M05 必须安排完整核查，不能为缓存命中臆造 retained。没有自动执行的回退任务。

M04 决定原始材料是否复用，M05 判断新情境下科学评价是否适用；Delta 不授予任何复用许可。
M07 仍需对子代独立完整 R2，M10 不能继承父代评分。本轮无材料复用器、科学 Delta 解析器或演化器。
Python 类型名和文档表达所有权，不是运行时身份认证或模块权限系统。

## LiteraturePort：执行事实与材料访问

`co_scientist_next.literature.LiteraturePort` 只有 `search(SearchRequest)` 和
`fetch(FetchRequest)`。M01 决定背景检索策略，M04 决定 Claim 检索策略，M05 解释证据。
它们不依赖 M09/M11 实现；仅共用极小的结构校验函数。

Search 保留真实查询、来源、声明范围、分页游标、执行时间、条目、可获得的总量与错误。
执行状态区分 succeeded、failed、incomplete。只有成功、声明范围完成、非续页且没有条目的
结果才表示 `searched_empty_within_scope`。空页、最后一个空续页、未知分页完成度、技术失败
均不能据此声称整个查询无结果；部分条目后中断用 incomplete 保留条目和失败原因。
时间和范围由适配器如实提供，不证明真实外部服务已经被本契约调用。

Fetch 区分请求的访问层级与实际获得的 none、metadata、abstract、full_text、supplementary。
metadata 不能伪称已有文本；abstract/full_text/supplementary 必须保留实际文本和来源。
实际层级与请求不同需说明 limitation；全文未取得但得到摘要可明确记录成功的受限获取。
技术失败保留错误且不得伪装成成功空结果；部分取得材料后中断用 incomplete。
这只能检查标签/内容是否齐备，不能检测把摘要文本谎标为全文，或认定文献方法学已被核验。

无真实适配器、数据库选择、查询生成或外部请求。未来适配器须把每次真实发送交给现有 M15，
保存实际请求/响应、错误、重试和可获得用量，不能在内部隐藏发送或技术重试。
新增测试仅证明固定受限材料的请求和返回可通过 M15 保存，不代表真实来源获取已接入。

## 固定反例与运行

`examples/w0-t2-contracts.json` 明确标记 synthetic，包含资格分离、强修订建议但未准入、
新情境与新增桥接、不可靠映射、仅摘要/全文不可得等固定反例。测试另含双父代合并、同名
本地 Claim、混用 Epoch/Inventory、失败误标空结果、空续页、A/B 顺序和反证输入记录。
没有真实论文、专家真值或真实 Judge。

```sh
PYTHONPATH=src python -m pytest -q tests/next/test_shared_contracts.py tests/next/test_literature_contract.py
PYTHONPATH=src python -m pytest -q -s tests/next
python -m ruff check src/co_scientist_next tests/next
```

沿用现有 Python 3.11/3.12 或 conda 环境，无新生产依赖和 API 密钥。
S01–S14 的实际覆盖和未验证部分见 [映射表](W0_SCENARIO_MAP.md)。
