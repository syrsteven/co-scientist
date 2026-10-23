# 架构与开发

## 执行链

`Workbench → RunService → CoreRunner → Supervisor → Worker → AgentExecutor → Provider`

`co_scientist_web` 独立承载本地 FastAPI、草稿/项目、凭据内存、后台驱动和静态前端。
`co_scientist.release` 提供同一执行链的 CLI、冻结配置、逐 Run 授权与资源安装。
`runtime` 管理 dispatch、容量、retry/recovery、raw-first、ledger 和一致性导出；
`supervisor` 负责科研调度与应用；`domain` 定义科研规则；`adapters` 连接 SQLite、artifact、LLM/PubMed。
版本化 Prompt/Schema/skill 在包资源中，前端不计算科研评分，也不替代原生状态。

G3：4 roots → Ethics/grounding/Generation → Candidate Ethics/Reflection → Ranking/TrueSkill；
G1–G3 各最多两 offspring，累计 P、UCB=μ+σ、0.7 crossover/0.3 mutation、最终 argmax(μ)。
保留 2-valid/6-focal、committed-match 顺序、失败不补槽和 terminal barrier。
科研规范见 [冻结 Core Spec](2608_IDEATION_CORE_SPEC_V1.md)；性能增强 G3 并非完整论文复现。

## 目录与依赖

- `src/co_scientist/`：科学内核、执行/持久化、CLI、包内配置与资源。
- `src/co_scientist_web/`：本地 Web 服务和无需 Node 构建的前端。
- `tests/`：socket-denied Mock、恢复/完整性、浏览器验证。
- `scripts/`：安装与外部发行清单校验工具。
- `examples/`：研究目标；`docs/`：使用、配置、架构、接口、科学规范。
- `constraints.lock`：唯一共享版本约束；`pyproject.toml`：运行依赖与 web/dev/web-test extras。

此版本是全新 DEV 基线，历史来源清单与补丁 SHA 叠层已移出安装包，详细证据留在本地归档。
当前测试直接校验 skill/schema/phase、全部 Prompt 可加载性及科学行为，不依赖历史 commit。
安装包、CLI 和 Web 共用 `co_scientist.__version__`；每次创建 Run 仍冻结当前代码/资源身份，
防止运行中软件变化。此保护不提供旧 Release 恢复兼容，也不能关闭。
原型模块如仍有现行内核调用方，不凭目录名称删除；正式 UI 使用新 Web，不使用旧 Cockpit。

## 开发、测试和构建

```bash
sh scripts/setup.sh --dev
.venv/bin/python -m playwright install chromium
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest --import-mode=importlib -p no:cacheprovider -m 'not online' -q
CO_SCIENTIST_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_web_replay.py -q
.venv/bin/python tests/web_browser.py /tmp/co-scientist-browser-new
.venv/bin/python tests/web_reliability_browser.py /tmp/co-scientist-boundaries-new
.venv/bin/python -m build --no-isolation
```

浏览器输出路径必须全新。Playwright 安装只下载测试工具；Mock 运行硬拒绝科研网络，浏览器仅允许 loopback。
CI 在 Python 3.11/3.12 跑离线回归、Ruff、targeted mypy、compile、wheel/sdist 和 wheel CLI Mock；
3.12 另跑浏览器 G3、SSE/服务重启与停止恢复。Ruff 的历史 migration import-order 排除显式列在 CI，
未将大模块历史 type debt 伪报为已清零。测试不等于真实模型/科研有效性认证。

普通安装不会安装 pytest、mypy、Ruff、build 或 Playwright。不要另建互相冲突的依赖锁。
修改依赖时同步 pyproject 与 constraints，并在干净环境验证普通/开发安装、wheel 和资源。
科学逻辑/Prompt/事件变化必须独立审查；不要借整理目录更改历史 replay、fence、费用或 admission。
本基线不提供旧 Release 数据迁移。新建 Run 的身份校验不匹配时仍拒绝恢复。

构建产物不提交源码库；需要发行完整性清单时在仓库外生成，并显式运行
`python scripts/verify_release.py --manifest /absolute/path/manifest.json`。
默认仅查已列文件，`--strict` 校验完整目录（包括未列文件）；应对独立发行目录操作。
当前仅维护 DEV，不自动创建 tag 或发布构建。源码许可证仍待维护者决定，不擅自添加。
