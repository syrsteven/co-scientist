# Clean Release 离线验证报告

结论：**CLEAN_RELEASE_READY（有界 G3 DEV 部署/离线验证）**。
不是完整 G10 复现认证，也不代表新部署入口已经通过真实 API 验证。

## 来源与提取

来源是成功 Continuous R2 的实际 dirty worktree，而非仅 HEAD。
选择性保留科研执行链和必需资源，未复制整个开发仓库。
**166 个原核心/资源文件逐字节不变**；两个原运行文件仅作资源路径与联系邮箱适配。
另调整项目入口/元数据/.gitignore，新增独立 operator 包、必要测试和中文文档。
profile 仅修改两个 tokenizer 路径，P1 和 Frozen Spec 原 SHA 保留。
详细 hash/source/exclusions 见根目录 provenance 与 SHA256SUMS。

排除历史数据库/raw/trace、开发审计、封存数据、原 venv、个人设置、凭据和缓存。
两份 Finder `.DS_Store` 在 packaging 审计中发现，已仅从提取件隔离，不分发。
DeepSeek tokenizer 许可已核对；OpenAI BPE 采用显式安装阶段获取而非重新分发。

## 新环境验证

| 项目 | 结果 |
| --- | --- |
| 独立 source venv，从锁定依赖安装源码 | PASS |
| 第二个独立 venv，非 editable wheel 安装 | PASS |
| pip check | 无依赖冲突 |
| CLI全部11个命令help与实际操作边界 | PASS |
| 缺授权/缺APIKey、授权跨Run或manifest篡改 | 派发前拒绝，零真实网络 |
| DeepSeek + tiktoken离线加载/hash | PASS |
| 51个skill/prompt资源、完整schema加载 | PASS |
| 包内原核心文件与成功源码hash比较 | PASS |
| 长上下文G0→G3、4 roots + 6 offspring、G3 barrier、原生Final Selection | PASS |
| Ranking request >296588 bytes，token规划与完整critique | PASS |
| JSON/length/429/unknown-delivery有限重试、restart、单次应用 | PASS |
| stop → native PARTIAL，无额外派发；终态resume/replay | PASS |
| 原raw-first/capture/accounting/recovery和Ranking/Evolution回归 | PASS |
| wheel从site-packages独立运行完整G3，五项导出及重复resume/export | PASS |
| 源码完整离线Release测试集 | **103 passed, 0 failed** |
| 最终wheel针对性部署测试 | **10 passed, 1 deselected（长测在源码环境已执行）** |
| Ruff（新部署层、测试、两处改动）、targeted mypy（部署5模块）、compile | PASS |

源码测试由92项未改变的核心回归与11项Release集成测试组成；不是宣称重新运行原仓库所有测试。
执行条件：`PYTHONDONTWRITEBYTECODE=1`、`--import-mode=importlib -p no:cacheprovider -m 'not online'`，
临时目录独立、pytest禁止真实socket。没有使用原 `.venv`。
targeted mypy 不代表整个原科研内核已无既有type diagnostics。

最终wheel CLI Mock：10候选、G3 COMPLETE / FINAL_WINNER，396事件、54合成HTTP ledger记录；
winner `hyp-offspring-g2-slot-0`，终局barrier完成，μ最高。所有这些是合成测试，不是科研结果。
五项导出与原始状态一致，终态重复resume/start不增加dispatch。

## 修复与限制

初版部署测试发现中间和最终导出共用目录；已仅调整薄封装为版本化中间快照，
保留原生冻结导出不可覆盖规则。wheel审计发现两份Finder元数据进入清单；已隔离并重测。
Python包索引下载遇sandbox DNS限制后，依授权完成安装；没有科学API调用。

本輪模型API=0，PubMed=0；没有读取HOLDOUT、运行Pilot/M2、commit/push或修改canonical。
原仓库HEAD/diff/inventory、Spec/Contract/P1和R2历史932文件树SHA保持不变。
历史R2树SHA：`e62729560d6a0a88d9c28d824239035cd5b1a0f56af321816fbb0b025e2a3e90`。

可以脱离Codex通过正式CLI安装、配置、授权、启动、查看、停止、恢复和导出G3。
但真实价格/模型权限需用户另行确认，新Release入口仍需独立小额真实验证；
不承诺任意Goal一定COMPLETE或科学假设必然正确。
macOS/Python3.12实测；Linux未实机验证；Windows不支持。
无已上线Web API、完整前端、机构伦理审批或多用户安全隔离。
旧Cockpit桥并非已接通本G3的生产API：额外只读核查显示其legacy snapshot reader
依赖`evaluation_rules_hash`，与native baseline rating事件不兼容。该原型不在正式CLI调用链中，
没有为此扩大修复；后续前端必须使用已测试的RunService/Native trace接口。
没有剩余的已知离线部署阻断。
