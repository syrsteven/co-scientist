# 检查记录

基线main9dfd07e8b690a907fce46479fec2f09a3686a572；实际执行代码32abb8f89236ca262a4576d0adea9b506691b1c5。现有conda coscientist：Python3.12.11、pytest8.4.2、Ruff0.16.6。

## 真实发送前已完成

- 新增11项离线测试：`env -u OPENAI_API_KEY PYTHONPATH=src python -m pytest -q tests/next/test_p09_recovery.py`：11通过。涵盖缺授权/错原Attempt、请求变化、重复授权与命令、同Task同key/previous_id、再次uncertain、提交中跨进程崩溃、保存ID后新进程只GET、保存完成响应后本地应用、其他未解决调用不放行、授权事务中断回滚。
- `env -u OPENAI_API_KEY PYTHONPATH=src python -m pytest -q tests/next`：**393通过、0失败/跳过，52.31秒**（382既有+11新增），含9项本机HTTP和跨进程恢复。[完整输出](pytest-final.txt)。获准沙箱外loopback，无修改全局禁止真实网络断言。
- 全仓Ruff：`python -m ruff check src tests scripts --per-file-ignores 'src/co_scientist/_migrations/env.py:I001' --per-file-ignores 'src/co_scientist/_migrations/versions/*.py:I001' --per-file-ignores 'src/co_scientist/adapters/persistence/migrations.py:I001'`通过，沿用CI旧迁移债务豁免。
- 修改Python格式、JS `node --check` candidate-review.js与generation.js、git diff --check通过。
- `python -m build --no-isolation --outdir /private/tmp/p09-recovery-build` wheel/sdist成功；仓库外`pip install --no-deps --no-index --target /private/tmp/p09-recovery-installed <wheel>`及安装后`review_trial --help`成功，[哈希](build.json)。
- 两项PR原固定head各4项CI成功；合并后main的3.11/3.12 CI也全部成功后才发请求。[证据](merged-baseline.json)。
- actual P09原请求规范SHA25690b0dcdf…b39f与重组完全相同；原Attempt无response、无remote ID；准备哈希/候选/Goal/政策/Prompt/配置匹配。

## 真实结果与离线后验

- 一次授权恢复P09POST+2GET；仅有效真实pass后，一次P10POST+2GET。查询间隔15.375/15.214秒，均在各自20分钟/60次内；终态停止，无第三次P09POST或R1。
- P09/P10均completed且模块契约有效；分别pass/proceed_to_R1。实际完整消息、原始响应、逐次usage、解析结果、授权/谱系与绑定均已导出，没有手工修补。
- 每个远端ID取最终累计provider usage一次；旧调用未知不改0；供应方未返回finish_reason，不补stop。
- 实际无凭据浏览器读取、刷新2次并重启；所有逻辑行与39条Attempt全行相同、无新供应商请求。SQLite文件hash变化如实记录，不声称重启前后字节相同。
- 原真实库SHA256保持a1414816be01c06535e9493f9eaa62d40ee892ad45cf024af61dc7776ab7a2b9；候选/原文/历史科学行不变，原P09Attempt仅允许增加retry_authorization，旧P08 uncertain不变。原工作区232项内容/index/status指纹通过。
- 审阅包SHA256、原始body_base64/hash、原Attempt前后字段、同请求谱系、真实P09→P10、参数/容量、去重usage与页面保护由verify_bundle.py离线核验；解压后的独立包同样验证。

开发过程：先写测试在入口缺失时7项预期失败；初次混合focused在沙箱内69通过/1个本机端口权限失败，后经获准全量393通过。期间补齐未用变量/显式subprocess check的Ruff问题后检查通过；一次只读脚本因未设置PYTHONPATH报ModuleNotFoundError，纠正现有环境后通过。没有绕过审批、忽略检查或将环境失败冒充模型结果。

未运行：本机Python3.11全量、旧G3本机全套、R1/R2/后续模块、检索、生成、实验、独立专家伦理/科学复核。科学有效性/伦理准确性/政策成熟度及单次输出稳定性未验证。science_validated=false。
