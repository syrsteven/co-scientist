# W0-T4 可操作 Goal 工作区

本轮已实现最小页面、后端保存与条件推进；实际科研模型适配器尚未接入。
代码位于 `co_scientist_next`，不调用旧 G3 Orchestrator，也不解析旧回放格式。

## 启动

在本PR checkout，使用现有 Python3.11/3.12 或 conda环境，无新生产依赖：

```sh
PYTHONPATH=src python -m co_scientist_next.workspace --db runs/goal-workspace.sqlite --port 8784 --development-test
```

打开打印出的 `http://127.0.0.1:8784/`。当前交付时同端口已运行，数据库为
`/private/tmp/co-scientist-w0-t4/runs/w0-t4-live.sqlite`，内有实际通过页面创建、明确标记为工程验收的记录。
如端口占用，可改用另一个端口；单个数据库只允许一个运行者。

**必须显式传 `--development-test` 才启用确定性测试适配器。** 不带参数时可以保存/查看简报，
执行只会记录 adapter_not_configured；不会自动连接任何真实模型或加载示例政策。
不需要API密钥，没有付费调用。政策ID、版本、文本由用户显式填写；“填入开发示例政策”也必须主动点击。
示例政策不可在非开发模式使用，不能被视为生产批准政策、伦理委员会批准或临床/实验执行许可。

操作顺序：

1. 新建研究并输入原始问题、硬约束、偏好、背景、用途和材料引用，保存简报版本。
2. 显式填入政策，创建固定Run。创建并不执行；未保存的草稿不能直接创建新Run。
3. 点击“执行当前切片”才调用开发测试适配器并处理Goal与筛查；可以选择清楚标识的固定测试情景。
4. 右侧查看固定简报、Goal条件/出处、澄清项、政策快照和筛查/执行结果。
5. 左侧编辑保存产生新BriefRevision，已有Run继续引用旧版。刷新从后端读取，不执行或重发。
6. 重启后仍可查看旧事实。仅中断运行提供显式恢复动作；不确定发送保持阻断，需核实并通过后端API明确授权重试，页面没有隐含自动重发。

页面借鉴V5的浅色侧栏、青绿色操作和草稿/研究详情布局；没有导入V5内置病例、候选、时间线、排名或假进度。
没有未接入功能的可点击入口。后台仅绑定127.0.0.1，检查Host、同源写入和JSON；不提供多用户/远程部署认证。

## 后端事实与M12

- Brief原始question保持原字串；显式hard_constraints/preferences分别保存，background和intended_use独立。
- `GoalSlice.prepare` 通过可注入调用边界取得Goal输出，验证原问题、来源片段、显式条件完整性、背景/材料引用和关键澄清形状。
  原问题内的条件始终保留；解释与未指定项单列，不把新模型/分子当用户条件。
  第一切片保守要求prepared_question不改写原问题，系统解释不能引入没有输入依据的新内容。
- 每个来源定位指向最终发送的USER字段，如 `explicit_constraints[0]`，其内容来自固定BriefRevision。
  GoalContext在结果应用事务中保存，身份为 `goal-<prepare task id>`，Run稳定绑定它；待澄清Goal也可固定读取。
- M02读取显式版本政策。完成输出必须为pass/reject、非空理由和准确政策引用；缺风险信息是completed=false且无decision。
  缺政策或政策要求的用途缺失不发出screen调用。语法/形状无效保存parse_error及原始响应，不创建后继科学任务。
- M12只对这两个命名操作增加必要条件分支；只消费模块返回状态，不自行判断伦理或科学。
  pass停在awaiting_background；reject和各准备/失败状态分别保存，不跳过背景、不生成候选。
- Store新增两个小表goal_contexts/goal_run_config；配置、初始任务、结果、Goal和后继/停止状态均在各自事务内保存。
  重复应用相同结果不新增Goal/任务，不同结果冲突拒绝；其余新系统序列行为保持回归。
  Task的succeeded表示该模块结果处理已保存，不表示其伦理判定pass或科学验证完成，必须同时读取Run执行状态/结果。

## M15与真实适配边界

`GoalSlice(store, adapter, development_test=...)` 接受具备 `target` 和 `__call__(request)->CallResponse` 的窄适配器。
真实供应商/SDK、凭据、请求超时与底层重试映射尚未连接；页面无法配置它们。
适配器必须返回 `CallResponse({"raw_response": 原始响应文本}, usage)`，不得隐藏外部重试。

每次请求通过既有TaskCalls保存最终system/developer/user消息、Prompt版本、政策引用、开发模式和实际目标。
筛查USER包含完整政策ID/版本/文本与Goal，未用政策模板名替代实际政策内容。
原始响应先保存后解析；解析错误以单独fact保存。未知token/费用为null，读取成功回放不新增Attempt/用量。
发送后未收到响应保持uncertain；进程中断期间in_flight须经显式恢复转成不确定状态，不能默认安全重发。

开发适配器只复制显式输入字段并返回预设情景，**不是科学语义抽取器或伦理分类器**。
缺少具体分子/模型不是必然关键歧义；关键澄清由模块明确声明并给出输入定位，工程检查只能验证形状/引用，
不能替代专家判断该歧义是否真的关键。自然语言条件分类、真实模型准确性与安全政策有效性均未验证。

## 检查与页面证据

```sh
PYTHONPATH=src python -m pytest -q -s tests/next
python -m ruff check src/co_scientist_next tests/next scripts/w0_t4_browser.py
python -m ruff format --check src/co_scientist_next tests/next scripts/w0_t4_browser.py
python -m build --wheel --no-isolation
# 可选浏览器验收：安装Playwright与Chromium后，针对运行中的开发页面执行
python scripts/w0_t4_browser.py --url http://127.0.0.1:8784 --evidence /tmp/w0-t4-browser-evidence
```

本地沙箱禁止绑定loopback时，HTTP/浏览器检查需要主机允许本地端口；不能把环境拒绝记为功能通过。
本轮测试工具另装在临时目录，不改生产依赖；浏览器脚本允许 `--executable` 指向现有Chromium。

实际浏览器操作报告：[w0-t4-browser.json](verification/w0-t4-browser.json)。

- [桌面Goal与pass边界](verification/w0-t4-workspace.png)
- [编辑草稿后仍读取旧Run](verification/w0-t4-fixed-run-after-edit.png)
- [移动布局](verification/w0-t4-mobile.png)

页面验收记录来自真实HTTP与SQLite，非V5脚本内置演示。科学有效性、伦理分类准确性及真实模型表现仍为未验证。
接受修订见 [W0_T4_DECISIONS.md](W0_T4_DECISIONS.md)。
