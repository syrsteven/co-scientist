# Codex 任务：将 Co-Scientist Workbench v0.4 接入 main v0.1.1

## 基线与输入

- 代码仓库：`https://github.com/syrsteven/co-scientist`，以执行时最新 `origin/main` 为准。本次审核 SHA：`21213ed0d7863547aff5c081e75bfb0c4f875ec6`。先执行 `git status --short`、`git rev-parse HEAD`、`git fetch origin main`，记录实际使用的 SHA。如存在未提交变更，在独立 worktree/分支开发，不覆盖用户工作树。
- 本交接包 `frontend/` 是可编辑的五页 UI 原型（HTML/CSS/JS）；`frontend/workbench.html` 是可单独打开的**构建快照**，不是唯一源码。请优先使用 `frontend/index.html`、`styles.css`、`fixture.js`、`app.js`、`workbench.js`，保留现有布局、导航、候选榜单、候选详情、回放和结果页。
- `API_CONTRACT.md` 是建议接口清单，不是现存服务。结合实际源码设计后可细化，但必须解释修改。
- Python 使用 3.12（项目约束 3.11/3.12）；`dist/*0.1.0*` 是历史构建，**禁止作为最新 v0.1.1 包安装**。从当前源码新构建。
- 本次只开发 Autonomous 模式；**不做 Human-in-the-loop、科研算法优化、G10 完整论文复现声明**。

## 最高优先级的安全与一致性要求

1. 严格复用 `co_scientist.release.service.RunService` / CoreRunner / 原生 SQLite、Raw、ledger、fencing、TrueSkill、UCB 和 `ideation_trace`；禁止在前端或 Web 层重新实现科研计算、模型重试/预算或 Final Winner 判定。
2. Web 代码应位于 `src/co_scientist_web/`、`web/` 等**独立于 `src/co_scientist/`**的位置。`RunService.code_identity()` 会扫描后者文件；新增 Web 文件不能无意破坏既有 Run 的冻结代码身份。历史 v0.1.0 Run 继续使用原环境。
3. 默认所有测试、CI 与示例运行仅使用**合成 MockTransport**。禁止真实 OpenAI、DeepSeek、PubMed 请求和付费/授权探测；不要读取或打印用户真实密钥。只有用户将来在 UI 明确选择 LIVE、逐 Run 确认权限/价格、费用上限及 unknown-delivery 重复计费风险时，才允许发出真实调用。开发期间不得执行这个 LIVE 流程。
4. `MOCK_ONLY` 与 `LIVE_SINGLE_DISPATCH` 完全隔离；Mock 无需凭据。`stop()` 是终止请求，最终 PARTIAL，**不是**可继续暂停；仅未终结、原生允许恢复的 Run 才能 `resume()`。任何运行中阶段都不得虚构 FINAL_WINNER。
5. 服务仅监听 `127.0.0.1`，同源提供网页与 API，默认禁用跨域；为任何修改型接口添加会话认证/CSRF/Origin 防护。请求只接收安全的逻辑 `project_id/run_id`，服务端目录映射到固定可写 Data Root，禁止客户端自定任意磁盘路径、数据库 URL、执行命令或访问其他目录。
6. OpenAI/DeepSeek API Key 通过“设置”页的专门接口提交给受控本地服务，服务端只在**进程内存**短期保存（或者若实现 OS 凭据库需单独说明和测试），不写 localStorage、任务草稿、YAML、数据库、日志、响应、异常、SSE、导出文件或 Git。页面只显示“已配置/未配置/未验证”，不回显 key。重启后要求重新提供；不得称内存保存为永久凭据。PubMed 邮箱应在创建每个真实 Run 时由 `RunService.create()` 按原设计冻结，更改邮箱不影响已有 Run。
7. 下拉菜单的模型目录不等于已接入本 Release，也不等于账户有权限。冻结默认是 Generation `gpt-6.1-sol` 与其它角色 `deepseek-flash`。`application/model_catalog.py` 是 2026-09-17 参考快照；自定义模型未完成端到端适配前显示“待支持/未验证”，不得假装可真实运行或自动回退默认模型。

## 迭代 M1：默认 G3 Mock 的真实端到端闭环（必须完成）

- 在独立 Web 包实现 FastAPI（或说明同等理由），同源服务五页前端；不需要前端重做设计。
- 实现最小服务器 Project / Draft 存储（可用独立 web SQLite/JSON，但**不得**修改原生科学数据库），支持列表、创建、保存草稿、项目关联 Run。保留原有本地演示数据但必须明确标记 DEMO，不能混入真实 Run 列表。
- `GET /health`、`GET /config/defaults`、`GET /config/models`、`POST /config/preflight`：默认模板读取已发行 G3 配置，预检负责 goal 校验、tokenizer/资源检查、预算核算、模型/角色兼容性；失败按字段和可修复原因返回，不派发科学请求。Tokenizer 缺失时提示显式安装/离线导入，不在执行阶段静默联网。
- `POST /runs` 仅接受通过预检的草稿/配置，调用 `RunService.create(..., mock=True)`，冻结为新 Run；`POST /runs/{id}/authorize` 对 Mock 也走现有授权边界；`POST /runs/{id}/start` 在**独立于 HTTP 请求生命周期的后台驱动**运行。浏览器刷新/关闭不能停止任务；启动幂等、单 Run 单驱动，明确记录 job PID/状态并能恢复监控。不得用 FastAPI 请求一直 await 整场 G3。
- `GET /runs/{id}/status`、`GET /runs/{id}/events?after=N` 与 SSE `/runs/{id}/stream`（重连从序号续传）展示当前状态、代际、任务阶段、预算费用、活动预留、异常。`prepared` 的 events 返回空集、export 明确不可用；不得把无数据库当作服务崩溃。
- 实时候选榜单来自**原生已提交科学事件**，重用 `replay_bayesian_rating` 等只读投影，排名 μ 递减，显示 σ、有效 decisive 次数。未达到最低比较次数的候选显示“评估中”。同时提供 candidate 详情（原始 title、claim、完整 mechanism_chain、assumptions、predictions、falsifiers、Reflection、Ethics、真实来源/证据绑定、Rating 和父代关系）、lineage、ranking history。摘要只能忠实压缩原始 `claim`，不偷偷额外调用模型或编造证据。根候选代数应由原生 Generation fact 判断，不猜 ID。
- 结果中心严格使用原生 `IdeationFinalSelectionV1`：只在 COMPLETE + terminal barrier 完成 + `FINAL_WINNER` 时显示正式获胜者；否则 best-so-far / PARTIAL。导出走 v0.1.1 一致性只读 `RunService.export()`；busy 时提示稍后重试，不能发布混合时点结果。正式五项 Trace 与阅读版导出分别标注。

## 迭代 M2：设置页 + 真实运行接入（离线验证即可）

- 将“设置”页连接到 `settings/status`、`credentials/{openai|deepseek}`、`settings/pubmed` 端点。密钥只通过安全的 POST/PUT 到同源本地后端；响应无敏感字段；保存后清空输入，支持覆盖、清除，明确“已填写 ≠ 已验证账户权限”。
- LIVE Run 创建需校验两类 Key、PubMed 联系邮箱、冻结配置、Tokenizer、模型能力及预算；服务器创建时冻结邮箱及 profile/hash。授权页面展示确切风险上限（默认 G3 为 $60）、保守规划、可能重复计费风险、模型及运行 ID。要求用户**分别明确确认**价格/权限、费用上限及未知投递风险；严禁自动勾选或直接从“新建任务”跳过授权。
- 提供真实模式的 start、stop、resume 接口包装，重复点击 start 不得二次派发；旧 Run 身份不符时明确提示需要原版本环境，禁止绕过 code_identity。所有 LIVE 路径使用 socket-denied/fake credentials 测试，**本次不得实际调用模型或 PubMed**。

## 迭代 M3：模型、代数、预算自定义（允许分阶段交付，不能绕过安全验证）

- 前端保留可编辑的 Generation 模型、Review/Evolution 模型、G0→Gn 代数、root slots、每代 offspring slots、风险预算、时长字段。
- 后端设计版本化 `Config Builder`、合法能力矩阵与成本/dispatch 预算规划；默认 Profile 仍可原样运行。注意现有 `RunService.validate()` 要求 profile 语义等于内置 G3，`FullIdeationConfig.cycle_identity()` 区分 G3/G10，不能只修改 YAML、删除等值检查或硬编码允许 G5/G10。
- 若要实际开放某个自定义组合，必须先证明 provider API/JSON/schema/tokenizer/能力/价格、监督调度、停止/恢复、代际终局、TrueSkill、成本预留全部通过相应完整 Mock，新增版本化 profile 并保留原有 v0.1.1 Run 兼容隔离。
- 本次若无法安全完成 M3，不要为了进度假装已支持；UI 明确阻止真实创建/启动该组合，并提交可执行的 M3 设计及测试缺口。**M1、M2 的完整闭环优先于解冻不安全配置。**

## 必须覆盖的验收测试

详细场景见同包 `ACCEPTANCE.md`。至少包含：默认 G3 Mock 从网页创建至 COMPLETE + 五项 Trace；创建前页面刷新与 prepared 状态；双击 Start 单驱动；中途刷新后榜单重建；有效比较数不够的候选独立分组；正确展示 PARTIAL；终态 resume 零派发；停止后非继续；模型不兼容/预算不足/缺资源明确拒绝；密钥永不泄漏到浏览器持久存储、日志、事件和导出；通过安全 run_id 拒绝路径穿越；导出并发 busy 可恢复；Mock 禁止任何真实外部 socket。

## 开发约束与交付格式

- 可以安装公开的开发依赖以运行本地测试，但任何 scientific provider 请求、任何自动付费探测均禁止。执行测试前移除真实 `OPENAI_API_KEY` / `DEEPSEEK_API_KEY`，并为 Mock 强制网络拦截。禁止读取 sealed HOLDOUT 或历史敏感 raw。禁止推送 GitHub、修改远端或覆盖用户的现有工作目录；除非用户另行授权。
- 不修改科研主链路（Supervisor、Worker、CoreRunner、科研事件、评分和演化算法），不改原始预算/授权保护，不改变 v0.1.1 默认 profile 身份。必要时以独立代码与 adapter 扩展，说明不能保持兼容的原因。
- 完成后给出：(a) 实际基准 commit / 新工作分支及目录；(b) 启动命令、浏览器地址；(c) M1/M2/M3 完成状态；(d) 代码 diff 及新增 API 清单；(e) 真实执行的测试命令、pass/fail/skip；(f) 一次完整 Mock 的 run_id、终局状态、候选数、五项导出路径；(g) 剩余问题与优先级。任何未跑通项必须标为未完成，不得伪报 PASS。
