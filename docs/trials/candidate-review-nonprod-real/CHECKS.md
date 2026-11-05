# 本轮检查记录

基线：b677c7f94f588aa71c3f453a13620f4e6bb0ad6c（PR16 merge）；本轮仅交付文档/脱敏证据及离线核验脚本，不改应用代码。
现有conda coscientist：Python3.12.11 / pytest8.4.2 / Ruff0.16.6。

- `env -u OPENAI_API_KEY PYTHONPATH=src /Users/lemintea/anaconda3/envs/coscientist/bin/python -m pytest -q tests/next`：**373通过、0失败/跳过，49.88秒**，包含9项本机loopback HTTP及跨进程测试。获准沙箱外运行本机端口，保留既有禁止真实网络断言。隔离测试库，不使用实际试跑库；[输出](pytest-final.txt)。
- 全仓`python -m ruff check src tests scripts --per-file-ignores 'src/co_scientist/_migrations/env.py:I001' --per-file-ignores 'src/co_scientist/_migrations/versions/*.py:I001' --per-file-ignores 'src/co_scientist/adapters/persistence/migrations.py:I001'`通过；沿用CI旧迁移文件豁免。
- `python -m ruff check docs/trials/candidate-review-nonprod-real/verify_bundle.py`与format --check通过；JS `node --check` app.js及candidate-review.js通过；git diff --check通过。
- 实际inspect前后验证同一准备SHA；实际请求与已验收P09 messages/body完全一致，配置/容量/候选/Goal/原文哈希一致；[核验脚本](verify_bundle.py)检查本包SHA256及结果语义。
- 实际无凭据浏览器查看、刷新、服务重启：保持一个P09 uncertain Attempt、零远端ID/GET、零P10。原真实库字节不变，试跑旧历史行不变；原工作区232项内容/index/status指纹通过。

导出时第一次以“试跑库文件重启前后字节相同”为断言失败；核对发现33条Attempt全行相同，但文件哈希变化。已更正证据口径，按实际请求记录证明刷新/重启无新增供应商请求，不改应用、不掩盖文件差异。

未运行：本轮wheel/sdist构建（应用未改）、旧G3全套、本机Python3.11全量、真实P10及任何查询/恢复重试、R1及后续、独立专家复核。
唯一真实模型发送为P09一次POST尝试；因无ID uncertain按授权停止，其余已运行检查均离线/本机只读，不是新增付费调用。
科学/伦理正确性、真实P09输出表现、生产政策成熟度未验证；Codex初审仅说明证据可得性，不补造模型结论。science_validated=false。
