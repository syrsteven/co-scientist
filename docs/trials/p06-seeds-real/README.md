# P06 单次定向/开放 seed 结果与审阅包

Codex 初审，待独立人工复核。science_validated=false；Goal Ethics仍为开发测试结果，不是真实伦理审查。

交付分支 `codex/p06-seed-trial-review`；起点 `1a8d612b175ed35542e4aadaf17499d2e961914c`（P05结果提交），应用main基线 `378475b2e5a86d1c6504138bc3992dae2c977e81`。应用代码/既有Prompt不改，不合并main。

原Run `cea909fe8a004010b1896df1c1d98e02`；依据已保存真实P05 `p05-neutral-15cards-single`。DIRECTED完整包含其背景包，OPEN只读取约定四项，且执行后构建输入仍与DIRECTED执行前导出一致；完整卡、定向seed、评审均未进入OPEN。共享概述可能引导相似方向，输入隔离不等于科学独立。

## 实际执行

顺序 `p06-directed-one-single` → `p06-open-one-single`，各一新请求/一Attempt/一个seed，均HTTP200、finish_reason=stop、saved；无重试、切模型或新检索。既有Prompt `w1-l2-p03-p07-v1`。
模型gpt-6.1-sol/high/32768/JSON object，无temperature，600秒，凭据仅独立环境变量OPENAI_API_KEY；导出不含凭据。

| 操作 | 输入tokens | 输出tokens（含reasoning） | reasoning | 总tokens |
|---|---:|---:|---:|---:|
| DIRECTED | 16450 | 1447 | 812 | 17897 |
| OPEN | 1753 | 1447 | 956 | 3200 |
| 合计 | 18203 | 2894 | 1768 | 21097 |

费用未知/null；reasoning已经包含在输出，不重复计费。完整供应商usage（含cache_write_tokens等原样字段）见各 `*.usage.json` 及原始响应；不推算费用或缓存命中。

DIRECTED提出：在未预选核孔蛋白或模型时，若检测到修饰变化，如何用时序与选择性干预区分其参与mRNA输出障碍、损伤后反应或并行变化。
OPEN保留原Goal，以因果作用/下游/伴随区别为开放问题，较宽泛，并非机制答案。完整问题及Run/Goal/Task/seed绑定见各 `*.parsed-result.json`；未做P07，不能称ready。

## 容量与授权

原配置64000，DIRECTED envelope64013、HTTP正文63921；OPEN envelope7014、正文6922。原预检因此停止、无发送。用户明确批准后，仅将本次max_request_bytes提高至65536；模型参数/消息/HTTP正文均未变。原配置、预检、提案和批准后配置分别保留；preflight.json中的零请求是批准前阶段事实，不是最终调用计数。

G3参考：`src/co_scientist/runtime/context_planning.py:plan_context`将传输字节与token上下文分开，保留科学内容，超限明确失败。本次未移植旧Orchestrator/重试/动态输出调整或无损重组，不改变既有科学输入；字节检查不是精确token上下文证明。其他配置上限本次没有触发，不盲目放宽。未来较大包仍需显式容量检查与合理预算，而非保证任意输入可执行。

## 文件及离线验证

- `*.input.json` / `*.messages.json` / `*.planned-http.json`：执行前实际输入及请求，不含鉴权头。
- `*.attempts.json` / `*.action.json` / `*.original-response.json` / `*.usage.json` / `*.parsed-result.json`：完整调用事实与原始字节；原文/原输出不改。
- `source-p05.parsed-result.json`、`source-views.json`：实际使用背景及可定位原文；摘要与Results片段，不宣称读过其余全文/图像/补充。
- `directed-anchor-evidence.json`：三锚点的原卡、原文引句和字符定位；支持背景问题，不证明核孔蛋白磷酸化机制。
- `codex-review.md/json`：9项调用后初审。重点待人工确认：OPEN未就地限定“尚未建立”的知识范围，DIRECTED单句未逐字重复ALS，以及研究问题的价值/干预可行性。
- `runtime-audit.json`：P04/P05 action/task/attempt/result前后哈希一致，11Tasks/12Attempts/5背景动作，最后两项各一次。

运行（无网络、无模型调用）：

```sh
python docs/trials/p06-seeds-real/verify_preflight.py
python docs/trials/p06-seeds-real/verify_results.py
PYTHONPATH=src python -m pytest -q tests/next
python -m ruff check src/co_scientist_next tests/next docs/trials/p06-seeds-real
```

首次沙箱回归199通过、4项HTTP因socket权限失败；审批后同命令全量203通过、0失败、0跳过，日志见docs/verification/p06-seeds-real/next-regression.txt。未执行浏览器验证、旧G3回归、独立人工/专家审阅、科学有效性评测。

压缩包 `docs/review-bundles/p06-seeds-real.zip`，附SHA256；解压后仍可运行只读verify_results.py。原始DB仍为原Run的独立数据库，便携包不依赖本机DB。没有执行自动检索、seed补充、P07/P08/Candidate Ethics/R0，不标记完整科学链通过。
