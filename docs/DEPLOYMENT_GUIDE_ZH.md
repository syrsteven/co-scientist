# 中文部署与使用手册

## 1. 系统是什么

系统接受 Research Goal，执行 4 个独立 root 的文献检索和假设生成，随后进行
Candidate Ethics、Reflection、配对 Ranking、TrueSkill，以及 3 次双槽位演化。
最终在 G3 评价完成后从累计合格池选择 posterior μ 最高的候选。
普通 proposal 最多 10 个；失败、重复和拒绝不会自动补齐。
G3 后不生成 G4。本版本不是 G10 论文完整复现，不自动开展实验或写论文。

Root Generation 使用 Sol / Responses / medium / Performance P1 / strict schema，
其他角色使用 DeepSeek Flash。独立运行不需要 Codex。

## 2. 安装前准备

需要 Python 3.11 或 3.12、可写磁盘、macOS 或 Linux 的 POSIX 文件锁。
建议至少准备数 GB 可用空间用于每次 Run 的原始请求、响应、SQLite 和导出。
本轮实测系统为 macOS + Python 3.12。不要使用 Python 3.13。
首次安装依赖需要连接包索引；离线机器可由管理员预先准备对应平台的 wheel。
源码目录、依赖锁、tokenizer 不依赖开发机器或 Codex 的路径。

在解压后的源码目录执行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-build-isolation --no-deps .
python -m pip check
co-scientist --help
co-scientist ideation --help
```

如果安装 wheel，将最后一个安装命令替换为：

```bash
python -m pip install --no-deps dist/co_scientist_replica-0.1.0-py3-none-any.whl
```

锁文件包含已验证的运行、测试和构建依赖。不要混用旧环境。

## 3. 安装离线 tokenizer

DeepSeek V41 tokenizer 随包提供，使用前校验 SHA。
OpenAI BPE 数据通过明确的安装命令获取：

```bash
export CO_SCIENTIST_RESOURCE_DIR="$PWD/tokenizer-assets"
co-scientist ideation resources
```

该命令仅访问资源清单中固定的 OpenAI 官方文件，不发出模型请求。
若管理员已经获取正确文件，可完全离线导入：

```bash
co-scientist ideation resources --from-file /path/to/o200k_base.tiktoken
```

SHA 不匹配会拒绝，运行期间不会静默联网下载。
不设置资源目录时默认使用用户缓存目录。之后启动和恢复使用相同资源目录。
Sol 的编码映射是显式校准估算，不声称官方提供精确 Sol tokenizer。

## 4. Research Goal

复制随包的真实 DEV 研究目标后编辑自己的科学问题：

```bash
cp examples/research-goal.yaml my-goal.yaml
co-scientist ideation validate --goal my-goal.yaml
```

该文件虽然使用 `.yaml` 扩展名，也允许 JSON 语法。
字段包括 `title`、`goal`、`required_causal_chain` 与 `required_outputs`。
用清晰的科学问题描述目标、需要解释的因果链和预期输出；不要写 API Key。
不要要求将尚未验证的假设当作事实，也不要把安全审批写成已获机构批准。

默认选择包内冻结 G3 profile。显式配置文件可通过 `--profile /path/to/profile.yaml` 提供；
只有符合 R2 科学参数、版本和资源/预算校验的配置才会通过。
修改 Goal 或 profile 不会修改已经创建的 Run；需要创建新 Run。

`validate` 是离线配置校验，不证明账户有权限、模型仍可用或价格仍适用。

## 5. 首次 Mock

无需任何 API Key：

```bash
co-scientist ideation mock --goal my-goal.yaml --data-dir ./mock-runs --long-context
```

Mock 使用真实 Supervisor/Worker/CoreRunner、原生 SQLite 和 provider parser，
但 HTTP 由合成 MockTransport 提供。它不会联系模型或 PubMed。
命令输出独立 `run_root`，可用下面的状态/导出命令查看。
Mock 的成功、候选和 token/费用都是测试记录，不是科研结论或真实账单。

## 6. 配置真实凭据

需要有目标模型权限的 OpenAI 和 DeepSeek 账户，以及 PubMed 联系邮箱。
建议在创建真实 Run 前执行 `umask 077`，限制本机研究资料和运行文件的访问权限。
只从环境变量读取凭据，不会从 `.env` 自动导入；`.env.example` 仅为字段模板。
避免把密钥写入 shell 历史。以下命令适用于 Bash；zsh 可用 `read -s` 或安全凭据管理工具。

```bash
read -r -s -p 'OpenAI API Key: ' OPENAI_API_KEY; printf '\n'
export OPENAI_API_KEY
read -r -s -p 'DeepSeek API Key: ' DEEPSEEK_API_KEY; printf '\n'
export DEEPSEEK_API_KEY
export CO_SCIENTIST_PUBMED_EMAIL='researcher@example.org'
```

把邮箱替换为真实联系方式。不要共享带凭据的环境、截图或 shell 日志。
本版没有运行时自动价格查询。真实授权前，人工核对账户模型权限、API 参数和价格；
如果现价高于冻结的保守计算范围，不要授权旧计划，应由维护者发布新版本配置。

## 7. 创建、授权、启动第一次真实 G3

```bash
co-scientist ideation create --goal my-goal.yaml --data-dir ./runs
```

创建只冻结配置、Goal、code/config hash 和计划，不调模型，不创建科研 PASS。
将输出中的 `run_root` 赋给本地变量，例如：

```bash
RUN='./runs/ideation-g3-YYYYMMDD-完整随机ID'
co-scientist ideation status "$RUN"
co-scientist ideation authorize "$RUN" --accept-usd 60 --confirm \
  --accept-unknown-delivery-risk --confirm-pricing-capability
co-scientist ideation start "$RUN"
```

`RUN` 必须替换为 `create` 输出的完整路径，不要直接使用占位符。
授权风险上限 $60，不代表立即花费 $60；冻结保守资源规划为 $54.1303296。
最多模型 143、初始 119、重试 24、Sol 24、Flash 135、PubMed 48、总 HTTP 191，
模型上限共享总额度，整个 Run watchdog 7200 秒。
纯 LLM unknown delivery 新 attempt 可能重复计费；必须显式接受该风险。
不能复用历史授权或给同一 Run 替换 profile/代码。该命令不会启动第二个 Run。

## 8. 监控运行与费用

另开终端、激活同一环境：

```bash
co-scientist ideation status "$RUN"
co-scientist ideation events "$RUN" --after 0
tail -f "$RUN/progress.jsonl"
```

`events --after N` 按原生 event sequence 读取增量。
`status` 包含 task 状态、费用估算、reservation 和最终选择投影。
估算费用不等于提供商账单；unknown usage/cost 仍保留 reservation，不能解释为零费用。
完整科学输入、请求和 raw 保存在独立 Run 目录，可能含敏感研究资料；分享前人工审查。

## 9. 安全停止与恢复

```bash
co-scientist ideation stop "$RUN"
```

停止标记是 durable 的。驱动进程在当前有界调用完成/失败后停止新增科研派发，
由原生状态关闭为 PARTIAL。不能取消已经发送的服务端请求或退款。
有 stop 标记而没有驱动进程时，执行 `resume` 可处理该停止标记。

```bash
co-scientist ideation resume "$RUN"
```

`resume` 复用原始数据库、冻结配置、attempt 和预算；不会重新读取可变 YAML。
仅异常中断、仍允许恢复的原 Run 在原 watchdog 内继续。终态 COMPLETE/PARTIAL 不重开任务，
再次调用不会派发新请求。不要删除 stop 标记、重置数据库或手改授权。
代码/资源 hash 不匹配时 fail closed；恢复期间不要升级软件或替换 tokenizer。
同一 Run 同时只能有一个驱动进程。SIGKILL 不能保证立即写终态，durable checkpoint
用于后续恢复；硬件故障后不要假设最后一次请求未发送。

## 10. 读取和导出

```bash
co-scientist ideation export "$RUN"
```

运行中导出保存为 `snapshots/events-N/`，终态输出位于 `exports/`。
冻结快照不会被覆盖。指定新的目录可另行复制只读导出：

```bash
co-scientist ideation export "$RUN" --output ./shared-export
```

五项输出：

| 文件 | 内容 |
| --- | --- |
| `run-timeline.json` | 原生事件、任务/请求/call/attempt、raw、ledger、usage 和成本 |
| `candidates.json` | 全部候选科学内容、代数、科学父代、Ethics/Reflection 与 rating |
| `ranking-history.json` | 配对、结果、有效性、TrueSkill 投影 |
| `evolution-tree.json` | UCB tournament、操作、双/单父代、mutation critiques 和子代 |
| `ideation-report.md` | 可读的演化与最终选择摘要 |

只在 COMPLETE 且终局 barrier 完成时报告正式 Final Winner；否则只有 best-so-far。
排名不是科学正确性证明，下一步仍需研究者评估机制、证据、预测和实验可行性。
五项导出包含 raw/artifact 引用；要保存全部响应原字节、数据库和恢复资料，
终态时还应备份完整 Run 目录，而不是只复制这五个文件。例如：

```bash
tar -czf ./run-backup.tar.gz "$RUN"
```

备份含研究资料和联系人信息，分享前检查权限与内容。恢复应保留原 Run 路径、
代码版本和配置身份；不要移动目录后手改 execution-root/fence。

## 11. 常见故障

- `resource ... missing/hash mismatch`：显式安装正确 tokenizer；不要关闭校验。
- 缺 API Key/邮箱：不会派发；补齐环境，邮箱配置错误需创建新 Run。
- 401/403/支付失败：检查账户权限，不自动切换模型。
- 429/临时 5xx：按冻结 bounded policy 最多 3 attempts，并受共享 retry cap 控制。
- length/incomplete/JSON/source coverage：失败 raw 永久保留，按版本化反馈与容量规则有限重试。
- unknown delivery：优先原响应恢复；纯 LLM 最多一次新 attempt，reservation 不能伪造释放。
- 上下文真实超限：记录明确容量失败，不静默丢弃科学输入。
- `another driver owns this Run`：不要启动第二个驱动；先确认原进程状态。
- `frozen ... identity mismatch`：不要手改 manifest；使用原版本恢复或新建 Run。
- 导出目录已有不同冻结内容：选择新输出目录；不要覆盖原快照。
- 没有两名合格候选/Ranking 不完整：可能 PARTIAL，不会补位凑满 10 候选。

本版无远程服务守护进程、网页、机构审批或人工审阅 UI。
本轮 Release 验证全部离线；新部署入口仍需单独、小额真实 smoke 验证。
