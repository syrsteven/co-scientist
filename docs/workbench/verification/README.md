# 执行证据（离线工程验证）

环境：macOS，已有 conda `coscientist` Python 3.12；Node 用于 JS 语法检查；未创建 .venv。源码均在独立 worktree，未修改旧 G3 共享实现。

执行命令：

```sh
PYTHONPATH=src /Users/lemintea/anaconda3/envs/coscientist/bin/python -m pytest -q tests/next
/Users/lemintea/anaconda3/envs/coscientist/bin/python -m ruff check src/co_scientist_next tests/next
for f in src/co_scientist_next/frontend/*.js; do node --check "$f"; done
/Users/lemintea/anaconda3/envs/coscientist/bin/python -m build --wheel --no-isolation --outdir /private/tmp/co-scientist-v6-wheel
```

初始新增注释验证 3 passed；完整新系统 398 passed（原 393 + 3 注释 + 2 HTTP），失败0、跳过0。新增 HTTP 验证显式目标测试选择、三个角色同时配置/无凭据不回退、只读历史哈希不变、笔记导出、跨服务进程重启、长操作期间 GET 可读及并发写拒绝。原有测试继续覆盖失败/uncertain、远端 ID 恢复及成功不重发；未运行旧 G3 全套或在线供应商测试。

Ruff、所有 Next JS 语法检查和 wheel 构建通过；wheel 包含新前端和历史静态资源。原始附件及历史派生文件哈希另见 SOURCE/ADOPTION。

真实浏览器（IAB）使用单独 `fixture.sqlite`，全部模型为明确 development_fixture，文献为 OFFLINE 响应夹具，未配置模型密钥：

- 新问题“盐度变化如何影响植物根部离子运输与耐受性”→保存 Brief→显式选开发 Goal→pass→查询计划→逐条夹具搜索→取得摘要→选择原文范围→阅读→中性背景→定向/开放方向→定向补充阅读/背景→ready→两种模式各生成1个候选→独立 fixture Ethics pass→R0 proceed_to_R1。
- 夹具本身是固定发明内容，与植物问题不相关。人工意见明确记录该事实；此流程证明界面从任意 Project/Run 读取和调用，完全不证明检索相关性或科学能力。
- 原文按钮显示实际72字符摘要及访问限制；两个候选分别选择，不继承兄弟审查。个人意见分别绑定研究整体/候选，保存刷新可读。浏览器导出 JSON 实际下载并解析：2候选动作、2人工意见，包含原始记录且意见单列。
- 创建第二研究“光周期变化如何影响开花时间”，页面清空旧候选/Run，要求再次选择开发前置，不显示旧研究成果。
- V5历史十候选列表、排序、选两条并排比较实际点击可用；历史阶段选择 G0–G3 与回放控件保留。未穷举每个历史候选/回放组合。
- 桌面和390×844窄屏检查；document/body scrollWidth均390，无整页横向溢出；长标题正常换行。截图 `desktop-fixture.png`、`narrow-fixture.png` 为替身库，不是真实新生成。
- 实际服务8767仅查看空研究、设置和历史只读记录，再返回首页；`stage-settings.png`、`stage-home.png` 为该服务。凭据可用仅显示布尔，不返回值；没有点击真实检索或模型执行。

最终 stage.sqlite：projects/runs/attempts/annotations均0。fixture.sqlite：2 Project、1 Run、18 OFFLINE Attempts、2人工意见；不提交两库。原工作区232项文件内容、索引和status均不变；两个历史真实数据库SHA保持：

- p04-v2-prepared.sqlite: `a1414816be01c06535e9493f9eaa62d40ee892ad45cf024af61dc7776ab7a2b9`
- candidate-review.sqlite: `3da6812c150d38c712952ed1148c4a8f740b22a96886a69cc1bb296a5db70874`

本轮真实模型请求0，真实文献请求0；science_validated=false。页面主体没有 ALS_RECORD/内嵌科学结果。配置就绪不证明供应商当前联网质量；本轮没有网络探测/付费质量测试。
