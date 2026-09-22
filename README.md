# Co-Scientist Replica

面向生物医学研究者的 Co-Scientist 开发版：从研究目标出发，生成机制假设、开展文献审查、比较候选、演化修订，并保存可追溯的研究过程。

本项目受 [Nature Co-Scientist 论文](https://www.nature.com/articles/s41586-026-10644-y)启发，为独立实现，不是原作者发布的代码。当前提供 CLI Core Preview 和本地研究驾驶舱，附有晶状体再生示例；工程流程可离线重放，科学效果与原论文性能尚未建立等效性。

## 当前能力

- Supervisor 统一创建和调度任务，控制生命周期、预算、假设准入、停止与最终汇总。
- 六类 Agent 契约与执行入口：Generation、Reflection、Ranking、Evolution、Proximity、Meta-review；新真实模型模板支持由 Supervisor 调度的有界 Meta-review 反馈闭环。
- 假设科学内容不可变；审查覆盖、状态、聚类和 Elo 由事件投影重建。
- initial review 必需，full review 根据 profile；条件触发的深度/观察/模拟/复审尚未完整接线。演化子假设重新审查后才能进入比赛。
- 文献新颖性由 Reflection 评估，Proximity 负责候选间相似度。
- 每个 TournamentEpoch 固定评价规则；非 decisive 比赛不更新 Elo。
- SQLite 保存任务、租约、预算、事件与调用状态，文件系统保存原始响应。
- 支持中断恢复、原始响应重用、确定性导出及事件重放。
- 接入 OpenAI、DeepSeek、Qwen、Gemini、Claude；当前每个 Run 使用一个模型。
- 五家真实模型新模板启用 Research v1：完整科学正文、六角色科研指令、内容绑定的评审依据与六维 Ranking 标准；协议和模型身份冻结到新运行，旧 Replay 不变。
- 文献来源支持 PubMed；离线模式使用仓库内固定响应。
- 本地 Web 研究驾驶舱：运行阶段、任务输入/产物、假设血缘、证据评审、竞技场、事件和成本；支持只读数据库轮询与导出目录离线浏览。
- 可视化设置：七组参数菜单、同源后端校验、保存新运行 YAML 配置与启动命令，以及刷新频率/阅读密度偏好。
- 模型目录：五家供应商共 19 个公开型号及日期化参考报价，保留自定义 ID；见[模型与价格](docs/model-catalog.md)。
- 人工控制：暂停/恢复调度、请求收尾；显式确认和 sequence 校验，不启动 Worker、不修改冻结计划。展示任务心跳与租约，不把 running 当存活证明。
- 科学阻断处理：网页或`run scientist-feedback`提交署名意见，在原预算/Meta-review轮次内排队独立复评；保留原结论，复评非clear仍暂停。提交不启动Worker，但存活Worker可能继续付费执行。详见[人工核查与复评](docs/research-cockpit.md#meta-review判定与人工核查)。

尚未实现：Web 创建运行/启动 Worker、任意阶段人工反馈与自有假设导入、角色级多模型合作、自动模型路由、单/多模型对照实验平台、原论文完整基准复现、分布式部署。当前科学行为和输入质量的具体缺口见[论文对齐审计与验收指南](docs/reports/2026-09-17-paper-alignment-audit.md)，不要把六角色覆盖测试当自主工作流等效证明。

## 打开可视化研究驾驶舱

安装好下方 Python 项目环境后，另需 Node.js 22+。在项目根目录运行（无需 `npm install`）：

```bash
npm --prefix web run dev
```

打开 [本地研究驾驶舱](http://127.0.0.1:4173)。默认发现项目根目录 `.co-scientist*` 下的 `co-scientist.db`，以及 `*-export` 导出目录。左上角切换运行；点击任一阶段 → 任务 → 调用，展开输入和结构化产物；假设卡片可查看机制链、证伪条件、评审与准入证据。

数据库模式每 5 秒读取一致性快照，CLI 在另一个终端执行时可以同时观察。导出模式是历史快照，不会自动更新。页面不会启动 Worker、调用模型、迁移数据库或上传本地目录；无需在浏览器配置 API key。

“运行总览 → 运行监控与人工干预”提供有限生命周期控制。暂停不保证取消供应商在途请求；继续调度不保证原 CLI 进程仍在；需要时按提示手动启动 Worker。更新 `web/server.mjs` 后必须重启网页服务才有新的控制接口。

左侧进入“设置”，按研究目标 → 模型连接 → 文献检索 → 评审与演化 → 竞技场与停止 → 计算预算逐项调整。可以从当前运行复制、载入仓库模板，或读取已保存配置。点击“校验配置”，再“保存为新配置”：文件保存在项目 `.co-scientist-configs/<版本>/`（Git 已忽略），页面提供启动命令。保存本身不会运行模型，也不改变历史 Run；真正执行 CLI 命令时才产生在线调用。界面偏好单独保存到浏览器，可调整自动刷新、5/10/30/60 秒刷新间隔和阅读密度。

旧运行副本仍保留 **Legacy**。要使用本轮科研输入修复，在“文献检索”确认科学上下文已开启，再在“评审与演化 → 科研指令协议”选择 **Research v1**，保存后使用新 Run ID 启动；不要用旧 Run 的 resume 代替升级。新仓库模板已默认启用，内置 Replay 继续使用 Legacy。具体输入、评分维度及验收方式见 [Research v1 协议](docs/research-protocol.md)。

“评审与演化 → Meta-review 反馈闭环”可设置总结轮次、比赛间隔和每次反馈的子代上限。新真实模型模板默认最多 2 次总结、间隔至少 2 场新增比赛、每次最多 1 个子代；设总结轮次为 `0` 关闭。开启时需要 Research v1、启用 Evolution，以及有限的调用数和比赛数预算。运行总览的“反馈闭环追踪”展示反馈版本和接收到该版本的下游任务；传入反馈不等于科学上采纳或改进。旧 Run 不会自动出现新策略。

DeepSeek + Research v1 可在“竞技场与停止 → Ranking 输出协议”显式选择严格工具输出，仅用于新运行的 Ranking。默认仍为标准 JSON，不升级历史 Run。一次兼容性检查通过，但[Run010 真实测试](docs/reports/2026-09-20-strict-workflow-live.md)在 7 场比赛及一次科学 Meta-review 后，第 8 场仍因非法工具参数暂停；完整闭环未通过，不保证 JSON 有效。使用限制及实现见[Ranking 严格输出协议](docs/ranking-output.md)。原始响应窗口提供只读错误位置提示，不自动修补或重试。

另提供实验性 `deepseek-strict-tool-v2`，把六维理由改为顶层字段后无损映射回原结果。仅离线验证，不自动替换 v1，也不保证减少在线错误；需在上述设置中显式选择并创建新 Run。

指定不同数据目录或 Python 解释器：

```bash
CO_SCIENTIST_DATA_DIR=.co-scientist-deepseek \
CO_SCIENTIST_PYTHON="$PWD/.venv/bin/python" \
npm --prefix web run dev
```

详情见 [驾驶舱使用与前端设计](docs/research-cockpit.md)，包含七个视图、API 契约、测试方法和当前边界。

## 安装

需要 Python 3.11 或 3.12。克隆本仓库后进入项目根目录：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pip install build
co-scientist config check --data-dir .co-scientist
```

命令会初始化或迁移数据库。请选择新的数据目录进行独立实验；不要手动删除有研究记录的数据库。Windows 可使用 `.venv\Scripts\activate` 激活环境，下文密钥输入示例针对 macOS zsh。

## 首次体验：无需密钥的离线运行

```bash
co-scientist run execute \
  --run-id lens-replay-001 \
  --goal examples/lens_regeneration_goal.yaml \
  --profile configs/profiles/core_preview.yaml \
  --provider replay \
  --data-dir .co-scientist-replay
```

示例使用保存的响应执行流程，不调用模型或实时 PubMed，不产生 API 费用。成功时输出 `state: completed` 和 `stop_reason: quality_converged`。这验证程序对固定输入的执行行为，不代表假设经过科学验证。

## 配置真实模型

密钥通过进程环境变量读取，不应写进研究目标、配置 YAML 或 Git。项目不自动读取 `.env`。

| 供应商参数 | 密钥变量 | 模型变量 | 配置文件 |
|---|---|---|---|
| `openai` | `OPENAI_API_KEY` | `CO_SCIENTIST_OPENAI_MODEL` | `configs/profiles/core_preview_online.yaml` |
| `deepseek` | `DEEPSEEK_API_KEY` | `CO_SCIENTIST_DEEPSEEK_MODEL` | `configs/profiles/core_preview_deepseek.yaml` |
| `qwen` | `DASHSCOPE_API_KEY` | `CO_SCIENTIST_QWEN_MODEL` | `configs/profiles/core_preview_qwen.yaml` |
| `gemini` | `GEMINI_API_KEY` | `CO_SCIENTIST_GEMINI_MODEL` | `configs/profiles/core_preview_gemini.yaml` |
| `claude` | `ANTHROPIC_API_KEY` | `CO_SCIENTIST_CLAUDE_MODEL` | `configs/profiles/core_preview_claude.yaml` |

模型 ID 必须是该账户可通过 API 调用的具体模型名称。Qwen 当前使用中国大陆 DashScope 端点，密钥区域须匹配。不同模型对 JSON 输出的支持可能不同，接口接入不等于所有型号均已实测。

在 macOS zsh 中隐藏输入两家密钥：

```bash
read -s "OPENAI_API_KEY?OpenAI API Key: "
export OPENAI_API_KEY
echo
read -s "DEEPSEEK_API_KEY?DeepSeek API Key: "
export DEEPSEEK_API_KEY
echo
export CO_SCIENTIST_OPENAI_MODEL='YOUR_OPENAI_MODEL_ID'
export CO_SCIENTIST_DEEPSEEK_MODEL='YOUR_DEEPSEEK_MODEL_ID'
```

这些设置只对当前终端及其子进程有效。在另一个终端或桌面应用中运行时，需要在那里配置环境。

## 用 DeepSeek 和 OpenAI 测试完整流程

五家真实模型模板已启用摘要证据和有限 Evolution：修复不合格候选与根据 Meta-review 改进合格父代，共享最多 3 次 Evolution 调度；单次修复最多 2 个子代，反馈驱动时另受每次最多 1 个子代限制。
可在 profile 的 `evolution` 与 `meta_review` 参数组调节。要关闭全部 Evolution，需同时将两组的 `max_rounds` 设为 `0`。预算、质量收敛、人工停止和安全方向检查优先，不保证每个 Run 都用完所有轮次。
配置对新运行生效；真实研究假设可能未通过评审，因此命令执行不保证最终产生排名。
详细流程与限制见 [多供应商指南](docs/multi-provider.md)。

```bash
co-scientist run execute \
  --run-id lens-deepseek-001 \
  --goal examples/lens_regeneration_goal.yaml \
  --profile configs/profiles/core_preview_deepseek.yaml \
  --provider deepseek --data-dir .co-scientist-deepseek

co-scientist run execute \
  --run-id lens-openai-001 \
  --goal examples/lens_regeneration_goal.yaml \
  --profile configs/profiles/core_preview_online.yaml \
  --provider openai --data-dir .co-scientist-openai
```

在线配置使用真实 PubMed 和真实模型，会产生供应商费用。CLI 不检查 `CO_SCIENTIST_NETWORK_ONLINE`；该变量只控制在线测试是否启用。

每个新实验使用新的 run ID。以上两次运行使用相同研究目标和策略，但实时文献和随机生成可能不同，尚不构成严格的模型性能基准；不同 epoch 的 Elo 也不能直接作为跨模型分数比较。

## 研究目标与预算

复制 `examples/lens_regeneration_goal.yaml` 并修改以下字段：

```yaml
title: 研究标题
goal: >
  描述要解决的问题、机制范围、竞争解释和希望区分的实验。
required_causal_chain:
  - early_perturbation
  - cell_state_transition
  - tissue_outcome
required_outputs:
  - causal_mechanism
  - falsifiers
  - discriminating_experiments
```

通过 `--goal` 选择目标，通过 `--profile` 选择审查、比赛、停止和预算策略。当前预览仍包含晶状体示例锚点，新研究领域需要匹配的锚点及评价协议，不应直接把示例排名解释为通用研究质量。

配置中的 `budget` 可限制调用数、输入/输出 token、假设数、比赛数和美元上限，`null` 表示该项无限制。现有配置最多 40 次计数调用（含文献任务）、6 个假设和 12 场比赛。当前美元费用未计价，不能用记录中的零美元判断免费，也不能依赖美元上限准确约束实际账单；应配合调用/token 限额与供应商账户预算。

## 状态、恢复与停止

```bash
co-scientist run status lens-deepseek-001 --data-dir .co-scientist-deepseek
co-scientist worker run lens-deepseek-001 --data-dir .co-scientist-deepseek
```

`worker run` 从持久化状态继续。已经完成、失败或取消的 Run 不会重新启动。若调用已返回但原始字节尚未持久化便中断，恢复时仍可能再次请求供应商。

生命周期操作需要使用 `run status` 返回的最新 `current_sequence` 替换下列 `N`：

```bash
co-scientist run pause RUN_ID --expected-sequence N --data-dir DATA_DIR
co-scientist run resume RUN_ID --expected-sequence N --data-dir DATA_DIR
co-scientist run stop RUN_ID --expected-sequence N --data-dir DATA_DIR
co-scientist run cancel RUN_ID --expected-sequence N --data-dir DATA_DIR
```

`resume` 修改暂停状态后，再用 `worker run` 执行任务。`stop` 请求部分结果汇总；`cancel` 直接取消。并发状态变化时应重新查询序号。

若为 `needs_attention / provider_output_invalid`（例如模型返回坏 JSON），普通 `resume` 不会绕过失败。可以明确授权一次**原任务、原输入、原模型**的重新调用：

```bash
co-scientist run retry-output RUN_ID --call-id FAILED_CALL_ID \
  --expected-sequence N --confirm --data-dir DATA_DIR
# 上一步只重新排队，不启动 Worker；确认没有其他 Worker 后再执行：
co-scientist worker run RUN_ID --data-dir DATA_DIR
```

失败 call ID 来自前端事件详情的 `RunNeedsAttention.external_call_id` 或导出 `external_calls.json`。新尝试可能收费；旧 raw、失败状态和 token/费用保留，绝不修补 JSON 或覆盖模型结论。必须有有限的剩余调用预算且未达到任务 `max_attempts`（当前默认 3，包含首次及网络恢复尝试）；再次无效仍暂停。

也可在网页“运行总览 → 运行监控与人工干预 → 输出失败”中查看原始响应、核对预算和次数，点击“检查并授权一次重试…”，明确勾选费用确认后重新排队。页面不启动 Worker。更新服务代码后需重启网页服务；导出目录保持只读。完整限制与审计方法见[显式输出重试](docs/output-retry.md)。

## 导出与结果阅读

```bash
co-scientist run export lens-deepseek-001 \
  --data-dir .co-scientist-deepseek --output lens-deepseek-001-export
co-scientist replay lens-deepseek-001 --data-dir .co-scientist-deepseek
```

导出路径必须不存在，避免覆盖结果。同一运行未发生变化时，重复导出的内容应一致。

| 文件 | 用途 |
|---|---|
| `manifest.json` | 固定研究目标、策略、模型和来源信息 |
| `hypotheses.json` | 不可变假设内容 |
| `hypothesis_projections.json` | 当前状态和审查覆盖 |
| `reviews.json`、`novelty_assessments.json` | 审查与新颖性证据 |
| `matches.json`、`ratings.json` | 比赛结果与 epoch 内排名 |
| `literature.json` | 文献来源 |
| `events.jsonl`、`tasks.json` | 执行审计记录 |
| `external_calls.json`、`raw_artifacts/` | 调用记录与原始响应 |
| `costs.json`、`budget_reservations.json` | token 使用及预算记录 |
| `convergence_checkpoints.json`、`stop_decisions.json` | 停止条件依据 |

生成假设需要研究者检查原始文献、因果合理性和可证伪实验。排序是系统评价结果，不是临床结论或实验验证。

## 开发与验证

```bash
python -m pytest tests/unit tests/contract tests/scenario tests/smoke -q -m 'not online'
python -m ruff check src tests alembic
python -m mypy src/co_scientist
git diff --check
```

五家接口包含模拟契约测试；真实在线行为需要分别实测。OpenAI/PubMed 在线测试另需密钥、模型 ID 和 `CO_SCIENTIST_NETWORK_ONLINE=1`，然后运行：

```bash
python -m pytest tests/contract/llm/test_openai_online.py \
  tests/contract/literature/test_pubmed_online.py \
  tests/smoke/test_lens_online_smoke.py -q -m online
```

## 代码导航

```text
src/co_scientist/
  domain/         科学内容、状态、预算和比赛规则
  supervisor/     任务编排与结果应用
  agents/         提示请求、输出 schema 和结果校验
  runtime/        Worker、外部调用、恢复与检查点
  adapters/       模型、PubMed、SQLite 和原始文件存储
  application/    配置与命令/查询边界
  cli/            终端入口
  events/         事件模型与投影
  export/         可复现结果导出
  skills/         六类 Agent 的内置资源
configs/profiles/ 运行策略
examples/         晶状体目标与固定响应
tests/            单元、契约、场景和 smoke 测试
docs/             设计与操作说明
```

更多细节见 [Core Preview](docs/core-preview.md)、[多供应商使用说明](docs/multi-provider.md)及 `docs/superpowers/` 中的设计文档。
