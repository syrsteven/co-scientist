# Workbench v0.4 可靠性修复（未发布开发分支）

审查基准：`a9a6934ce2c579d7302efe40a25c041c77a86d68`。
分支：`codex/workbench-v0.4-reliability`。只在独立源码树开发，不 push/merge/tag。
本报告不替换历史 `WORKBENCH_PROVENANCE.json`、发行 hash 或旧 Run 记录。

## Findings / RED → GREEN

| 严重性 | 文件 / 符号 | 根因与复现 | 修复 |
|---|---|---|---|
| P1 | `supervisor/orchestrator.py:562` `_baseline_search_stop` | 合成 ready=5/rated=4，G0/1/2/3 停止全部抛 R ledger 错误；实际 Mock 第五次 review 边界同样可到达 | COMPLETE 保持集合全等；PARTIAL 仅允许已排名集合为有效 ready 的子集，并核对 entry content hash |
| P1 | `runtime/core_runner.py:444` `_finish_continuous_partial` | 已有 final 且 STOPPING 时重复创建生命周期；基准注入测试 RED | 只在 RUNNING 恢复生命周期，STOPPING 仅处理已有 finalizer |
| P1 | `frontend/backend.js` reconnect/resume | 原按钮直接 POST resume，普通查看和恢复执行混淆 | 独立只读连接按钮与付费执行确认；后端 resume 强制显式 intent，start 不能代替中断恢复 |
| P1 | `release/service.py:291` `stop` | prepared 也创建 stop 文件 | 身份校验后拒绝 prepared，终态零操作，重复请求幂等 |
| P2 | `frontend/app.js:129` `nativeView` | tie-only 历史从终局快照得到 8 次比较；未来 rating/review/ranking 泄漏 | decisive 且 winner/双方身份有效才计数；只显示前缀已提交评分与审查/来源/配对；缺评分保持未知 |
| P2 | `driver.py:15` `run_driver`; `app.py:484` status | 原 main 返回非终态也写 finished；实际旧入口复现 finished/running 不一致 | 原生状态为唯一事实；脱敏 code/phase/last sequence，失锁与过期 PID 标需要检查，不自动恢复 |
| P2 | `app.py:519` monitor / stream / export; `monitor.py` | 每次事件变化生成完整 Trace；导出同步工作阻塞 ASGI 主循环（基准健康请求测试 RED） | 增量分页只读事件、阻塞工作进入线程池；保留原生一致性快照与不可覆盖导出 |
| P2 | `release/service.py:32` `save_new` | JSON 序列化中断留下最终路径半文件（RED） | 同目录临时写入、flush/fsync、独占 hard link 发布、目录 fsync；不覆盖已有文件 |

核心停止修复没有插入任何 InitialRating、MatchEvaluated 或伪造评分。PARTIAL 永远没有正式 Winner；
best-so-far 也只从真实有至少两次有效比较的既有 P 选取。非法 rated 成员、content hash 和配对错误仍 fail closed。

## 验证与命令

测试均 `env -i` 清空真实凭据，`PYTHONPATH` 显式指向本次源码；pytest 自动拒绝 socket。
后台 Mock 驱动也拒绝真实 socket。Chromium 只允许本地资源或由测试拦截的静态页面。
公共依赖安装不属于科研 HTTP；没有付费 API、PubMed、HOLDOUT/Pilot/M2。

使用的 Python：

- 3.12：`/Users/lemintea/Documents/co-scientist-workbench/.venv/bin/python`
- 3.11：`/private/tmp/co-scientist-web-reliability-20261023-py311/bin/python`
- CWD：`/private/tmp/co-scientist-web-reliability-20261023`
- 公共 tokenizer：`/Users/lemintea/Documents/co-scientist-workbench/tokenizer-assets`
- Chromium：`/private/tmp/co-scientist-workbench.SDbqyv/browsers`

每个解释器均运行：

```bash
# 环境同时设置 PYTHONDONTWRITEBYTECODE=1、PYTHONPATH=$PWD/src、
# CO_SCIENTIST_RESOURCE_DIR、CO_SCIENTIST_BROWSER_TESTS=1、PLAYWRIGHT_BROWSERS_PATH。
python -m pytest --import-mode=importlib -p no:cacheprovider -m 'not online' -q \
  --basetemp=/private/tmp/workbench-reliability-final312
# Python 3.11 对应 basetemp 为 ...-final311。
python -m ruff check src tests scripts \
  --per-file-ignores 'src/co_scientist/_migrations/env.py:I001' \
  --per-file-ignores 'src/co_scientist/_migrations/versions/*.py:I001' \
  --per-file-ignores 'src/co_scientist/adapters/persistence/migrations.py:I001'
python -m mypy --follow-imports=skip src/co_scientist_web src/co_scientist/release
PYTHONPYCACHEPREFIX=/private/tmp/workbench-reliability-compile312 python -m compileall -q src tests
node --check src/co_scientist_web/frontend/app.js
node --check src/co_scientist_web/frontend/backend.js
git diff --check
```

结果：Python 3.12 全量 **156 passed / 0 failed / 0 skipped**，452.69s；
Python 3.11 全量 **156 passed / 0 failed / 0 skipped**，413.62s。
两次均包含 Chromium 回放及全部既有离线回归。
之后补强“decisive 已出现但对应新评分投影尚未出现”的展示边界：RED 错误显示旧 μ，
最小只读 JS 修正后，两版各 3 个浏览器回放用例重新 GREEN；该最终展示修正后未第三次重跑完整套件。
原生科学/执行代码与上述全量及受控对照使用的字节一致。

补充验收（本地 HTTP/Mock）：

```bash
python tests/web_browser.py /Users/lemintea/Documents/co-scientist-workbench-reliability-evidence-20261023
python tests/web_reliability_browser.py /Users/lemintea/Documents/co-scientist-workbench-reliability-boundaries-20261023
python tests/compare_workbench_science.py /private/tmp/workbench-reliability-science-comparison baseline
python tests/compare_workbench_science.py /private/tmp/workbench-reliability-science-comparison patched
```

最后两条分别以基准/修复源码的 PYTHONPATH 启动；共享合成 manifest 和固定调用身份，未改任何历史 Run。

- 完整浏览器 G3 Run：`ideation-g3-20261023-a96d56958fd244eb9f1c395cff8e2d64`。
  COMPLETE/FINAL_WINNER，10 候选、396 events、13 decisive、26 posterior projections、6 reproduction。
  HTTP 服务退出后原独立驱动继续；终局五文件 ZIP 完整；浏览器外部请求=[]、JS errors=[]。
- 补充恢复 Run：`ideation-g3-20261023-42bfbe05dc744c13aed3d5a9535858f7`。
  只读重连/刷新没有执行 POST 或新增原生事件；取消确认没有执行；显式恢复后请求 stop，
  原生 completed_partial、winner=null，终态再恢复增加事件=0，ZIP 五文件。
- 5,000 事件只读分页完整且无重复；并发导出忙时不阻塞健康读取，也不创建科研状态。
- SIGKILL：发送进入 Mock transport、capture 前；domain raw 已保存、domain apply 前。
  两者显式 stop 后 PARTIAL；零重发、零伪造 cost entry，预留保留；原生 raw 恢复回归也保持通过。
- 实际第五个 review stop：ready=5、rated=4；PARTIAL、单一 final，重复运行不增加事件/HTTP。
- 输出 length/JSON/429/unknown、lease/fence/raw-first/replay 的既有离线用例全部保留。
- 独立 wheel 安装 Web API：5 passed / 1 deselected；CLI help 与已安装 wheel G3 Mock 完成，396 events、FINAL_WINNER。
- targeted mypy 14 modules PASS；显式 CoreRunner/Orchestrator 检查有 1 条基准相同的 return-value 诊断，未掩盖或修复。
  基准位置 `orchestrator.py:6333`，修复仅导致行号偏移。
- 原有 6 个 migration import-order 债务沿用 CI 明确排除，不称其已修复。远端 CI 未执行。

## 科研结果前后对照

受控完整 G3，基准与修复都选中 `hyp-root-slot-3`。
全部 396 个事件类型顺序、56 个关键科研事件投影（内容/hash、父代、配对、μ/σ、演化抽样、正式终局）与费用向量完全相等。
两份投影 SHA-256 均为 `5db91defe810e73c8afb94b39625a3ebe5a93acb27f8a3935e879ff8f2254f01`。
没有声称完整 raw/数据库逐字节相等：新代码身份、执行根、时间、lease/fence 与 artifact 引用是不同运行身份。
其它随机 Run 的 Winner 可不同；不能把不同 Run 的 seed 差异解释成科学算法变更。

## Compatibility / 重要限制

原生科研事件 schema、SQLite schema、TrueSkill、UCB、Evolution、Prompt/P1、冻结配置、预算、pricing、raw 和历史记录未改。
仅 Web SQLite 新增独立诊断表，原 jobs/objects 和原生表不迁移；原生事件仍是唯一权威。
原子发布依赖本地 POSIX 同文件系统 hard link/fsync，不声称覆盖所有网络磁盘/Windows 电源故障语义。

本分支原生代码身份：`sha256:a5c190a6565cb2d63d1f1a61cfd576a938f4532634ca0321c8cc920fdd5e5b71`。
旧 Run 不能直接在新代码恢复。实际旧 v0.4 Mock Run `_verify` 拒绝且四个历史控制/DB 文件哈希保持不变。
不提供改 plan/code_identity、复制目录替换、篡改旧数据库或补造终局的操作。
已受旧 bug 影响的历史 Run 若需处置，必须另行批准专门恢复方案；本次没有自动修好历史 Run。

历史 Trace 仍可只读导入，不等于将 CLI Run 纳入可写管理。未实现任意路径注册。
未模拟物理断电；用 SIGKILL、durable checkpoints、原子发布及恢复注入代替部分故障窗口。
未认证真实账户/限流/计费/生产网络或所有 OS 崩溃窗口；没有自动重发未知交付请求。
没有实现 Windows、多用户远程服务、M3 任意自定义组合、Human-in-the-loop。

历史 provenance/index 原样保留；新增 `release/resources/workbench-reliability-v1.json` 显式登记三处原生改动。
开发 wheel 仍沿用基础项目的 0.1.1 metadata，仅用于隔离测试，不是正式新版发行；发布需要维护者另行定版本。
不改原发行构建产物，不 push、merge、tag 或发布正式版本。Mock PASS 不代表真实 API 或科研有效性。
