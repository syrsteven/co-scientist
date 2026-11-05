# Candidate Ethics／R0非生产真实试跑准备：验证

基线/PR15 merge `d6e20cb1744ffad2e844d6ab5e23d9ad55c244e0`；分支`codex/candidate-review-real-preparation`。
执行环境：现有conda coscientist，Python3.12.11、pytest8.4.2、Ruff0.16.6；不强制venv。
本轮真实模型请求0、模型密钥读取0；science_validated=false。

## 最终验证

- `env -u OPENAI_API_KEY PYTHONPATH=src /Users/lemintea/anaconda3/envs/coscientist/bin/python -m pytest -q tests/next`：**373通过、0失败/跳过，49.23秒**。[完整输出](pytest-final.txt)。355既有+18新增，包含跨进程恢复、所有9项loopback HTTP测试。
- `python -m ruff check src tests scripts --per-file-ignores 'src/co_scientist/_migrations/env.py:I001' --per-file-ignores 'src/co_scientist/_migrations/versions/*.py:I001' --per-file-ignores 'src/co_scientist/adapters/persistence/migrations.py:I001'`：通过，沿用CI旧迁移文件豁免。
- `python -m ruff format --check src/co_scientist_next/candidate_review.py src/co_scientist_next/review_trial.py src/co_scientist_next/workspace.py tests/next/test_review_trial.py`：4文件通过。
- `node --check src/co_scientist_next/frontend/candidate-review.js`及`app.js`、`git diff --check`：通过。
- `python -m build --no-isolation --outdir /private/tmp/review-trial-final-artifacts`：wheel/sdist成功；仓库外`pip install --no-deps --no-index --target /private/tmp/review-trial-installed <wheel>`后`PYTHONPATH=/private/tmp/review-trial-installed python -m co_scientist_next.review_trial --help`成功。[构建产物哈希](build.json)。
- 实际`review_trial inspect`核对冻结包哈希及指定试跑库，审查action为0；实际`assemble-p10`因缺真实P09 pass预期退出2、没有生成输出目录。
- 逐文件核对准备包SHA256；原真实库SHA256仍为`a1414816be01c06535e9493f9eaa62d40ee892ad45cf024af61dc7776ab7a2b9`；原工作区232路径的内容、index及status指纹不变。

## 回归范围与开发过程

新增18项（含参数化）覆盖：非生产政策/真实执行标识分离；pass/reject/incomplete与真实pass来源门；fixture或仅篡改标签不能放行；候选/Goal/用途/模型/政策/Prompt/request-id绑定；P10真实结果条件组装；无授权不读取凭据；uncertain无ID停止、不重发；跨进程同ID查询；页面状态持久化；第二数据库拒绝及写连接前只读预检。

较早版本17项新增时全量372通过；最后补充“误指向原库时写连接前拒绝”测试后总数373，未删减测试。
最终重跑第一次在沙箱内364通过、9失败，全部为HTTPServer绑定127.0.0.1遭PermissionError；申请沙箱外本机回环测试后最终373全部通过，未关闭测试的真实网络禁令、未修改断言规避。
开发时也曾因在pytest父进程直连触发既有socket禁令，修为项目既有的子进程loopback验证方式。没有把这些环境失败称为模型调用失败。

## 页面证据

实际浏览器打开隔离试跑库，选择原Run并刷新；展示非生产政策、真实模型适配器未配置凭据/未授权、已保存审查0、准备身份及P10前提。
[截图](page-mode.png) · [可见文本](page-text.txt) · [刷新前后持久化对照](browser.json)。
刷新前后试跑库SHA256相同、没有新增Task/Attempt、模型POST/供应商GET均0；原真实库不变。
截图检查后仅修正全局Goal测试提示及旧页脚文本，候选审查面板不变；这些最后文本通过JS检查，未再进行整页截图。
页面仅必要状态展示，未做整体改版。CLI真实profile HTTP状态还由最终回归覆盖。

## 边界

政策/拟议用途/完整P09/尚不可执行P10模板及后续显式命令见[准备包](../../preparations/candidate-review-real-trial/README.md)。
测试中的Responses为明确离线Wire，不计真实模型表现；没有fixture结果写入原真实库或准备库。
没有运行真实P09/P10、伦理分类准确性/政策成熟度/独立专家复核、R1、重生成、检索、旧G3全套回归或本机Python3.11全量；这些均未运行，不能用工程通过替代科学验证。
候选及原始材料/Prompt原样保留，历史措辞失真初审不进入模型输入。
