# v0.1.1 可靠性修复与验证

基准：`ideation-dev-release-v0.1.0` / `baa13351ec3cbea8a1e6e81cd4c1432377e315cf`。
修复分支：`codex/reliability-hardening-v0.1.1`。未 push、merge 或创建 tag。
在独立 clone 实施，原 Release 和原开发工作树不改动。

## 已确认缺陷

| 问题 | 基准行为 / 原因 | 修复边界 |
|---|---|---|
| P1 prepared export | `RunService.export` 初始化 CoreRunner，执行数据库初始化后因无 Run 记录触发 `KeyError: unknown run`；随后 status 同样失败 | prepared 先拒绝导出；events 返回空集；status 明确 prepared；已启动导出只用只读连接，无 CoreRunner/迁移 |
| P2-A 自定义配置 | watchdog、ranking role dispatch cap、capability 可变，但 budget/permit 限额固定 | 只接受与发行内置配置语义完全相同的 profile；budget 同时核对完整 typed execution config。研究目标仍可独立填写 |
| P2-B tokenizer | 最终路径直接 `xb` 写入；中断残片永久触发 identity mismatch | 安装专用 flock、同目录私有临时文件、flush/fsync、SHA 校验和原子 replace；坏文件在替换成功前保留 |
| P2-C 并发 export | 多个独立 DB session、ledger 和 artifacts 读取混用不同时间点 | 两个 SQLite 只读 backup；固定副本读取；源连接 data_version 和 artifact 清单 hash 检测跨存储变化；变化则 busy 拒绝发布，不写混合输出 |
| P2-D 旧 Cockpit | 完成原生 G3 后，旧 read-model 读取 rating 事件中不存在的 `evaluation_rules_hash`，出现 KeyError | Cockpit snapshot 在进入旧投影前明确 `UNSUPPORTED_LEGACY_G3`；正式 RunService/native trace 不受影响 |
| P3 清单遗漏 | 原 verifier 只核对清单内文件，额外文件不会导致失败；未解析 `--strict` | 默认明确 hash-only；显式 strict 检查所有额外文件、符号链接和清单外内容 |

**未误报为漏洞：**零价格与顶层 budget overlay 不一致本来就会被拒绝。
本次没有移除这些保护。新 profile 限制是部署入口冻结，不是改变科研算法。

## RED / GREEN

新增 `tests/test_hardening.py`：18 项通过。原版复验子集：6 failed、2 passed、10 deselected；
六个失败对应 prepared export、三个配置变更、坏 tokenizer 和并发数据库导出。
两个原本通过的是已有 pricing / budget-overlay 拒绝保护。
另对原完成 G3 数据调用旧 Cockpit，确认为 `KeyError('evaluation_rules_hash')`。
独立微型发行目录包含未列入清单文件时，旧 verifier 甚至接受 `--strict` 并打印 PASS；
新 verifier 在同类场景拒绝。未运行真实 API。

新测试还覆盖：临时文件 fsync 失败、四线程同时安装、重复安装、坏源文件不覆盖原文件、
相同 profile 副本、旧 code identity 拒绝、ledger/artifact 并发变化。
现有长 G3 测试保留 restart/replay、重复导出、费用和终局选择断言，未放宽其科学断言。
最终完整离线套件：**121 passed、0 failed、0 skipped**（283.49 秒）。
中间一次整套为 120 passed / 1 failed，原因是新增 ledger 注入测试只做了不改变值的 UPDATE，
没有可靠触发所需提交变化；改为真实改变测试用 blocked 状态后，focused 和整套均通过。

## 验证命令与环境

本地 Python 3.12；清空环境变量（尤其凭据），设置 clone-first PYTHONPATH；
只复用已安装依赖及只读公开 tokenizer 文件。pytest 的 autouse fixture 拒绝真实 socket。
这不是重新联网安装全部依赖的干净环境认证。

```bash
python -m pytest tests/test_hardening.py --import-mode=importlib -p no:cacheprovider -q
python -m pytest --import-mode=importlib -p no:cacheprovider -m 'not online' -q
python -m mypy --follow-imports=skip src/co_scientist/release \
  src/co_scientist/runtime/trace_snapshot.py src/co_scientist/runtime/ideation_trace.py \
  scripts/verify_release.py src/co_scientist/application/cockpit.py
PYTHONPYCACHEPREFIX=/tmp/co-scientist-pyc python -m compileall -q src tests scripts
git diff --check
python -m build --no-isolation --outdir /tmp/co-scientist-v0.1.1-artifacts
python -m pip install --no-deps --target /tmp/co-scientist-wheel /tmp/co-scientist-v0.1.1-artifacts/*.whl
```

wheel 安装后从仓库外执行 CLI `--help` / `ideation validate`；以 installed-package 优先路径运行
资源完整性、无凭据零派发、长 G3/restart/replay 测试，不能退回源码包导入。
这四项 installed-wheel 测试实际为 4 passed；CLI help/validate 另行验证通过。

全树 Ruff 在原版和补丁版均有六项 I001（未修改的 packaged Alembic env、0001–0004、
persistence/migrations.py）。本次不为清理排序而改变历史迁移身份。
CI 对这六个旧文件的 I001 显式隔离，其余整个源码/tests/scripts 执行 Ruff；新改动无诊断。
必要 mypy 为 targeted / follow-imports=skip，不声称全科研内核类型检查已清零。
本机 Python 3.11 既有 httpx/click 导入异常，未运行 3.11 测试；CI 配置 3.11/3.12，尚未远程执行。

## 科研行为对照

原版和补丁版使用相同 synthetic goal、固定 Run UUID 和原有 MockTransport 完成 G0→G3。
均有 396 个事件、10 个候选、13 次 decisive matches、26 次 posterior projections、6 次 reproduction，
正式 winner 均为 `hyp-root-slot-1`。83 个科学事件的内容、顺序、候选、父代、算子、评分和选择一致。
比较排除执行 provenance：result/review UUID、事件绑定、raw 引用/hash 等；原始 bytes 仍分别保留。
不能宣称两个独立 Run 的所有 raw/event bytes 相同：其随机 result/call UUID、时间与运行路径不同，
也会传播进 request fingerprint/raw hash。本比较不证明真实 API 兼容性或科学有效性。
两次各有 53 个 call / 53 条模拟 cost entry，模拟账务总额均为 0.002196 USD；不是实际付费。

## 兼容性与发布

- 不修改事件 schema、SQL schema、迁移、prompts、G3 profile、P1、pricing、tokenizer 版本或算法。
- 不修改 Supervisor/Worker/CoreRunner、TrueSkill、UCB、Evolution、准入和原生 Final Selection。
- **旧 Run 继续使用原 v0.1.0 环境。**新 package code identity 必然不同；authorize/start/resume/export
  不允许绕过它。status 可作只读查看，不等于授权恢复或新版导出。
- 原 SHA256SUMS、source-files、provenance、deployment-changes.diff 和 dist/0.1.0 原封不动。
  新增 `reliability-overlay-v0.1.1.json` 单独记录两个观察模块的基准/补丁 hash 与新增 snapshot helper；
  测试要求原有 51 个 skill 资源和其余基准文件仍精确匹配，不静默改写旧哈希。
- 新构建版本 0.1.1，必须输出到独立目录；未覆盖旧构建，未发布 tag。
- strict verifier 针对隔离发行目录；它有意把 `.git`、缓存也当作额外文件。
  原默认 v0.1.0 清单在补丁源码目录报 MISMATCH 是预期，不能宣称旧清单验证新源码通过。

## 剩余风险与后续

- 写入频繁时导出可能 busy；应在稳定边界稍后重试。没有阻塞科学写入的长写锁或新事件系统。
- 本次提供固定数据视图，不提供五个导出文件的跨文件系统事务发布；保留逐文件不可覆盖规则。
- 旧 `SqliteRunReadModel` 是 legacy 接口；直接绕过 Cockpit 调用它仍不支持原生 G3 rating。
- tokenizer 安装面向 macOS/Linux，flock 不支持 Windows；强制 kill 可能留下无害的私有临时文件，
  但不会留下半写入的最终 tokenizer。未声称抵御整机断电后的全部文件系统故障。
- LICENSE 缺失，需要维护者决定授权范围；未添加或推定许可证。
- 大模块拆分建议仅为后续：orchestrator 的任务策略/结果应用/只读投影分离；SQLite 的查询、
  原子事务命令、预算/fencing 校验分离。应先稳定其接口与 replay fixtures，本次不重构这两个模块。
- 未测真实 provider、PubMed、Linux 实机或付费服务；未读取 HOLDOUT、未运行 Pilot/M2。

最终测试数量及规范化比较 hash 记录在同目录 `HARDENING_VERIFICATION.json`。
