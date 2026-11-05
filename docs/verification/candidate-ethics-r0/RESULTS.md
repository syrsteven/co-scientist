# Candidate Ethics／R0 工程验证

PR14：固定head `cd815066dba167fc6c7faa016226719c7fe468be`，4项CI success、无审查评论/变更请求/冲突，普通Git合并固定提交。
GitHub核实已合并，merge/最新main/开发起点均为 `c90ce9365fa3c90f25e52bb77ee9fc551073a669`。
独立工作区 `/private/tmp/co-scientist-ethics-r0`，分支 `codex/w1-candidate-ethics-r0`。新PR不合并。

## 实际检查

最终命令（已有conda环境Python3.12.11、pytest8.4.2、Ruff0.16.6；不强制venv）：

```sh
env -u OPENAI_API_KEY PYTHONPATH=src /Users/lemintea/anaconda3/envs/coscientist/bin/python -m pytest -q tests/next
/Users/lemintea/anaconda3/envs/coscientist/bin/python -m ruff check src tests scripts \
  --per-file-ignores 'src/co_scientist/_migrations/env.py:I001' \
  --per-file-ignores 'src/co_scientist/_migrations/versions/*.py:I001' \
  --per-file-ignores 'src/co_scientist/adapters/persistence/migrations.py:I001'
node --check src/co_scientist_next/frontend/candidate-review.js
node --check src/co_scientist_next/frontend/generation.js
node --check src/co_scientist_next/frontend/app.js
env -u OPENAI_API_KEY python -m build --no-isolation --outdir /private/tmp/ethics-r0-final-artifacts
python -m pip install --no-deps --no-index --no-cache-dir \
  --target /private/tmp/ethics-r0-wheel-final-smoke \
  /private/tmp/ethics-r0-final-artifacts/co_scientist_replica-0.2.0.dev0-py3-none-any.whl
git diff --check
```

最终新系统 **355 passed、0 failed、0 skipped**（328已有＋27新增，含8项loopback HTTP及跨进程夹具）；[原始日志](tests-next.txt)。
Ruff全仓通过，只沿用CI原有6处历史import-order豁免，无新增豁免；3份JS语法、diff与所改Python格式通过。
构建wheel/sdist成功；[构建日志](build.txt)、[安装日志](wheel-install.txt)、[产物哈希/安装检查](build-summary.json)。
安装包包含固定P09/P10资源和candidate-review.js，并从仓库外导入/执行help验证，无网络或模型调用。

## 反例和恢复范围

- P09 pass/reject/incomplete、缺政策/decision_policy、无效/错候选输出、技术失败和uncertain：只有完成pass允许R0；错误不形成伦理决定。
- 同候选不同用途/政策/内容身份禁止复用，跨Run/另一候选的pass不能放行，Goal更改拒绝；成功重复提交/回放无新增Task/Attempt。
- R0可定位的核心事实反例能blocked，保持候选不变，不生成修复/R1。反例是新身份的故意错误开发候选，非真实DIRECT候选的科学裁定。
- 未知桥接、局部失真、弱证据、争议、工具未落实、新颖性未知不在阻断类别；有R1核查项的proceed样例保留未知。
- 事实阻断必须定位实际原文及访问层级；错引、模型记忆、助手转述不能冒充原文。R0输入不能仅传助手摘要或ID替代来源。
- Responses queued持久化ID、显式同ID查询completed、终态failed/incomplete/空正文/坏JSON、POST uncertain不重发、GET断连只留查询失败；完整usage沿用M15。
- 新进程GET同ID不POST、无适配器新进程回放成功P09/P10、只读刷新/重启不自动发送。
- 已完成P08迁移的两个旧uncertain仅沿同候选来源校验作用域保留；任何其他未解决调用继续阻断，不全局放行。
- Fixture导入拒绝既有数据库、候选内容逐对象保真；导出mode=ro、无凭据/无网络，P09/P10完整输入和容量校验。

## 真实浏览器与原库保护

IAB实际打开隔离开发库：选择复制的真实DIRECT候选→填开发政策→显式P09 pass→显式R0 proceed_to_R1。
页面明确显示DEVELOPMENT/确定性替身、政策版本、理由、未知和“下一步R1核查（尚未执行）”，技术记录折叠。
刷新后仍显示两项保存结果，整个fixture DB字节哈希保持一致，Attempt仍2个；[页面截图](page-refresh.png)、[文字](page-text.txt)、[核验](browser.json)。

原真实数据库本轮只计算文件哈希，不经Store打开、不写schema或替身结果，前后字节一致。
原工作区232项内容/暂存/状态指纹保持；历史试跑、设计原件和原候选文件在本分支无修改。

## 没有验证的能力

本轮真实模型请求 **0**，没有读取模型密钥。全部审查结果为明确开发替身，不能解释为该真实候选已通过真实Candidate Ethics或科学R0。
生产安全政策/decision_policy尚未配置；真实P09/P10表现、伦理准确性、科学事实判定准确性、实验可行性、新颖性和独立专家评审均**未验证**。
R1/M03、R2、科学准入、Ranking/Evolution均未实现或执行。旧G3全套及本机Python3.11全量**未运行**，不能以本轮夹具宣称完整科学链通过。
M00原“核心事实错误”责任边界按用户已接受修订采用，不改历史原件；其余未定生产语义仍显式配置，未发现必须改变M00科学流程的冲突。
science_validated=false。
