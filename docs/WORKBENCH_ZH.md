# Workbench v0.4 本地后端

基于 `origin/main@21213ed0d7863547aff5c081e75bfb0c4f875ec6` / Release v0.1.1。
首版 Web 包独立于 `src/co_scientist/`。后续可靠性修复基于 `main@a9a6934`，
仅改变原生 PARTIAL 停止、终局恢复和原子文件写入代码；Profile、Prompt、评分与科研事件契约不变。
新代码身份与旧 Run 不兼容，旧 Run 仍须使用原版本环境。详见 [修复报告](WORKBENCH_RELIABILITY_V1.md)。
本版仅 Autonomous、G3 DEV，不是完整 G10 复现，不包含 Human-in-the-loop。

## 安装和启动

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-web.lock
python -m pip install --no-build-isolation --no-deps -e .
co-scientist ideation resources --from-file /path/to/o200k_base.tiktoken
python -m co_scientist_web --data-dir ./.co-scientist-workbench --port 8765
```

浏览器打开 http://127.0.0.1:8765 。无 `--host`、跨域或多 worker 参数，只监听 loopback。
`resources` 是显式安装步骤；如允许安装阶段获取公开 tokenizer，也可不带 `--from-file`。
不要安装历史 `dist/*0.1.0*` wheel；缺资源时预检明确失败，不会运行时下载。

1. “创建任务”填写研究目标、必要因果链、期望输出，选择默认 G3 与 Mock。
2. 保存服务器草稿；在第三步点击“重新检查输入”。这是离线预检，不检查真实账户。
3. 第四步冻结新 Run；在单独授权窗口查看 Run ID、保守规划、风险上限并明确确认。
4. 后台执行由独立进程驱动，浏览器关闭或 HTTP 服务重启不会取消它。
5. 从项目列表或 URL 中 `?run=<id>#monitor` 恢复监控。SSE 通过 sequence 续传。
6. 点击候选或结果中心查看原文、机制链、预测、证伪、Ethics、Reflection、配对、谱系。
7. “导出五项 Native Trace”创建一致性快照并下载 ZIP。前端阅读报告和视图 JSON 不是 Native Trace。

费用上限为风险授权，不是立即花费。Mock 的费用行也是模拟记录，不是账单。
只在原生 COMPLETE + terminal barrier + FINAL_WINNER 时显示正式 Winner。
不足两次有效比较的候选保留在“评估中”。所有中间榜单都是临时的。

## 终止、故障与恢复

- “终止 Run”请求原生 stop：当前有界调用完成后以 PARTIAL 关闭，不是暂停。
- 终态 resume 返回 `terminal_no_dispatch`，不重新派发，不重开失败槽位。
- 非终态驱动中断后，Web 状态显示 `interrupted_needs_review`，原生 checkpoint 不被篡改；
  检查原生事件后可点击独立的“恢复原 Run 执行（可能产生费用）”，明确确认后才能写入执行请求。
  “重新连接监控（只读）”、页面刷新和打开项目不会恢复执行。
  恢复仍经过 code identity、授权、锁、预算和 fencing，未启动 prepared Run 不能 stop/resume。
- job PID/状态持久保存在独立 Web SQLite；驱动存活以 OS 文件锁为准，不仅信任 PID。
- 不要移动 Run 目录或改写 manifest/plan/auth。旧版本不符时使用创建它的原 Release 环境。
- 导出遇到 `SNAPSHOT_BUSY` 时稍后重试；这不是科研失败，不会为了导出停止驱动。
- HTTP 服务重启后会话/CSRF 令牌变化，重新打开页面；同一驱动和数据根可重新监控。

## 设置与 LIVE 接口（本次未执行真实请求）

设置页仅向同源本地后端 PUT。保存成功/失败后密码输入均清空，GET 只返回布尔配置状态。
服务器凭据只在进程内存，后台驱动通过私有 stdin 管道接收；不写 argv、Run、Web 数据库或日志。
重启服务需重新提供凭据，已有 Mock 驱动不需要凭据；已有独立 LIVE 驱动可持有自己的内存副本。
PubMed 邮箱在新 Run 创建时由原 RunService 冻结，更改设置不影响已创建 Run。
“已配置”不表示账户权限、当前价格或模型能力已经在线验证。

默认服务拒绝 LIVE start。未来若独立获准进行真实研究，需要操作员主动以 `--allow-live` 启动，
在 UI 选择 LIVE，并逐 Run 分别确认费用、价格/权限和 unknown-delivery 重复计费风险。
安装、预检、保存设置均不会自动探测账户、调用模型或 PubMed。本次测试没有启用真实派发。

## M3 状态：仅默认组合可运行，自定义执行未完成

`web-config-builder-v1` 保留模型、代数、root/offspring、预算和时间字段，允许保存自定义草稿。
只有与默认已验证参数完全相同的组合可预检/创建；其他组合返回明确字段错误，不静默回退。
保留原生 RunService 的全配置等值校验。
补充 constraints note 尚无原生映射，因此仅能保存草稿；必要科学约束应明确写入 ResearchGoal。

要开放自定义执行，需要另行增加独立版本化 Profile，并验证 provider/schema/tokenizer/pricing、
调度、终局 barrier、停止/恢复、TrueSkill 及全程预算。模型目录没有实时账户权限含义。
尚未实现这些组合的完整 Mock，因此不得将本版标为 M3 自定义执行完成。

## 安全与部署限制

本地单用户服务，不是远程多用户平台。无 CORS；校验 Host/Origin；API 会话 Cookie 为 HttpOnly/SameSite Strict，
写接口还要求 CSRF header；脚本 CSP 不允许 unsafe-eval。API 只接受逻辑 ID，不能指定磁盘路径或命令。
Data Root 应位于受控本地磁盘，根目录权限 0700；需要 POSIX flock（macOS/Linux，未适配 Windows）。
不记录请求 body、访问日志或 provider 异常文本。Python 进程内存不等于 OS 凭据库，也不保证物理安全擦除。
退出浏览器不会删除已保存科研数据；安全备份和研究资料访问权限仍由本地操作员负责。

## 实际新增接口

均以 `/api/v1` 为前缀：session、health；projects GET/POST、projects/{id} GET/PATCH；
drafts GET/POST、drafts/{id} PATCH；config/defaults、config/models、config/preflight；
settings/status、settings/credentials/{provider} PUT/DELETE、settings/pubmed PUT/DELETE、settings/validation POST；
runs GET/POST、runs/{id}/authorize/start/stop/resume POST、status/events/stream GET；
leaderboard、candidates/{id}、lineage、rankings GET；trace GET；exports POST、exports/{id} GET（ZIP）。

可靠性修复新增 `runs/{id}/monitor?after=<sequence>`：最多返回 1000 个已提交事件，无 Artifact 扫描。
`POST runs/{id}/resume` 现在要求 `{"confirm_execution":true}`；终态仅返回零派发状态。
默认实时监控不生成完整 Trace；详情和导出才调用原生一致性快照，忙时返回可重试状态。
历史回放评分仅来自当前序列边界的原生 μ/σ 投影，不显示未来的审查、配对或终局。

“导入历史 Trace”只读，不等于管理旧 CLI Run；不接受任意历史目录，不移动或修改原生 Run。

相对交接建议增加 session/bootstrap、draft PATCH、run list 和 trace 只读视图，便于鉴权、刷新和复用原 UI。
账户验证接口只做本地状态说明，不自动网络探测。原生来源按 Run/root/binding 显示，不伪造逐 Claim 文献支持。

## 离线复验

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest --import-mode=importlib -p no:cacheprovider -m 'not online' -q
python -m playwright install chromium
python tests/web_browser.py /tmp/new-workbench-browser-acceptance
python -m ruff check src/co_scientist_web tests/test_web.py tests/web_browser.py
python -m mypy --follow-imports=skip src/co_scientist_web
python -m build --no-isolation --outdir /tmp/new-workbench-artifacts
```

浏览器安装阶段可下载公开测试工具；运行阶段浏览器只允许 loopback 请求，Mock 驱动硬拒绝外部 socket。
pytest 禁止真实 socket；浏览器验收包含关页、HTTP 服务重启、候选详情与五项 Trace 下载。
这些是技术 Mock 结果，不证明真实 provider、账户权限或科研有效性。
