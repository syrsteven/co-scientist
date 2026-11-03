# P04 context-v2 验证记录（2026-11-04）

实际起点87668c8ee84a52aa3109830cd7dbef02d0a32f28；代码/数据commit776b202383ab47d112d5d4e95bc76c023a05014f。
后一个提交仅增加本验证目录与STATUS，src/tests/preparations内容不再改变。
本机Python3.11.4、pytest8.4.2，使用已有环境，无新增依赖。

实际最终命令：

```sh
cd /private/tmp/co-scientist-p04-v2
OPENAI_API_KEY= DEEPSEEK_API_KEY= PYTHONPATH=src /Users/lemintea/Documents/co-scientist/.venv/bin/python -m pytest -q tests/next
python -m ruff check src/co_scientist_next tests/next docs/preparations/p04-context-v2/*.py
python -m ruff format --check src/co_scientist_next/background.py src/co_scientist_next/background_ops.py src/co_scientist_next/store.py tests/next/test_p04_prompt_version.py tests/next/test_p04_preparation.py docs/preparations/p04-context-v2/*.py
node --check src/co_scientist_next/frontend/background.js
python docs/preparations/p04-context-v2/verify_preparation.py
git diff --check
```

结果：203 passed、0 failed、0 skipped。[完整pytest输出](new-system-tests.txt)、[Ruff](ruff.txt)、[format](format.txt)、[准备包核对](preparation-check.txt)。
197原新系统用例+4项Prompt身份/迁移/恢复用例+2项独立准备包/不覆盖恢复用例=203。
旧v1消息可与已提交首次实际请求逐字重建；新v2任务固定版本；旧pending任务迁移仍用v1；
旧成功调用后模拟未应用结果的中断，在新进程恢复且NeverSend替身禁止任何重发，仍成功回放。
这些是工程断言，不是新Prompt真实模型效果或科学准确性验证。

[页面证据](page-evidence.json)：IAB打开新独立页面并刷新，确认v2版本、摘要及全文片段范围、未授权无凭据执行模式、开发伦理声明。
页面库始终runs1/tasks6/attempts7/views2/background_actions0，未点击执行；其中Goal2本地替身+文献5实际公共请求。
本次没有真实模型HTTP请求；页面阅读/真实模型Attempt数0。首次reload观察发生于异步渲染中，待可见版本文本加载后再次核对通过，无JS错误。

来源获取与后续校验分开：真实公共请求已记录到准备包M15事件，离线回归只读这些材料/使用夹具，不重复联网。
互补全文版本/访问限制以原JATS和provider metadata为准；未取图片或补充材料，不能把文字图注算看图。
旧Brief/Run/原始试跑目录没有改写，原用户232项改动及暂存指纹验证未变。

未运行：新Prompt付费/真实模型调用、P04科学效果审阅、独立专家验收、本机Python3.12、旧G3全套回归。
不声称完整科学流程或科学验收；science_validated=false。
