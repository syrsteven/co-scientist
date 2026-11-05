# V6 手动阶段测试工作台

本页接入现有 Next 后端，不启动旧 G3 Orchestrator。工程验证与科研质量评价分开；`science_validated=false`。

本轮起点：PR #19 固定 head `256cc9e4f806b56ad58a664fdb4493a8dae978c3`，四项 CI 成功且无阻断后合并，实际 main/merge `758bd4132a1792da01ab996b91d78711c494d6a2`。独立分支 `codex/v6-stage-workbench`，新 PR 保持未合并。

## 启动与重启

现已启动地址：<http://127.0.0.1:8767/>，独立空阶段库 `/private/tmp/co-scientist-v6-stage/runs/stage.sqlite`。启动没有检索、调用或恢复。数据库在系统临时目录，需要长期保留时请在停止服务后备份，或首次启动前通过 `CO_SCIENTIST_STAGE_DB` 指定持久目录；不要切换数据库重发已有任务。

在本次工作目录 `/private/tmp/co-scientist-v6-workbench` 使用已有 conda 环境：

```sh
CO_SCIENTIST_PYTHON=/Users/lemintea/anaconda3/envs/coscientist/bin/python \
CO_SCIENTIST_HISTORY_DB=/private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite \
scripts/start_stage_workbench.sh
```

先停止旧服务再执行相同命令；终端前台运行时按 Ctrl-C。端口占用时不要并行启动另一个数据库实例绕过任务状态。可用 `lsof -nP -iTCP:8767 -sTCP:LISTEN` 找到该工作台 PID，核对命令后发送 SIGINT，再重启。重启只读取，未完成操作必须显式执行/查询。

凭据只从既有后端 `OPENAI_API_KEY` 读取。缺少凭据时显示未配置，没有开发替身回退。启动脚本不写密钥、不打印环境。服务仅绑定回环地址；不是多用户认证部署，不应转发公网。

## 一页人工测试路径

1. **新建研究**：填写原始问题、背景、逐条硬约束、偏好和拟议用途，保存 Brief。创建 Run 前明确选择“Goal 制备／筛查开发测试”，审阅并显式填入测试政策。查看固定 Goal/条件/澄清及 pass/reject；后续草稿不改旧 Run。Goal 是确定性开发前置，绝非真实伦理审查。
2. **文献与背景 → 检索与获取**：手动输入查询，或在资料准备中选择“规划文献查询”，再逐条点击执行计划查询。计划不是已检索。检查返回页、数量、分页及错误；显式获取摘要或可访问全文，选择实际材料范围并写选择理由。Europe PMC 实际请求只在点击时发生。
3. **资料准备**：选择已取得的材料视图阅读，选择宽背景/具体方向；完成阅读后中性综合，再准备定向或开放方向。已有材料、背景和方向使用列表选择。宽背景与 seed 定向准备分别记录；继续补查需要显式操作。查看原文、阅读卡、阴性结果和范围，不能把摘要当全文或把来源数当独立研究数。
4. **方向准备与生成**：为所选方向规划/执行补查、阅读并综合方向资料，检查 readiness。只有已保存 ready 且绑定同一 Goal/seed/背景包才可选择 DIRECT 或 ASSUMPTION_STRUCTURED 生成一个新候选。两者都是单次调用，不是迭代。数量由操作决定，没有固定 ALS 配额。ready 不证明科学正确。
5. **候选与科学阅读**：按主张、情境、机制、证据、新猜想、假设、竞争解释、预测、证伪与限制阅读。来源按钮打开本次实际使用的原文及字符范围；完整候选 JSON 和技术记录折叠展示。科学措辞未改写。
6. **Candidate Ethics／R0**：选择候选，显式填写用途、政策及决策路由；可明确采用非生产概念审查模板并审阅全文，不是生产默认值。development 是政策成熟度，不是“替身”的同义词。非 pass 不能 R0，R0 通过仅等待未实现的 R1。
7. **远端长任务**：Responses 提交后显示保存的 ID 与状态，使用“显式查询同一远端任务”。页面刷新仅读本地，不查询供应商。无 ID uncertain 停止，不能用普通重试绕过；显式恢复只限既有专属入口/授权，未添加通用重发按钮。阅读 Chat 为同步请求，可用“刷新本地状态”观察已保存事实，不能据等待时间推测成功。
8. **人工评估与笔记**：选择 Run、原文视图或候选及内容版本，分别记录相关性/遗漏，情境/阴性/作者措辞，证据忠实性/机制价值/可检验性/主要问题。意见独立保存在后端，不自动进入模型输入；刷新、换浏览器仍可读。导出按钮下载该 Run 的固定输入、原始输出、调用、材料、背景、候选和独立人工意见。

每次点击真实操作可能联网/收费；查看已有研究、刷新和历史入口不收费。没有自动完整科研按钮，也不为获取 pass/ready 自动循环。

## 能力和边界

| 部分 | 当前执行方式 |
|---|---|
| Goal 制备／Goal Ethics | 仅显式选择的确定性开发适配器，不验证科学或伦理准确性 |
| 查询规划、阅读、中性背景、seed/readiness | 现有真实 Chat 适配器，任务各自冻结配置；本轮仅替身验证 |
| 公共文献 | 现有 Europe PMC 搜索、摘要与可访问开放全文；按页显式执行，本轮真实请求 0 |
| DIRECT / ASSUMPTION_STRUCTURED | 现有 Responses 后台，先保存 ID，再显式查询；本轮真实请求 0 |
| Candidate Ethics / R0 | 独立 Responses 后台；非生产政策与真实/替身执行分别标记；本轮仅替身验证 |
| 人工意见／导出 | 实际后端持久化，内容哈希绑定，模型输入隔离 |
| M03、R1、Ranking、Evolution | 新系统未实现，不显示假结果；历史演示不代表新系统能力 |

三个角色显式并存配置：`reading-model.json`（Chat）与 `responses-model.json`（生成/审查分别加载）。均为 gpt-6.1-sol/high/32768、JSON object、无 temperature、600 秒、262144 字节容量，超限拒绝且不裁剪；Responses 保留 background/store=true、truncation=disabled 语义。真实能力质量不由工程测试证明。

V6 附件原件和 SHA 在 `../design/workspace-v6-user-provided/`。唯一派生历史 HTML 默认展示 V5 青光眼，保留 G0–G3、十候选、比较与回放；opaque sandbox 与 CSP 禁止其连接服务，演示笔记仅框架内存。真实 ALS 的可选入口通过 `ReadOnlyStore` 读取独立旧库，不执行迁移、不写注释、不提供科学执行按钮。

写操作仍单进程串行；长 POST 期间只读 GET 使用独立 SQLite 快照，并发 POST 返回 409。用户仍需核实科学内容、来源忠实性、政策适用性和检索遗漏。本轮未评价科学质量、模型表现或组织伦理适用性。
