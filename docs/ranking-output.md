# Ranking 严格输出协议（Developer Preview）

`deepseek-strict-tool-v1` 是新 DeepSeek 运行可选的 Ranking 结果传输协议。默认仍为标准 JSON；它不改变科研评分标准，也不保证科学结论正确。离线工程验收和[一次在线兼容性检查](reports/2026-09-20-strict-ranking-probe.md)已通过；但[常规 Run010 测试](reports/2026-09-20-strict-workflow-live.md)在 7 场比赛和一次科学 Meta-review 后，第 8 场仍因非法工具参数暂停。严格输出不是 JSON 有效性的保证，完整闭环和可靠率提升尚未建立。

2026-09-20 新增可选 `deepseek-strict-tool-v2`：六维理由使用扁平字段，已离线验证、**尚未在线验证**。它不是对010原响应的修补，不自动替换 v1；详见下方版本说明。

## 为什么增加这个选项

真实运行 `lens-deepseek-20260919-009` 的两次 Ranking 响应，在供应商报告 `finish_reason=stop` 的情况下仍包含非法 JSON。原适配器已经使用 `response_format: json_object`，因此不能把再次开启 JSON 模式当成修复。详情见[真实续跑报告](reports/2026-09-20-explicit-retry-live.md)。

新选项让供应商按明确的函数参数 schema 输出 Ranking 结果。函数仅是结果通道，不执行实验、不创建后继任务、不更新 rating；调度和领域应用仍由 Supervisor 控制。

## 如何启用

1. 设置页载入 DeepSeek 模板，或复制一个已有 DeepSeek 运行。
2. 在“文献检索”开启科学上下文；在“评审与演化”选择 `Research v1`。
3. 在“竞技场与停止 → Ranking 输出协议 → 结构化输出约束”显式选择 v1，或 **DeepSeek Strict Tool v2 · 扁平理由 / 仅离线验证**。
4. 校验并保存为新配置。按页面命令使用新的 Run ID 启动；执行时才会发生在线调用。

命令行用户可在满足上述条件的 DeepSeek profile 顶层增加这一行，保留其余配置：

```yaml
ranking_output_protocol: deepseek-strict-tool-v1
```

删除该字段或设置为 `null` 使用原有标准 JSON。旧副本不会自动开启；切换到其他供应商会清除此选项。当前只支持 DeepSeek + Research v1，不能通过它启用其他供应商的严格输出。

**不能升级正在运行或历史 Run。** 协议、模型、评价规则和输入在创建时冻结。不要修改旧 manifest、任务输入或原始响应，也不要用 `resume` / `retry-output` 将标准 JSON 运行转换成严格输出运行。不同 epoch 的 Elo 不直接比较。

## v2：扁平理由的实验协议

在新 profile 中设置 `ranking_output_protocol: deepseek-strict-tool-v2`。它使用唯一函数 `submit_ranking_result_v2`，将六维理由改为顶层 `reason_<dimension>` 字符串。例如 `reason_causal_specificity` 原样映射为规范结果的 `dimension_reasons.causal_specificity`。所有理由全文、评分维度、身份字段、confidence、分歧和判定都保留，不限制理由长度或降低科学标准。

动机是减少模型生成嵌套理由对象的结构负担。这只是待验证的改进假设：扁平 JSON 仍可能非法，不能保证解决供应商错误。v2 不接受嵌套的 v1 参数、不混用函数名、不接受缺少/额外维度或空理由，也不尝试恢复坏 JSON。

v2 的函数名、六维映射和生成指令整体冻结到独立契约，纳入 epoch 评价身份与规范请求指纹。v1 契约及其 hash、普通 JSON、旧 Replay 和原始响应保持不变。010 的 7 份历史有效输出用新代码离线解码后仍与已保存结果逐项相等；第 8 份仍在原位置1507被拒绝。

本轮离线验收：156 项定向 Python 测试及 9 项 Node 设置测试通过，含 v1/v2 四类比赛判定、完整文本的无损映射、缺失/错误字段、版本混用、010 多余冒号形状、真实临时数据库的暂停→显式授权→恢复、配置保存与历史兼容。没有付费调用，没有重复全量套件。原010仍为 needs_attention / SEQ182。

测试对应 `tests/unit/runtime/test_ranking_output_v2.py`、`tests/scenario/test_failure_recovery_audit.py`、`tests/unit/runtime/test_live_ranking_probe.py`，不包含私人原始研究正文。

## 传输与校验

DeepSeek 官方将严格工具调用标为 Beta，要求使用 beta endpoint、所有对象属性列为 required、禁止额外属性；其支持的 schema 子集不包含 `minLength/maxLength` 或数组长度限制。本实现使用该子集构造明确 schema，不进行宽松的自动 schema 转换。[官方 Tool Calls 文档](https://api-docs.deepseek.com/guides/tool_calls/)

| 项目 | 本项目行为 |
|---|---|
| 范围 | 仅 Ranking；其他角色继续原来的输出协议 |
| 端点 | `https://api.deepseek.com/beta/chat/completions`，固定在版本化契约中 |
| 工具 | 只声明 `submit_ranking_result`，`strict: true` |
| 工具选择 | `auto`，指令要求仅返回一次指定函数结果 |
| 内容绑定 | 计划版本、match/epoch、候选 ID/hash、评价规则/prompt/judge/rating/admission 身份 |
| 科研内容 | 同一六维理由、置信度、未解决分歧和四类比赛判定 |
| 原始证据 | 保持完整供应商响应及 usage；先落盘，再解析工具参数 |
| 失败 | 保留 raw/成本并进入待处理，不补 JSON、不降级为普通文本、不自动继续付费重试 |

保留用户配置的思考模式。官方 API 不允许在思考模式使用 `required` 或指定名称的强制工具选择，因此使用 `auto`；模型仍有可能不返回工具，此时必须失败，不能静默关闭思考或接受普通 JSON。[官方 Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/)

上表工具名为 v1；v2 使用 `submit_ranking_result_v2`，其余传输、安全边界相同。

传输格式有一个显式编码差异：`winner_slot=0` 表示 canonical `null`，即没有胜者；`1/2` 仍代表左右候选。此编码用于避免依赖未明确支持的 nullable schema，不是修补模型判定。解码后继续通过原 `RankingResultV1`：只有 `decisive` 可以有胜者，其他判定不更新 Elo。

本地校验要求唯一 choice、`finish_reason=tool_calls`、唯一指定函数、没有混合正文，以及合法 JSON、无重复键/非有限常量、准确字段类型和内容绑定。供应商端 strict 不代替本地验证，工具输出也不被当成可执行命令。

固定契约与 hash 保存到 manifest，并进入 epoch 评价规则和 judge 身份。Supervisor 将它注入 Ranking 输入，工具 schema 进入规范请求及 request fingerprint。其他角色、旧 Replay 和未启用该选项的序列化身份不变。

## 原始响应诊断

“运行总览 → 输出失败 → 查看原始响应”现在附带只读 JSON 语法提示。当前支持 DeepSeek/Qwen 的正文或单工具参数，以及 Replay 原文；先验证文件归属、长度和 hash，再显示错误通道、行列和从 0 计的字符位置。

提示“JSON 可解析”**不表示**重复键、字段、内容绑定、审查或科学结论已通过。诊断不写数据库、不修改 raw、不授权重试、不调用模型；结构不明确时直接提示无法诊断。技术恢复仍使用[显式输出重试](output-retry.md)入口。

## 离线验收与下一步

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_ranking_output.py \
  tests/unit/application/test_output_diagnostics.py \
  tests/unit/application/test_cockpit_settings.py \
  tests/scenario/test_failure_recovery_audit.py -q
node --test web/tests/*.test.mjs
```

2026-09-20：完整 Python 离线回归 872 项通过，3 项 online 未运行；随后补充设置依赖错误定位及配置保存往返，上述 82 项定向测试再次通过。Node/HTTP 31 项通过。覆盖四类比赛结果、缺失/多工具、截断、重复键、非法数值、错绑、旧协议兼容，以及临时数据库内 raw-first → 显式授权 → 独立 Worker 完成流程；浏览器验证设置草稿和真实失败响应的只读诊断。

该轮没有调用付费模型，没有更改 Run009 的事件、候选、原响应或配置。Run009 仍停在 SEQ136，20 次外部尝试、19 笔成本记录、1 场有效比赛；这不是完整科研闭环成功。

2026-09-20 后续在线 probe：`deepseek-flash` / thinking enabled / low 返回 HTTP200、唯一工具结果并通过本地校验，判定为 needs_tiebreaker；1 次调用，4,476 输入 + 3,041 输出 tokens，无领域应用。下一步应以独立有限预算的新 Run 验证完整流程，再在固定输入与评价规则下对比标准 JSON/严格输出的有效结果率、失败类型、token 成本及科学判定。单次成功不能换算成在线可靠率提升或原论文性能等效。

同日完成的 Run010 常规流程测试已记录新限制：前 7 场成功，第 8 场严格工具参数非法；Meta-review v1 已进入后续 Ranking，但反馈驱动子代因候选余量规则未调度，最终收尾未开始。实际用量 318,777 tokens，原始及导出 raw 各 26/26 完整，工程审计 0 违规。当前建议先离线处理这些限制，不持续付费重试。详见上述 Run010 报告。

### 单调用在线兼容性检查

开发测试入口仅使用仓库内两个固定晶状体 anchor，不读取历史 Run 的候选，也不调用 PubMed。它复用生产请求构造、DeepSeek adapter、严格解码和内容绑定校验，但不创建科研 Run、不提交 AgentResult/比赛、不更新 Elo。因此不出现在驾驶舱运行列表，不能替代完整 Worker 流程测试。

确认本终端已经配置 `DEEPSEEK_API_KEY` 和 `CO_SCIENTIST_DEEPSEEK_MODEL` 后执行：

```bash
.venv/bin/python -m tests.live_ranking_probe \
  --output .co-scientist-probes/your-new-probe-id \
  --confirm-paid-call
```

目录必须不存在；上述命令最多发出一次 HTTP 请求，拒绝重定向和第二次请求，不自动重试或 fallback。使用仓库 DeepSeek 模板的生成参数并显式开启 strict；模板中的科研预算不参与 probe 调度，probe 自身固定上限为一次请求。示例中新的目录名由用户自定，不要循环生成目录来规避一次调用限制。

probe 默认仍使用 v1。仅在明确决定测试新协议时添加 `--protocol deepseek-strict-tool-v2`，并使用新的证据目录；此参数不修改已有 probe 或科研 Run。本轮没有执行 v2 在线 probe。

证据包括 `manifest.json`、`request.json`、不含认证头的 `wire-request.json`、`events.jsonl`、`artifacts/raw/` 和 `report.json`；通过后才写 `result.json`。收到完整 HTTP 响应时先保存原文及 hash，再解析，非 2xx 错误正文也保留。网络失败或中途断开可能没有完整 raw/usage，不代表供应商没有计费。`usage=null` 或 `cost_usd=null` 表示未知，而非免费。

状态序列为 `planned → started → raw_response_persisted → usage_recorded → validated`，失败则保留已有记录并写 `failed`。这只是独立 probe 的审计记录，不冒充完整 ExternalCall/领域提交生命周期。进程被中断时先检查原目录的最后状态；不要直接重发不确定请求。该目录已被 Git 忽略，未经明确授权不要上传原始研究输入/响应。

probe 守卫离线测试：`.venv/bin/python -m pytest tests/unit/runtime/test_live_ranking_probe.py -q`。

相关实现：`domain/ranking_output.py` 定义版本化输出契约与解码；`application/config.py` 冻结身份；`supervisor/scientific_context.py` 注入；`agents/executor.py` 构造请求并执行落盘后校验；`adapters/llm/multi_provider.py` 构造供应商 HTTP 请求。后续更改传输语义时应新增协议版本，不修改已冻结版本。
