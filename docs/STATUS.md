# 项目状态 — W0-T2

更新：2026-11-02，Asia/Shanghai。当前为独立功能分支上的工程/契约交付，W0 整包保持 Proposed。

## 起点、合并与工作区保护

- PR #2 的工程验收由项目总控通过，审查固定 head：
  `eb10f6d3ff6e9a7e3564d72c037643ef950455ce`。
- 合并前实际查询：head 未变化、mergeable=true、mergeable_state=clean，
  4 个 Python 3.11/3.12 check runs 均 completed/success，无 commit status 阻断或分支规则，
  无新增 PR review。使用固定预期 SHA 合并，未沿用变化后的 head。
- PR #2 merge commit / 本轮实际起始 main：
  `83d88686ae853d4f634cf68bf68e7065d38e4d71`。
- 本地 main 已更新到该 merge commit，并跟踪 origin/main。
- 原工作区 `/Users/lemintea/Documents/co-scientist` 的旧本地 main 在
  `c2ddbda03f84d5a52f46b47d942b2cce710c919b`，与远端分叉（6 个本地、11 个远端独有提交）。
  先创建 `codex/preserve-local-before-w0-t2` 保留全部旧提交与未提交文件，
  再更新未检出的 main 引用；未 reset/stash/rebase 或覆盖工作文件。
  切换前后 232 个已改/未跟踪文件的内容、Git 差异、暂存区与 status 指纹一致。
- W0-T2 分支：`codex/w0-t2-contracts`；隔离目录 `/private/tmp/co-scientist-w0-t2`。
  本轮独立 PR 不直接合并，最终 head 以该 PR 和 `git rev-parse HEAD` 为准。

## 设计与模块状态

原设计文件位于 `docs/design/m00-accepted-v1.0/` 和 `w0-proposed-v0.1/`。
M00 仍为 design_accepted；reference/ 仍是历史材料；两包 31 个原文件未改。
旧 G3 参考固定为 `7313ca032e4f5f0c84578523e0f5639ad038e7af`，代码未删除、未成为新链依赖。
W0-T0/T1 的工程验收不等于 W0 整包设计验收或科学能力验收。

| 范围 | 当前真实状态 |
|---|---|
| W0-T0、M14a/M12/M15a | PR #2 已合并且总控工程验收通过；输入快照、最小调度、SQLite 事实与恢复保留 |
| M09a | 本轮新增固定 Admission 引用、决定状态及独立 parent/final 资格表示与结构检查 |
| M11a | 本轮新增 M11 意图提案、M03 Inventory 后 Delta 关系、未解析表示及来源一致性检查 |
| LiteraturePort | 本轮新增 search/fetch Protocol 和空结果/失败/不完整/访问层级表示，无真实适配器 |
| M20a / S01–S14 | 新增逐项证据映射，明确已有工程、本轮契约和科学模块待验证部分；未宣称 14 项完整通过 |
| M01–M11 生产科学、真实检索策略、Ranking/Evolution/R3 | 未实施、未科学验收 |
| 独立服务、完整模块 Schema、前端 | 未新增 |

本轮文件范围：

- 新增 `src/co_scientist_next/admission.py`、`delta.py`、`literature.py`、`_validation.py`。
- 新增 `examples/w0-t2-contracts.json`，全部材料显式 synthetic，不含真实论文或专家真值。
- 新增 `tests/next/test_shared_contracts.py`、`test_literature_contract.py`。
- 新增 `docs/W0_CONTRACTS.md`、`W0_SCENARIO_MAP.md`、`verification/w0-t2.txt`。
- 更新本 `STATUS.md`、`AGENTS.md` 与 `docs/design/README.md` 的本轮范围说明。
- 未修改已有调度、持久化、调用执行或旧 G3 生产代码、原设计包文件、打包配置。

契约说明见 [W0_CONTRACTS.md](W0_CONTRACTS.md)，每个科学情境的具体证据与未验证部分见
[W0_SCENARIO_MAP.md](W0_SCENARIO_MAP.md)。未发现需要总控重新裁决的跨模块科学语义冲突。

## 环境与执行命令

本地 macOS / Python 3.11.4，沿用现有
`/Users/lemintea/Documents/co-scientist/.venv/bin/python` 运行测试与开发工具。
无新生产依赖、无新环境安装、无需真实 API 密钥，不强制 .venv；可选兼容 conda/Python 环境。
从本轮功能分支 checkout 执行，python 替换为所选解释器：

```sh
PYTHONPATH=src python -m pytest -q tests/next/test_shared_contracts.py tests/next/test_literature_contract.py
PYTHONPATH=src python -m pytest -q -s tests/next
python -m ruff check src/co_scientist_next tests/next
python -m ruff format --check src/co_scientist_next tests/next
python -m build --wheel --no-isolation
PYTHONPATH=src python -m co_scientist_next --db /tmp/w0-t2-demo.sqlite
```

源码与 wheel 仅需标准库运行；测试需 pytest，lint/build 需现有对应开发工具。
T0/T1 示例仍是“长度 16 → 加倍 32”的工程样例；本轮 JSON 是结构反例，无科学推理入口。

## 验证结果

| 检查 | 实际结果 |
|---|---|
| 新增契约测试 | 37 passed，0 failed，0 skipped |
| 全部新系统测试 tests/next | 52 passed，0 failed，0 skipped；含原 15 项恢复/幂等/快照回归 |
| 真实子进程恢复回归 | 步骤间恢复、成功落库后硬退出回放、发送中硬退出不确定状态均通过 |
| Ruff check / format | 通过；15 个 Python 文件格式检查通过 |
| 31 个原设计文件完整性 | tests/next 原始内容哈希与文件集合检查通过，原文状态未变 |
| Wheel 构建与隔离运行 | 构建通过；python -I 仅从 wheel 导入并检查新增契约，原工程 CLI 完成结果 32 |
| Git diff --check | 全部 staged 文件检查通过 |
| 原用户工作区保护 | 实施前后均核对，232 文件及 index/status/diff 指纹一致 |

实际输出见 [verification/w0-t2.txt](verification/w0-t2.txt)。初次 lint 提示已修复。
GitHub 连接器合并返回集成权限 403，使用同一仓库已配置 Git 凭据的 REST API 成功完成 SHA 约束合并；
凭据未输出或写入文件。初次本地 fast-forward 因分叉被拒，保留全部旧历史后再更新 main。

**未运行：** 本轮旧 G3 全套本地测试、Python 3.12 本地验证、真实 Literature/API 集成、
浏览器、完整 14 个科学情境、真实研究 Run、专家评测和 G3 科学对照。
合并前观察到 PR #2 的远端 Python 3.11/3.12 检查成功，不能据此声称本轮本地已运行这些检查。

## 限制与后续

- 所有契约仅验证结构与引用一致性，不能证明科学资格、实际 Inventory 完整性、材料内容真实性或偏差消除。
  Python 类型与文档表达模块所有权，未建立权限认证或独立身份服务。
- 冻结记录不替代后续 M09 的持久 Admission/Epoch 注册；外部同 ID 重新绑定仍须对象所有者防止。
- Delta 由固定样例声明，无真实语义解析、证据复用或自动回退执行器；M04/M05/M07/M10 科学责任保留。
- LiteraturePort 无真实数据库/适配器/分页执行器/检索策略。时间、范围、访问层级与文本由适配器如实提供，
  单靠结构检查不能判断“摘要谎称全文”。未来外部发送必须通过 M15 保存实际调用和用量。
- A/B 顺序、核心文本和反证输入落库不代表 M10 已实现科学对称性、跨 Match 核心冻结或位置偏差检测。
- 既有 M15 的单进程 POSIX/SQLite、模块稳定调用 key、未知费用保留未知、不确定调用显式恢复等限制仍适用。
  外部重试可能重复效果，不声称 provider exactly-once。
- 后续需科学模块自身的设计批准、固定专家案例、真实执行与验证；W0 整包仍保持 Proposed。
