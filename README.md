# Co-Scientist Ideation Release 0.1.1 — Reliability Patch

此分支基于 `baa13351`，不是原 v0.1.0 构建产物。修复范围、旧 Run 的
code-identity 隔离及验证结果见 [可靠性补丁说明](docs/RELIABILITY_HARDENING_V0.1.1.md)。
原 `SHA256SUMS.json`、provenance 和 `dist/*0.1.0*` 保留为历史证据，
不用于宣称新源码与旧版本逐字节相同。新构建应使用独立输出目录。

独立部署的 **Continuous R2 G0→G3 DEV** 科研假设生成、评价与演化系统。
功能来源是已完成的真实 Run
`ideation-dev-g3-continuous-r2-20261014-836f244e5f7b4f0082c2381c85996d94`。
这是性能增强短周期 DEV 配置，不是原论文完整 G10 复现。

Python 3.11 / 3.12；本轮在 macOS、Python 3.12 独立虚拟环境验证。
Linux 使用相同本地 Python/SQLite 接口，但本轮没有 Linux 实机验证。Windows 暂不支持。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-build-isolation --no-deps .
co-scientist --help
co-scientist ideation resources
co-scientist ideation validate --goal examples/research-goal.yaml
co-scientist ideation mock --goal examples/research-goal.yaml --data-dir ./mock-runs --long-context
```

`resources` 是明确的安装阶段下载，不调用模型或 PubMed；完全离线安装可用
`resources --from-file /path/to/o200k_base.tiktoken`。模型执行不会下载 tokenizer。
Mock 数据全部为合成数据，不能作为科学证据。

真实运行必须另行提供 API 凭据、确认价格/权限、创建新 Run 并明确授权；安装和 Mock 不会自动启动真实调用。
完整操作见 [中文部署手册](docs/DEPLOYMENT_GUIDE_ZH.md)。
`python scripts/verify_release.py --manifest <新清单>` 仅校验清单内文件；
添加 `--strict` 才会拒绝所有清单外文件（包括 `.git` 和缓存）。
严格目录验证应针对独立发行目录，不应指向开发工作树。历史默认清单在本补丁树上
报告 MISMATCH 是预期行为，不得重写旧哈希以掩盖修改。

- [架构](docs/ARCHITECTURE.md)
- [配置、模型和预算](docs/CONFIGURATION.md)
- [前端接入边界](docs/FRONTEND_INTEGRATION.md)
- [源码与资源来源](docs/RELEASE_PROVENANCE.md)
- [离线验证报告](docs/RELEASE_VALIDATION.md)

尚未包含生产 Web UI、远程多用户鉴权或机构伦理审批。
系统的 Directive/Candidate Ethics 是模型辅助安全审查，不等于机构伦理批准。
保留科学输出验证；技术 PASS 或最终排名不能证明科学正确性。

项目源码未发现独立许可证声明，本交付不擅自赋予开源许可证。
第三方 tokenizer 的许可和分发策略见资源清单与来源文档。
