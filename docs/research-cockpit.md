# Research Cockpit · 本地开发版

## 目标与边界

回答四个问题：系统当前有哪些任务、使用了什么输入、留下了什么产物，以及为什么继续/拒绝/停止。页面读取真实领域状态，不在前端重建第二套调度或准入规则。

读取运行时使用只读快照；设置页可以保存独立的新配置。另提供经确认的暂停、恢复调度和请求收尾入口，写操作经过应用层 / Supervisor。网页不启动 Worker、不直接调用模型；但恢复调度后，仍存活的 Worker 可能继续付费调用。不是原论文性能验证平台，也不保证模型假设正确。

## 启动

项目已有 `.venv` 且已安装 `pip install -e '.[dev]'`，Node.js 22+：

```bash
npm --prefix web run dev
```

访问 <http://127.0.0.1:4173>。静态界面是原生 ES modules + CSS，无前端依赖，无构建步骤。修改代码后刷新页面；修改 `server.mjs` 后重启服务。

默认仅监听 `127.0.0.1`，无需登录。不要通过反向代理、端口隧道或公网托管暴露它：运行中可能包含未发表研究内容，当前没有用户权限隔离。

配置项：

| 环境变量 | 默认值 | 含义 |
|---|---|---|
| `CO_SCIENTIST_WEB_PORT` | `4173` | 本地端口 |
| `CO_SCIENTIST_DATA_DIR` | 自动发现根目录 `.co-scientist*` | 指定一个数据目录，不是数据库文件路径 |
| `CO_SCIENTIST_PYTHON` | 项目 `.venv/bin/python` | 安装了本项目的 Python 解释器；Windows 请指定 `.venv/Scripts/python.exe` |

没有 Python 环境时，已有 `*-export` 目录仍可浏览，页面提示数据库读取失败。也可以点击“选择导出目录”，选择包含 `manifest.json` 的目录；只读取顶层导出 JSON/JSONL，不上传文件，不递归载入 raw_artifacts。浏览器文件选择模式限制相关文件合计 64 MB；更大数据建议使用本地数据库模式。

## 信息架构与阅读路径

| 视图 | 回答的问题 | 可展开的产物 |
|---|---|---|
| 运行总览 | 目前什么状态，哪些角色已执行，为什么停止？ | Supervisor 计划、职责分区、预算与停止 checkpoint、综合反馈 |
| 假设空间 | 提出了什么机制，子代来自谁，能否证伪？ | 不可变内容、机制链、预测、证伪条件、父 content IDs、评审、准入证据和投影 |
| 证据与评审 | 哪些文献被使用，为什么通过/不通过？ | 原始获取摘要、题录级别、PubMed 链接、关键缺陷、维度分数、NoveltyAssessment |
| 竞技场 | 谁和谁比较，判定理由是什么？ | epoch 冻结规则、胜负理由、Elo before/after、固定 anchors、Proximity |
| 任务与产物 | 每一步实际输入和输出是什么？ | intent、attempt、租约、输入快照、外部调用、完整结构化 AgentResult、领域事件 |
| 事件流 | 状态如何一步步变化？ | sequence、时间、causation/correlation、完整 payload；支持搜索和类型筛选 |
| 模型与成本 | 哪个模型做了什么，消耗多少？ | provider/model、持久化调用状态、usage、成本账目、raw artifact 引用/哈希 |

建议先读总览，点击一个阶段，进入任务与调用，再沿假设的评审和证据回溯。输入和完整 JSON 默认折叠，避免大段技术数据遮住科学内容。

## 可视化设置

设置页的菜单按用途分组，不将技术字段简单堆在同一表单：

| 分组 | 菜单 | 可调整内容 |
|---|---|---|
| 研究配置 | 研究目标 | 标题、目标、必须覆盖的因果链、所需产物 |
| 研究配置 | 模型连接 | 五家供应商或 Replay、模型 ID；DeepSeek 单次输出上限、思考模式/强度、超时 |
| 研究配置 | 文献检索 | 科学上下文、题录/摘要、排序、最多五条顺序回退查询 |
| 运行策略 | 评审与演化 | 科研指令协议、完整评审、新颖性门槛、重复阈值、演化上限、Meta-review 轮次/比赛间隔/子代上限 |
| 运行策略 | 竞技场与停止 | Ranking 输出协议、最低覆盖、Top-k、排名/聚类/Elo 窗口；固定契约只读展示 |
| 运行策略 | 计算预算 | 调用、候选、比赛、输入/输出 tokens、USD 上限，均区分 `null` 和 `0` |
| 本地工作台 | 界面偏好 | 自动刷新、刷新间隔、舒适/紧凑密度，不进入研究配置 |

工作流：载入模板/运行副本 → 编辑 → 校验 → 保存为新配置 → 复制命令，在项目根目录终端执行。修改后有未保存提示；覆盖草稿前需确认；保存后再改参数会标记上次保存版本不含这些修改。

Ranking 输出协议默认保持标准 JSON。DeepSeek + Research v1 可显式选择 `deepseek-strict-tool-v1`，只对新运行生效；它是 Beta 选项，不改变科学评分标准。单次兼容检查通过，但 2026-09-20 Run010 第 8 场仍返回非法工具参数；完整闭环未通过，不能保证 JSON 有效。思考模式不关闭，缺失唯一工具结果或参数校验失败时暂停，无文本 fallback。详见[协议与测试边界](ranking-output.md)。

同一菜单新增 v2“扁平理由 / 仅离线验证”，显式把六维理由映射为六个顶层输出字段。保存配置时保留所选版本，不自动升级 v1 或历史运行；新协议的在线兼容性和有效率尚未验证。

保存生成 `.co-scientist-configs/<服务端版本 ID>/goal.yaml`、`profile.yaml`、`settings.json`，每次为新版本，不覆盖同名/旧配置，不修改任何数据库。这个目录已由 `.gitignore` 排除，仍包含研究内容，应按私人研究资料处理。目录结构支持现有 replay 相对资源路径。下载的 YAML 是额外副本；页面的启动命令引用服务器已保存的文件，不引用浏览器下载位置。

密钥不在网页填写或保存，只显示当前 Node 服务子进程是否能看到所需环境变量。这不是 API 连通性测试，不能代表另一个 CLI 终端也已配置。模型可从五家供应商的公开目录选择，或填写精确自定义 ID；启动命令通过 `CO_SCIENTIST_*_MODEL` 传给已有 resolver。日期化价格卡片包含币种、上下文/时段条件、缓存和官方来源，不查询账户授权，不修改历史费用。详见[模型与价格](model-catalog.md)。

明确的能力限制：初审始终必需；当前文献新颖性由完整评审生成，两者联动校验。DeepSeek 以外的生成参数、binary benchmark 行为、多模型路由、任意 Elo 算法和自定义 anchors 暂未开放。条件评审规则只读展示，不承诺当前默认调度会自动触发。现有停止内核始终联合检查 anchor/top-k/cluster，不提供不起作用的关闭开关。

预算不足以满足最低覆盖时显示警告（允许有意的预算中止实验）。费用未完整定价时，USD 上限不是可靠的供应商账单保护；应同时使用调用和 token 限额。不限预算不等于无限自动探索，当前续赛策略依赖有界调用与比赛设置。

自动反馈位于“评审与演化 → Meta-review 反馈闭环”；总结轮次 `0` 为关闭，开启须 Research v1、Evolution 和有限调用/比赛预算。旧运行副本保留关闭状态，新真实模型模板默认 2 次总结、间隔 2 场新增比赛、每次最多 1 子代；Evolution 的 3 次调度上限由修复和反馈驱动任务共享。保存后仍需用新的 Run ID 执行，不改变当前 Run。

有真实 `ResearchFeedbackRecorded` 事件的运行，总览显示“反馈闭环追踪”：最新反馈版本、接收此版本的后续任务及已完成数、Evolution 调度情况和原始事件入口。它不把 PubMed 检索计为反馈，不混用其他 epoch，也不把传入建议当成已经科学采纳。若安全方向要求研究者介入，显示真实暂停原因；现有暂停/恢复按钮不能提交新的科学证据。

界面偏好存储在当前浏览器的 `co-scientist.interface.v1`，立即生效；编辑设置时暂停读取运行快照，不会因轮询覆盖正在输入的内容。未保存研究草稿只存在页面内存，刷新/关闭前会提醒。

## 必须保留的语义（运行视图）

- Supervisor 是唯一调度权威。阶段卡是职责分区，不是线性 wizard 的完成百分比；反思、演化与比赛可以重复。
- initial review 必需，其余由冻结 profile 决定。卡片显示“任务执行成功”，不把它当成科学审查通过。
- 准入取自 manifest 的持久化 `admission_evidence`，匹配内容哈希与 epoch，不从某条 review 的 `pass` 猜测。
- Evolution 子代保留父 content IDs，独立重审；不覆盖父内容、不继承 rating。页面从这些字段绘制血缘。
- Proximity 是候选空间的相似度；文献新颖性来自独立 NoveltyAssessment。
- Elo 只能在相同 epoch 内比较。固定 anchors 单独列出；非 decisive 比赛显示“不更新”。Elo 不是正确率，1200 不是准入门槛。
- 停止面板显示持久化决策及 top-k、cluster diversity、novelty、anchor 等证据；Elo plateau 标注为辅助。
- `pricing_version=unpriced` 的零金额是未知价格，不能显示成免费。token 总量来自已持久化账目，未返回 usage 的在途调用不包含在内。
- 数据库中的 `running` 不是 Worker 正在存活的保证。总览使用在途任务最近两分钟的 heartbeat 和未过期 lease 显示观测结果，不宣称进程健康；没有在途任务时不能据此判断 Worker 离线。导出快照不用于判断当前存活状态。
- 测试工具显式调度的任务在详情标注“测试介入”。功能链路覆盖不等于自主策略或科学能力等效于论文。

## 数据流与接口

```text
浏览器（默认观测，控制需确认）
  GET /api/runs
  GET /api/runs/:id/snapshot
        ↓
Node 本地 HTTP 服务
  ├─ Python bridge → SQLite mode=ro → SqliteRunReadModel 单事务快照
  └─ 顶层白名单导出 JSON / events.jsonl
```

`GET /api/runs` 返回 `{runs, warnings}`。每项包含不透明 `id`、`runId`、`state`、`kind`、`location`，数据库项另含 sequence/updatedAt。客户端使用 `encodeURIComponent(id)` 获取快照，不自己构造数据库路径。数据库运行按最近领域事件时间排序；同一运行的导出副本也可单独选择。

快照沿用既有导出结构：`manifest`、`hypotheses`、`hypothesis_projections`、`reviews`、`novelty_assessments`、`proximity`、`tournament_epochs`、`matches`、`ratings`、`tasks`、`budget_reservations`、`convergence_checkpoints`、`stop_decisions`、`external_calls`、`costs`、`literature`、`events`，附加 `_source` 标明来源和读取时间。

数据库模式默认每 5 秒轮询当前运行，可在设置中改为 10/30/60 秒或关闭；页签不可见、编辑设置时停止轮询。请求串行，过期返回不能覆盖新选择。总览刷新观测时间/心跳；其他视图仅在领域 sequence、任务/租约/调用状态或账目变化时重绘。没有 SSE、模型 token streaming、后台 Worker 启动或浏览器直连模型 SDK。

Python 读取 bridge 使用只读 SQLite URI，不调用写侧 WAL 配置、不执行 Alembic。HTTP 仅接受 localhost Host，拒绝跨源 Origin，无 CORS 放行，静态资源及导出文件均为白名单。控制 bridge 与只读 bridge 分开，不执行数据库迁移或创建 Worker。错误信息不透出内部 traceback。对常见密钥字段递归去敏，所有模型/文献文本做 HTML 转义。研究数据本身仍为敏感内容，去敏不是公开发布许可。

设置使用单独 bridge：`GET /api/settings` 返回仓库模板、已保存配置、模型价目目录和无密钥连接状态；`POST /api/settings/validate` 校验草稿；`POST /api/settings/save` 校验后写入新目录。POST 必须是相同 Origin 的 JSON，请求上限 256 KB。请求对象为 `{name, goal, profile, model}`；复用 `ResearchGoal/CoreProfile` 校验，并限制当前运行器未实现的参数。422 返回 `{ok:false, errors:[{field,message}], warnings}`；保存成功返回规范化 draft、YAML 文本、相对目录、无密钥命令和 `run_started:false`。

## 人工干预与控制接口

运行总览中的“运行监控与人工干预”提供：

- **暂停调度**：running → pausing → paused，不强行取消供应商在途请求。
- **继续调度**：仅 paused → running；不会绕过 needs_attention，也不会启动已退出的 CLI。
- **请求收尾**：running/paused → checkpoint-bound stopping；由 Worker 完成 finalization，保留已产出内容。
- **调整下一次研究**：进入设置，载入当前冻结配置副本，另存为新配置；不修改旧计划和 Elo。

`POST /api/runs/:id/control` 请求为 `{action:"pause"|"resume"|"stop",expected_sequence:整数,confirmed:true}`。目标只能来自服务端已发现的数据库目录；不接受请求体中的数据库路径/Run ID。未知目标 404、导出/过期序号/不允许状态 409、非法字段 422；同源与 JSON/大小校验同设置接口。失败时不自动重试，刷新检查是否已有部分控制事件落盘。

返回 `worker_started:false` 及可手动复制的 Worker 命令。如果原 Worker 已退出，在已配置 API 的终端执行；不要在已存活 Worker 之外盲目再开进程。恢复可能继续产生费用。暂停后需先继续调度或请求收尾，再恢复 Worker。

对于 `needs_attention / provider_output_invalid`，普通继续按钮仍不开放；“输出失败”面板提供独立的“检查并授权一次重试…”入口。先核对失败角色/模型、attempt、预算账本和原始响应，再勾选费用确认。命令只重新排队，成功回执提供 Worker 命令；不修补 JSON、不改结论、不放宽预算。也可用 CLI `run retry-output`。详细限制见[显式输出重试](output-retry.md)。

原始响应可在失败面板或调用详情打开：按 Run/call 归属解析路径，先验证长度/hash，再用纯文本展示；读取不提交领域结果。超过 4 MiB 或路径/完整性校验失败不显示；正文预览超过 65,536 字符时注明截断。失败授权框默认未确认，在打开期间暂停自动轮询；请求异常不自动重复提交。

输出校验失败时，任务可能为恢复/审计保留 `running` 状态和旧租约。角色卡片与任务列表会根据同任务、同 attempt 的失败调用显示“响应校验失败”，不将其当作正在执行；任务详情同时列出当前执行与持久化任务状态。重新排队或进入新 attempt 后不沿用历史失败标签。

更新后必须重启 `npm --prefix web run dev`；旧服务的快照没有 `controlAvailable`，页面禁用控制并显示重启提示。终态 Run 与导出快照始终不可控制。

人工科学 review、自有 hypothesis 和当前研究方向反馈尚未接入领域命令；页面明确显示此边界，没有伪装成成功提交的按钮。应优先完成[审计报告](reports/2026-09-17-paper-alignment-audit.md)中的闭环设计。

原始响应仍保留引用与哈希；点击正文入口时由后端重新读取并校验后显示，单纯看到引用不代表已校验文件。本版不提供任意文件路径读取接口；离线导出或大文件仍使用 CLI。完整已校验 AgentResult 可以展开查看，release invariants 使用现有导出与验证路径。

## 验证

Research v1 的入口在“评审与演化 → 科研指令协议”。五家真实模型模板默认启用，历史副本仍显示 Legacy；切换 Replay 到真实供应商时采用真实模板的正文/协议设置，真实供应商互换保留用户已选策略。此操作仅编辑新配置。详情见 [Research v1](research-protocol.md)。

```bash
npm --prefix web run check
npm --prefix web test
node --test web/tests/model.test.mjs web/tests/settings.test.mjs web/tests/server-routing.test.mjs
.venv/bin/python -m pytest tests/unit/application/test_cockpit.py tests/unit/application/test_cockpit_settings.py tests/unit/application/test_cockpit_control.py tests/unit/application/test_model_catalog.py -q
.venv/bin/ruff check src/co_scientist/application/cockpit*.py tests/unit/application/test_cockpit*.py
.venv/bin/mypy src/co_scientist/application/cockpit.py src/co_scientist/application/cockpit_settings.py
```

Node 测试覆盖费用语义、pending 状态、准入/epoch/血缘、HTML 转义、导出解析，以及 HTTP 的目录约束、只读、Host/Origin 和降级行为。Python 测试覆盖只读数据库、缺失文件不创建、未知运行不创建、快照结构和去敏。HTTP 测试需要 localhost 监听权限，无真实模型调用。

`web/tests/bridge.test.mjs` 另通过真实 Python 子进程和临时 Replay 数据库验证 HTTP 控制全链路及显式 Worker 收尾；自动清理临时数据。需要已安装本项目的 Python 环境，否则该项明确跳过。可通过 `CO_SCIENTIST_PYTHON` 指定解释器；全套 Node 测试并非只靠 mock 验证控制成功。

设置测试覆盖七组分类、菜单错误映射、切换模型不丢研究配置、不可变 Run 副本、偏好限值、同源 JSON/大小约束，以及在线/离线保存文件被真实 `resolve_run_config` 接受的契约。测试不调用模型、不创建 Run。

## 后续扩展接口

下一步是受控的 Worker 启动/日志流与人工科学反馈命令；保留 Supervisor 权威、sequence 乐观锁与明确费用确认，不在前端直接写 SQLite。若升级 React 或加入 SSE，继续复用快照契约与只读投影。多模型对照页需要先建立可比较的 benchmark 协议，不能直接跨运行比较 Elo。
## 候选容量策略

设置 → 总计算预算 → 候选上限行为，可为新运行选择 `capacity-v2`：达到候选数上限后停止新增，已有候选继续审查、准入、排名及最终汇总，仍受调用、token、费用和比赛硬上限约束。旧配置默认 `hard-stop-v1`，达到候选上限会停止整轮；复制旧运行不会自动升级。

CLI 配置可在 `budget` 下添加 `hypothesis_limit_policy: capacity-v2`。该字段随 manifest 冻结，仅影响新运行，不用于修改历史运行。此策略的验证使用离线 Replay；真实模型的输出可靠性需单独测试。

## Meta-review判定与人工核查

设置中的“Meta-review反馈闭环 → 反馈判定协议”提供可选`meta-review-loop-v2`，CLI对应`meta_review.contract_version`。v1仍为默认，旧配置不自动升级。v2随manifest及epoch评价身份冻结，增加内容绑定的各阶段安全记录与当前epoch准入事实，并明确普通科研证据缺口放入coverage_gaps。

`clear`不意味着机制成立；`concern`指具体安全疑问；`insufficient_evidence`应指判定具体安全疑问所需信息不足。full review的not_assessed本身不撤销initial review的安全通过；后续明确阻断仍必须报告。这是给模型的判定说明，不保证模型不会误判，Supervisor仍对两个非clear状态暂停。

总览的“研究者核查入口”链接到完整反馈和候选评审。“提交研究者意见”允许填写署名、依据或异议，并在确认费用后申请独立复评。署名是自报身份，意见不是已验证证据；不会直接覆盖模型结论。

提交仅针对当前`meta_review_requires_scientist_input`阻断，绑定feedback ID/hash、内容、epoch与运行序号。Supervisor和存储事务同时核对剩余调用预算、Meta-review轮次与无未完成任务，原子保存`ScientistFeedbackRecorded`并排队一次复评。复评占用原有轮次，不会自动扩预算。旧manifest及反馈保留，独立复评沿用当前运行的冻结协议；采用反馈v2必须新建配置，不能借人工意见升级011。

提交本身不启动Worker；已有Worker可能立即领取任务，并在复评clear后继续后续运行。concern或insufficient_evidence仍会再次暂停。技术失败走已有显式输出重试机制。网页遇响应不确定时刷新核对事件，不自动重发。快照只读；评审次数已耗尽时不能再申请该复评。

CLI等价入口（先将自己的意见写入文本文件）：

```bash
co-scientist run scientist-feedback RUN_ID --feedback-id FEEDBACK_ID \
  --expected-sequence CURRENT_SEQUENCE --actor "研究者署名" \
  --note-file scientist-note.txt --confirm --data-dir DATA_DIR
```

核对提交回执后，可用`co-scientist worker run RUN_ID --data-dir DATA_DIR`启动Worker。更改研究目标、模型或冻结协议需另存新配置，不支持直接手工指定clear。
