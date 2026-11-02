# W0 S01–S14 证据映射

原始定义保留于 [W0 Proposed 科学样例](design/w0-proposed-v0.1/02_W0_SCIENTIFIC_TEST_CASES_PROPOSED.md)。
本表区分已有工程测试、本轮结构契约检查和仍待科学模块验证的行为。
**没有任何一行因替身通过而被标为完整科学流程已验证；全部 14 项仍有明确的未验证部分。**

测试文件缩写（单元格中的名称均为对应文件内 pytest 函数）：

- R：[test_runtime.py](../tests/next/test_runtime.py)，W0-T0/T1 工程测试。
- P：[test_process_recovery.py](../tests/next/test_process_recovery.py)，真实子进程恢复。
- C：[test_shared_contracts.py](../tests/next/test_shared_contracts.py)，本轮 M09a/M11a 结构检查。
- L：[test_literature_contract.py](../tests/next/test_literature_contract.py)，本轮采集状态与实际 I/O 检查。

| 情境 | 已有可执行工程证据 | 本轮新增契约证据 | 当前未验证部分及责任模块 |
|---|---|---|---|
| S01 Goal Ethics 先于 Generation | R `test_module_failure_is_locatable_and_retry_preserves_history` 仅证明技术故障会保存并停止步骤；不是 Ethics 门 | 无新增 Ethics/Generation 契约，本项待科学模块 | M01.prepare_goal→M02.screen_goal→Generation 的合法时序、拒绝/未知不生成候选；M01/M02/M12 |
| S02 Brief 编辑不改旧 Run | R `test_brief_revision_and_detached_input_snapshot` 验证创建后及两步之间编辑，旧输入、政策和 GoalContext 引用保持；P `test_boundary_restart_duplicate_result_and_completed_run` 验证跨进程读取旧事实 | C `test_admitted_refs_are_fixed_and_require_all_review_refs` 补充固定参赛引用结构，不冒充 Goal 制备 | 真实 M01 Goal 内容、检索和 Ranking 全链不读取新草稿仍待接入；M01/M04/M10/M12 |
| S03 普通缺口补 R1 后回 R2 | 无对应科学执行测试 | 无新增 R1/R2/R3 Schema；C 的审查引用必填仅是结构条件 | 普通必要前提/覆盖缺口识别、定向 M03–M06、更新 Dossier 回 R2、不触发 R3 且不改假说；M03–M07/M09/M12 |
| S04 高影响 R3 和重复 Issue | R `test_duplicate_result_before_and_after_downstream` 只证明重复 Task 结果不重复应用；不识别科学 Issue 等价 | 无新增 Issue 识别或 R3 路由 | 高影响触发、范围/事实等价、科学关闭、结果回 R2、未完成不冒充完成；M07/M08/M12 |
| S05 无直接证据不自动阻断 | 无 Admission 科学判断测试 | C `test_admission_and_qualifications_are_separate_records[NOVEL]` 可表达人工指定的已准入但资格未评估记录；没有按论文数量作决定的代码 | 检索/评价完整性、阻断性、可检验性是否足以准入，真实创新例的科学判断；M05–M10 |
| S06 固定核心科学输入 | R `test_two_steps_and_exact_actual_inputs` 证明通用实际输入落库；不是跨 Match 核心规则 | C `test_admitted_refs_are_fixed_and_require_all_review_refs`；L `test_presentation_order_and_counterevidence_are_stored_not_scientifically_evaluated` 保存同一合成 core 和 E2；同 key 改输入被 M15 拒绝 | M10 跨不同 Match 的核心生成/冻结、反证遗漏检测、针对性增补的科学对称性；M09/M10/M20 |
| S07 非决定性不改分不检索 | R `test_known_failure_exhaustion_is_failed_not_scientific_unknown` 证明技术错误不产生成功结果/后继；没有 TrueSkill | 无新增 Match/Rating/反馈 Schema | needs_more_evidence/inconclusive/technical_failed 三分、零评分副作用、不发 M03–M08 任务；M10/M12 |
| S08 多代追加同一 Epoch | 无持久 Epoch 注册或代际流程 | C `test_fixed_epoch_refs_allow_child_but_not_self_or_blocked_comparison` 和 `test_comparison_refs_reject_mixed_run_epoch_or_policy` 只验证固定引用与同 Epoch 组合条件 | 一个 Run 唯一 Epoch 的持久生命周期、跨代科学准入、旧 Match/评分/依据不迁移；M09/M10/M12 |
| S09 未准入候选不能因修订建议成为父代 | 无父代池或 UCB 算法 | C `test_admission_and_qualifications_are_separate_records` 的 A/B/C/E；`test_nonadmitted_eligible_counterexample_rejected` 拒绝未准入 eligible；`test_qualification_basis_and_reference_mismatch` 拒绝错绑 | 实际 M10 覆盖与父代资格判断、UCB 池、M11 不能绕过选择/自动修复；M09/M10/M11 |
| S10 子代情境改变不继承科学解释 | 无子代科学核查 | C `test_context_change_intent_precedes_inventory_based_resolution`、`test_two_parent_combined_mapping_preserves_parent_inventory_provenance`、`test_unreliable_delta_has_explicit_full_check_fallback`、`test_resolution_rejects_mixed_parent_inventory_snapshots`；`test_relation_shapes` 覆盖六种表示 | M03 真实 Inventory/语义变化解析，M04 原始材料复用，M05 跨情境适用性，M07 独立 R2、M10 新评分；本轮只有固定声明，无科学解析器 |
| S11 调用重试、回放、结果幂等 | R `test_known_failure_retries_usage_and_local_replay`、`test_duplicate_result_before_and_after_downstream`、`test_ambiguous_timeout_blocks_resend_until_explicit_decision`；P 三项跨进程恢复测试证明发送计数与不确定窗口 | L `test_literature_actual_request_access_and_limited_text_persist_through_m15` 补充材料访问返回记录，不新增真实发送 | 真实 Match 合法结果与一次 TrueSkill 影响的关联仍待 M10；M15 工程幂等已验证不等于科学评分幂等全链 |
| S12 最高合格 μ / 无合格 Winner | 无终局 Winner 或 UCB 选择器 | C `test_admission_and_qualifications_are_separate_records` 的 A/E 证明父代与终局状态可独立表达；不选择 Winner | M10 正式终局资格，M12 最高合格 μ/无 Winner，不追加终局 R3；具体科学资格标准仍待研究 |
| S13 空检索、失败、访问层级 | R 通用失败与未知用量测试不证明检索含义 | L `test_success_empty_technical_failure_and_incomplete_are_distinct`、`test_empty_page_or_unreported_pagination_is_not_an_exhausted_empty_search`、`test_port_keeps_obtained_access_separate_from_requested_full_text`、`test_fetch_failure_and_partial_access_remain_locatable`、`test_fetch_contract_rejects_mislabeled_empty_text_missing_limit_and_wrong_source`；M15 受限摘要落库测试 | 真实检索源/分页/范围执行、全文内容真实性、M05 不臆造未读方法学和科学解释；M01/M04/M05/M15 |
| S14 A/B 顺序与偏差 | 通用实际请求记录可用，未有真实比较 | L `test_presentation_order_and_counterevidence_are_stored_not_scientifically_evaluated` 保存 A/B 与 B/A、政策标签和 E2；无 Judge 或评分 | 真正 M10 对称呈现策略、Judge 决策与偏差检测/统计、M20 专家评测；保存字段不保证无偏 |

本轮新增 37 个参数化测试实例，加上原 15 个，共 52 个工程/结构测试实例；
**测试数量不是 14 个科学情境的完成数**。S01/S03/S04/S07 的科学路由、S12 的科学终局均未实施。
S06/S14 的固定原始输入只用于审计，不把记录服务变成 Evidence View 科学评价层。

真实文献、专家标注、保留评估集、真实 Judge 与端到端科学收益均未运行。
W0 整包仍为 Proposed，当前结构检查不能代替后续模块自身的设计批准与科学验收。
