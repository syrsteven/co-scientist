# Co-Scientist — Ideation DEV Workbench

本地科研假设生成与演化工作台：从研究目标、PubMed 文献和来源审查出发，经过
Generation、Ethics、Reflection、Ranking/TrueSkill 与 Mutation/Crossover，完成 G0→G3。
可查看完整候选、评分、父代谱系和原生过程记录，并安全停止、恢复和导出。

这是性能增强的 **G3 DEV** 软件，不是论文完整 G10 复现，也不执行实验或撰写论文。
模型审查、排名或 Mock 成功都不代表科学结论成立。

## 安装与打开 Workbench

需要 **Python 3.11/3.12、macOS 或 Linux**。无需 Node、Codex 或 API Key 即可运行 Mock。

```bash
git clone https://github.com/syrsteven/co-scientist.git
cd co-scientist
```

先自行选择并激活 Python 环境。例如 Conda：

```bash
conda create -n co-scientist python=3.12 pip
conda activate co-scientist
```

或使用 venv：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

已激活兼容环境可跳过创建步骤。之后统一安装和启动：

```bash
sh scripts/setup.sh
co-scientist-web
```

浏览器打开 <http://127.0.0.1:8765>，进入“创建任务”，填写目标并选择默认 **Mock**，
预检后创建、确认模拟预算并启动。后台独立驱动会完成 G3；结果中心可查看候选与导出。
设置页无需填写真实密钥。Mock 请求被强制限制在本地合成 HTTP，不访问模型或 PubMed。

安装脚本不创建或激活任何环境，只使用当前 PATH 的 `python`，按唯一的 `constraints.lock`
安装 Web 运行依赖、检查依赖，并准备 SHA 校验的 tokenizer。
首次安装需要包索引及公开 tokenizer 下载；运行期间不自动下载。已有文件可用
`sh scripts/setup.sh --tokenizer-file /absolute/path/o200k_base.tiktoken`。
需要时可用 `PYTHON=/path/to/python` 显式选择解释器；请确保启动命令来自同一环境。
开发依赖使用 `sh scripts/setup.sh --dev`。

## 使用与开发

- [中文使用手册](docs/DEPLOYMENT_GUIDE_ZH.md)：Mock、设置、授权、监控、停止恢复、导出和故障处理。
- [配置与预算](docs/CONFIGURATION.md)：冻结 G3、角色模型、容量、费用和身份边界。
- [架构与开发](docs/ARCHITECTURE.md)：模块、测试、构建与维护。
- [Web 接口](docs/FRONTEND_INTEGRATION.md)：真实后端和前端接入边界。
- [冻结科学规范](docs/2608_IDEATION_CORE_SPEC_V1.md)：方法约束；DEV G3 不冒称完整复现。

CLI 为高级入口：`co-scientist ideation --help`。
Workbench 默认仅 Mock；LIVE 必须显式 `--allow-live`、配置凭据并逐 Run 授权。
真实运行前需自行核对模型权限和冻结价格是否仍适用，不会自动在线探测账户。
自定义模型/代数等可保存草稿，但未经完整验证的组合会拒绝启动。

仅支持本地单用户，监听 loopback；不要直接暴露公网。密钥不进入日志、Run 或导出。
本版为全新 DEV 基线，不提供旧 Release 数据迁移；新建 Run 仍要求冻结代码/资源身份不变。
历史构建和审查记录不放在当前源码目录；Git 历史保留，未重写。

项目尚未选定源码许可证；不能将公开仓库等同于已获开源再分发许可。
第三方 tokenizer 许可随资源提供，OpenAI BPE 仅在安装阶段从固定 URL 获取并校验。
