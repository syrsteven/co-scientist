# DeepSeek 严格 Ranking：单调用在线兼容性报告

日期：2026-09-20。结论：**本次真实请求兼容性通过，尚不是完整科研流程验收或可靠率评测。**

## 方法和边界

沿用现有 `deepseek-flash`、thinking enabled、reasoning_effort low、max_tokens 32768、HTTP timeout 300 秒。只把仓库内两个固定晶状体 anchor 和仓库研究目标发送给 DeepSeek，不读取 Run009 的科研候选，不检索新文献，不修改历史 Run。

测试入口 `python -m tests.live_ranking_probe` 复用生产 request builder、NativeJSONProvider、strict decoder、RankingResultV1 和内容绑定校验。HTTP 层固定一次请求、禁止重定向/自动重试；完整响应（含非 2xx）通过 response hook 先保存 raw 再解析。

这是独立兼容性 probe，不是 Supervisor/Worker 新 Run。未创建数据库、未提交 AgentResult、未产生 MatchEvaluated、未修改 Elo，不应出现在科研驾驶舱的运行列表，也不能作为单/多模型比较数据。

严格工具 beta 的参数要求以[DeepSeek 官方 Tool Calls 文档](https://api-docs.deepseek.com/guides/tool_calls/)为依据。本次直接验证了 `deepseek-flash` 接受当前完整 schema；不能外推其他模型或未来供应商版本。

## 实际结果

| 指标 | 本次观测 |
|---|---|
| Probe ID | `ranking-strict-20260920-001` |
| HTTP 调用次数 / 状态 | 1 / 200 |
| 结束原因 | `tool_calls` |
| 工具数 / 名称 | 1 / `submit_ranking_result` |
| 请求设置 | strict true、tool_choice auto、thinking enabled |
| 本地校验 | 通过；结构、六维理由、计划/候选/epoch 内容绑定一致 |
| 判定 | `needs_tiebreaker` |
| 传输编码 / 规范结果 | winner_slot 0 → null，无胜者 |
| 置信度 | 0.5，模型自报，不是校准正确率 |
| Token 用量 | 输入 4,476；输出 3,041；合计 7,517 |
| 金额 | 未定价，不能表示免费 |
| Raw 大小 | 14,609 bytes |
| Raw SHA-256 | `4181df4202c2d98b3fae34cb33312d0190138602380092aee1fa99c7e26ea9fa` |
| 请求指纹 | `7c1327eb25fce9221368fdc7a54e2e3a9d950b3eb486710255b83790ebb1fa7d` |

模型指出：两个 anchor 分别偏重透明功能结局和纤维化通路，但不足以分出有证据支持的优胜者；二者对手术配置和宿主年龄的描述不足，而且都是基准定义，不是实验验证。这说明本次返回了可表达不确定性的合法非 decisive 结果，不等于其科学评价已由研究者认可。

## 可复核证据

本地目录 `.co-scientist-probes/ranking-strict-20260920-001/`（Git 忽略）：

- `profile.yaml`、`manifest.json`：配置、明确 probe 范围、一次请求上限。
- `request.json`、`wire-request.json`：规范请求和实际 HTTP JSON 正文，不保存认证头。
- `events.jsonl`：planned → started → raw_response_persisted → usage_recorded → validated。
- `artifacts/raw/probe-1/`：完整供应商响应及内容寻址 manifest；长度/hash 复核通过。
- `result.json`、`report.json`：规范 Ranking 结果与本次调用用量。

原 Run009 只读复核仍为 needs_attention / SEQ136 / 20 次调用 / 1 场比赛，manifest_hash 与此前导出相同。没有对它授权重试、改变 epoch 或重启 Worker。

## 工程验证和下一步

新增 5 项 probe 离线测试通过：有效结果、非法 JSON、HTTP400、网络失败、缺确认；同时核对原文优先落盘、失败用量保留、禁止覆盖目录、不自动重试、不保存测试密钥。与 33 项严格协议测试合计 38 项通过；Ruff、mypy 和 CLI help 通过。没有重复执行完整离线套件。

下一步：用独立新 Run、显式 strict 配置与有限预算，沿常规 CLI/Worker 验证生成→审查→准入→比赛→反馈/演化→停止/汇总。只有实际事件达到相应阶段才能宣称覆盖；科学拒绝、不确定判定或坏输出应如实保留。之后才能设计重复样本、固定任务的协议/模型对照，而不是将 1/1 当成可靠率结论。
