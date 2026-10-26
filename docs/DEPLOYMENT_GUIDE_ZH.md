# 中文安装与使用手册

## 1. 系统与安装

本软件是本地单用户 G3 DEV 工作台。4 个 root 各自检索、审查文献并生成假设，
随后 Ethics、Reflection、Ranking/TrueSkill 和 3 次双槽位演化；最多 10 个普通候选槽位。
失败不补位。终局评价完成后按累计合格池最高 posterior μ 选择 Winner，不是按 UCB。
技术成功不证明科学价值。当前不含 Experimentation、Paper Writing 或人工干预科研流程。

需要 Python 3.11/3.12、macOS/Linux、POSIX 文件锁、数 GB 可用空间。
不支持 Windows 或 Python 3.13。源码没有个人绝对路径依赖，不需要 Node 或 Codex。

```bash
git clone https://github.com/syrsteven/co-scientist.git
cd co-scientist
```

自行选择一种方式管理环境；已经激活 Python 3.11/3.12 环境时无需重新创建。

Conda 示例：

```bash
conda create -n co-scientist python=3.12 pip
conda activate co-scientist
```

venv 示例：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

激活后，两者使用完全相同的安装和启动命令：

```bash
python --version
sh scripts/setup.sh
co-scientist-web --help
co-scientist-web
```

脚本不创建、激活或切换环境，也不要求特定环境管理器。默认使用 PATH 中的 `python`，
每一步均由同一解释器执行。可用 `PYTHON=/absolute/path/to/python sh scripts/setup.sh`
明确选择解释器；之后启动时仍须激活对应环境，避免误用其他环境的命令。
环境缺 pip 或版本不符时会明确失败；无权限或 externally-managed 错误应由用户调整环境，
脚本不会调用 sudo、绕过系统保护或回退到用户级安装。

打开 <http://127.0.0.1:8765>。可用 `--port 8767 --data-dir /absolute/path/workbench-data`
设置端口和本地数据目录。默认 `.co-scientist-workbench`，不要在运行后移动目录。
主进程退出不等于独立科研驱动停止；请先在界面请求停止并确认状态。

### 日志与错误定位

默认 INFO 显示启动、写入 API、预检、授权/启动/停止/导出、Driver 和已提交科研事件。
高频 GET（状态、SSE、监控等）在 DEBUG 下记录；SSE 的 HTTP 行表示连接建立，
不是整个 Run 已完成。日志是观察信息，原生状态、事件、raw、账务仍是权威记录。

```bash
co-scientist-web --data-dir .co-scientist-workbench --log-level DEBUG
tail -f .co-scientist-workbench/logs/workbench.jsonl
```

Run 页面和服务器列表中的真实 Run ID 可用于以下命令；将 `RUN_ID` 替换为它：

```bash
tail -f .co-scientist-workbench/runs/RUN_ID/logs/driver.jsonl
grep -F 'err-错误编号' .co-scientist-workbench/logs/workbench.jsonl*
```

日志为逐行 JSON，包含时间（UTC）、级别、阶段、Run、事件序号、请求/错误编号。
异常保留类型、模块及文件/函数/行号，**不包含异常正文、源码行、局部变量**。
例如 `TOKENIZER_MISSING_RUN_EXPLICIT_RESOURCE_INSTALL` 表示需显式准备资源，
`TOKENIZER_SHA_MISMATCH` 表示资源完整性不符；不要跳过 SHA 检查。
前端预检失败会保留编号；后台错误在监控页显示编号。使用相同编号检索本地文件。

后台 Driver 独立写入自己的文件，即使 Web 服务退出仍继续保留日志；Web 在线时
专用日志管道把它实时转发到终端和 `workbench.jsonl`。重启 Web 不会回灌旧日志，
请查看 Run 文件。`/api/v1/runs/<run-id>/logs?limit=100` 提供同源认证的只读日志尾部
（最多 500 条、读取最多 256KB；不会启动或恢复任务）。

stdout/stderr 不再直接丢弃：持续排空并记录来源/字节数，启动前 Python 错误另保留
可解析的调用栈位置和异常类型；**任意原始文本不落盘、不转发**，以防第三方打印
密钥或模型响应。DEBUG 同样不会解锁这些内容；完整科学输出应从原生结果查看。
第三方 logging 的消息也被替换为来源/位置等元数据，而非依赖不可靠的正则掩码。
即使第三方传入 `extra.safe_record` 也不会被信任。Driver 保留真正的 stdout/stderr
对象及 `.fileno()`、`.buffer` 等接口；输出由 Driver 自身的管道读取，仅记录字节数，
包括底层 fd 和子进程输出，不会因 Web 退出丢失读取端或泄露正文。

文件权限为 0600，日志目录位于私有数据目录；每份日志 5MB，保留 4 个轮转备份。
日志属于运行数据，不提交 Git。SIGKILL/断电无法保证最后一条日志；退出码或重启后
丢失驱动锁会被记录为需审查，不会据此自动重发、恢复或伪造科研终态。

### 依赖和 tokenizer

唯一版本约束是根目录 `constraints.lock`。激活环境后，普通安装只需 `sh scripts/setup.sh`，
开发安装使用 `sh scripts/setup.sh --dev`。二者共用同一安装流程和约束文件。
脚本使用选定解释器的 `python -m pip` 安装，再执行 `pip check`。

已有本地 tokenizer 时：

```bash
sh scripts/setup.sh --tokenizer-file /absolute/path/o200k_base.tiktoken
```

首次安装访问 Python 包索引及固定公开 BPE 文件，不访问科研 API。
DeepSeek tokenizer 随包提供；OpenAI BPE 安装时固定 URL/SHA 校验，运行时离线加载。
管理员准备好数据后可用 `resources --from-file /absolute/path/o200k_base.tiktoken`；
对应安装脚本参数为 `--tokenizer-file`。完全离线安装还需预先准备兼容平台的依赖 wheel
及构建依赖，并用 pip 的 `--no-index --find-links` 配置；仅提供 tokenizer 不代表依赖已离线就绪。
默认资产目录为 `~/.cache/co-scientist/resources-v1`；如设置 `CO_SCIENTIST_RESOURCE_DIR`，
安装和后续启动须使用相同值。校验失败不会静默忽略或在 Run 中下载替代资源。

## 2. 第一次 Mock G3（推荐）

1. “创建任务”填写标题、研究问题、必要因果链和期望输出。无需真实密钥。
2. 选择默认 G3 和 Mock，点击“重新检查输入”。预检是离线配置校验。
3. 创建后，在独立确认窗口查看 Run ID、资源规划与风险上限，明确确认后启动。
4. “监控”显示已提交事件、当前代数、候选、TrueSkill 和驱动状态。
5. 结果中心查看候选全文、来源、Ethics、Reflection、Ranking 和演化树。
6. “导出五项 Native Trace”保存 ZIP。

Mock 使用真实 Supervisor/Worker/CoreRunner 和 SQLite，但 provider/PubMed 由 MockTransport
合成响应且禁止外部 socket；候选、文献、tokens 和费用记录都不是科研或账单证据。
也可运行高级 CLI 的长上下文检查：

```bash
co-scientist ideation validate --goal examples/research-goal.yaml
co-scientist ideation mock --goal examples/research-goal.yaml --data-dir ./mock-runs --long-context
```

## 3. Research Goal 与配置

在网页创建或编辑草稿；也可复制 `examples/research-goal.yaml` 后修改 `title`、`goal`、
`required_causal_chain`、`required_outputs`。不要把假设写成已验证事实或放入凭据。
网页的额外 constraints note 尚无原生映射，只能存草稿；必要科学限制请写进目标。

仅包内已验证的冻结 G3 配置可执行。模型、代数、root/offspring 等自定义字段可保存在草稿，
未验证组合会明确拒绝，不会静默回退。不要手改冻结 profile 绕过原生等值校验。
详见 [配置](CONFIGURATION.md)。

## 4. 真实运行与凭据（需独立审慎授权）

默认服务不允许 LIVE start。确需付费研究时，由操作员显式启动：

```bash
co-scientist-web --allow-live
```

在设置页输入 OpenAI/DeepSeek Key、PubMed 邮箱；密钥提交后清空输入，后端不回显，
只在内存中持有，通过私有 stdin 管道传给驱动，不写 argv、数据库、Run 或日志。
重启 Web 后需重新提供凭据。已启动 LIVE 驱动可能仍持有独立内存副本。
设置已配置不代表权限/余额/价格已在线确认。安装不会加载 `.env`；`.env.example` 只是字段模板。
CLI 可使用对应环境变量，避免在 shell 历史中明文写 Key。

必须先人工核对模型、API、价格与冻结配置仍适用，再创建 LIVE Run，逐 Run 确认费用和
unknown-delivery 可能重复计费的风险；单次全 Run 风险上限 $60，资源规划 $54.1303296。
这是历史冻结价格下的规划，不是实时报价。若不适用，停止，不能私改 pricing 或减少 reservation。
当前模型角色和限制见 [配置](CONFIGURATION.md)。不自动探测账户、回退模型或扩展预算。

## 5. 监控、停止与恢复

- 页面刷新、打开项目、“重新连接监控（只读）”和 SSE 重连不触发科研执行。
- “终止 Run”是 durable stop 请求，在有界调用完成后以 PARTIAL 结束，不是暂停或退款。
- prepared Run 不可停止/恢复；终态 COMPLETE/PARTIAL 不会重新打开任务。
- 中断的非终态显示 `interrupted_needs_review`；检查原生状态后，只有独立的“恢复原 Run 执行”
  按钮并确认可能产生费用后才继续。恢复仍校验 code identity、授权、预算、watchdog、锁和 fence。
- Web job 元数据只是观察，Native Run 状态才是科研真相；不要因 PID 不存在就删除 ledger 或重发请求。
- unknown delivery 保留原始证据和未知费用，按冻结 bounded policy 处理，不等于零成本。
- 此基线不提供旧 Release 数据迁移；新 Run 恢复时仍检查创建时的软件/资源身份，不改写 identity。

高级 CLI（将 `RUN` 替换为实际创建输出路径）：

```bash
co-scientist ideation status "$RUN"
co-scientist ideation events "$RUN" --after 0
co-scientist ideation stop "$RUN"
co-scientist ideation resume "$RUN"
co-scientist ideation export "$RUN"
```

CLI `resume` 是执行写操作，不是只读监控。不要同时启动多个驱动或移动 Run 根目录。

## 6. 结果、回放和备份

仅原生 COMPLETE、terminal barrier 与 FINAL_WINNER 同时成立才显示正式 Winner。
PARTIAL/INCOMPLETE 仅有 best-so-far。历史回放只显示相应序列前的事件，不用未来评分补齐缺失数据。
“导入历史 Trace”仅供只读查看，不等于接管历史 CLI Run 或迁移原生目录。

五项 Native 导出：

| 文件 | 内容 |
| --- | --- |
| run-timeline.json | 原生事件、请求、raw 引用、attempt、ledger 和费用 |
| candidates.json | 完整候选、代数、父代、Ethics、Reflection、rating |
| ranking-history.json | 配对、有效性和已提交 TrueSkill 投影 |
| evolution-tree.json | UCB、算子、父代、mutation critiques 与子代 |
| ideation-report.md | 可读运行与最终选择摘要 |

导出是固定快照，不覆盖既有输出；运行中快照在 `snapshots/events-N/`，终态在 `exports/`。
遇到 SNAPSHOT_BUSY 稍后重试，不会为导出停止科研。完整恢复资料还需备份原 Run 数据库、
raw/artifacts、manifest、授权及原安装环境，而不只是这五个文件。终态后再做整体备份。
备份/导出可能包含私人研究目标、联系人和模型响应，分享前审查；不要把它们提交 Git。

## 7. 常见问题与边界

- 缺 tokenizer/hash 不符：重新执行显式安装或提供管理员校验文件，不关闭校验。
- 页面连不上：确认终端服务仍运行、端口一致，只用 127.0.0.1，不直接部署公网。
- 页面会话失效：Web 重启后重新打开；凭据设置需重新输入，原驱动不会因此自动取消。
- 401/403/支付失败：检查权限，不自动更换模型；429/5xx 和格式错误仅按冻结有限重试政策处理。
- raw 未完成/unknown delivery：不要手动重发历史 call 或删除 reservation；先检查原生状态。
- `another driver owns this Run`：原驱动可能仍在运行，不要绕过 OS lock。
- `identity mismatch`/watchdog 已过：保留记录，使用正确版本或报告 PARTIAL，不修改历史。
- 没有可配对候选/比较未完成：不补槽，不伪造评分或 Winner。

本软件不是远程多用户服务；没有机构伦理审批、人类审阅控制或完整 G10 LIVE 认证。
Directive/Candidate Ethics 是模型辅助安全审查，不等于机构伦理批准。
