# W1-L2：背景阅读、seed 与 readiness

本轮实现P03–P07的最小可执行切片。原W1 v0.4保持Proposed，M00 Accepted与W0-T4用户决定不改。
**真实适配器代码已实现，但没有执行真实模型调用；不宣称完整W1-L2已通过真实阅读验收。**

| 维度 | 本轮实际状态 |
|---|---|
| 后端 | 材料视图、P03计划、P04阅读、P05综合、分开P06定向/开放调用、P07逐seed准备检查已实现 |
| M12/M15 | 显式单步任务、已保存Goal pass门、结果幂等、成功回放、不确定发送恢复；无通用图流程/独立服务 |
| 页面 | 原文/解读分区、配置/用量、状态/负结果/外推限制、中性背景/seed/readiness与待补项已接入 |
| 替身验证 | 离线夹具和实际本地浏览器验证通过；不是实际模型阅读能力 |
| 真实供应商调用 | 未执行，无付费调用；只测试模拟HTTP/配置/原始响应与用量解析 |
| 模型阅读表现/科学有效性 | 均未审阅/未验证，science_validated=false；非盲测或独立发现 |

## 开发页面与操作

```sh
cd /private/tmp/co-scientist-w1-l2
PYTHONPATH=src python -m co_scientist_next.workspace \
  --db runs/w1-l2-live.sqlite --port 8786 \
  --development-test --development-reading --public-literature
```

交付时已运行：`http://127.0.0.1:8786/#run=9b5abf8a5ccd496d8c45ff9a6666b20e`。
它是对W1-L1实际公共获取数据库做一致、只读来源备份后的独立开发数据库；没有改写原L1数据库。
已有ALS Goal/测试Ethics与真实来源字节保留，P03–P07结果全部是明确标识的确定性替身。
新建数据库没有内置科学结果；可保存简报→显式开发Goal筛查→人工检索获取→选视图开始准备。
不需要真实模型密钥，无新生产依赖，兼容现有Python3.11/3.12或conda，不强制.venv。

1. 选择宽背景或一个seed，选择本Run已取得的摘要/全文。明确字符范围和裁剪理由，保存不可变视图。
2. P04只读取该视图。展开固定原文与模型解读分别查看，未选片段/图像/补充不视为读过。
3. P05综合当前范围的实际阅读记录与已执行查询。宽范围产生中性OrientationPacket，seed范围只产生该seed的资料包。
4. P06定向与P06开放分别执行；数量是本次配置，默认1，非固定全局科学规则。seed是问题，不是候选答案。
5. P03可用于宽背景或一个seed；保存计划不会检索。只有点击某条计划的“显式执行”才通过已有LiteraturePort/M15发送。
6. seed可选已有宽材料或本seed获取的材料，再执行P04/P05补资料；不能自动读兄弟seed检索内容。
7. P07对单个seed和明确packet检查；retrieve_more给出缺失信息及其作用，一个seed未准备好不阻止其他ready seed。
8. ready停在等待生成能力，不生成候选。刷新只读；未完成任务仅提供显式执行/恢复，按钮执行期间防重复点击。

`--development-test`指Goal适配器，`--development-reading`指P03–P07；两者独立。
`--public-literature`只允许显式非付费公共检索；本轮浏览器验证未点击计划执行，没有新增公共请求。
有真实来源不等于已真实模型阅读，更不等于真实伦理审查、科学发现或支持了主张。

## 真实供应商边界与试跑

已实现独立同步OpenAI Chat Completions HTTP适配器：
[官方创建接口](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。
2026-11-03实际搜索并读取官方文档，核对messages、JSON模式、finish_reason、prompt_tokens/completion_tokens。
现有G3 `OpenAIResponsesProvider`依赖异步SDK、旧外部响应类型和pilot pricing，不适合作为本切片独立窄客户端直接复用；
本轮复用新系统TaskCalls和无重定向HTTP边界，不引入旧Orchestrator或SDK依赖。
只支持显式官方端点 `https://api.openai.com/v1/chat/completions`，不声称适配全部供应商/全部模型。

公开配置示例：[reading-model.explicit.json](examples/reading-model.explicit.json)。`model`故意为空，必须填已获准的明确模型；
参数由调用方显式配置，本轮不默认选模型或换模型。不同模型参数支持有差异，实际4xx原样记为技术失败。
示例要求max_completion_tokens和JSON响应模式；可按模型文档显式配置temperature/reasoning_effort，无自动降级。

- 密钥通过单独指定的环境变量或仓库外私密JSON文件（api_key字段）读取，不探测现有.env/默认密钥。
- 不在页面填写/展示密钥，不把凭据放公开配置、材料、Prompt、M15请求或日志。HTTP Authorization只在发送时内存注入。
- 公开配置若含该密钥则拒绝；provider错误回显密钥时脱敏，并记录credential_redactions。原始字节只在无脱敏/截断时完整保留。
- 保存最终system/developer/user消息、实际材料/裁剪、Prompt版本、请求模型/参数/端点、实际HTTP body、原始响应和可得用量。
- 非stream、n=1、store=false；没有SDK、自动重试、重定向跟随或工具调用。未知token/费用为null，不估算成0。
- 可显式设置timeout_seconds（1..3600秒，当前已授权试跑使用600秒），该值为urllib socket操作超时，不承诺严格总墙钟截止时间。
  旧配置省略时仍使用90秒，且actual_request不补写默认字段：否则TaskCalls比较实际请求时会把历史成功记录误判为输入改变。
- 保存完整provider_usage（含reasoning_tokens、缓存细项等）及finish_reason；共享Usage仅保留通用计数，费用未知仍为null。
  max_completion_tokens包含推理和可见输出；length/空正文/不完整JSON均不保存为成功解读，不裁剪科学输入、不自动重发。
- HTTP响应先持久化后解析；finish_reason非stop、refusal、截断或无效JSON/引用都保存执行问题，不形成科研/伦理结论。
- 单响应技术上限4MB，超限明确标记；请求容量上限是显式字节限制，不冒充模型token窗口或用户总预算。

**以下命令没有运行；必须后续另获真实调用授权。** 先停掉占用该SQLite的页面进程（单运行者），
复制公开配置到临时文件、填入明确模型/参数，并通过独立环境或私密文件准备凭据。不要把密钥粘入页面、聊天、配置示例或Git。

```sh
# 仅帮助，无调用：
PYTHONPATH=src python -m co_scientist_next.background_trial --help
# 后续获授权后，显式只做一次已选视图的P04；不自动综合/生成：
PYTHONPATH=src python -m co_scientist_next.background_trial \
  --db runs/w1-l2-live.sqlite --run-id YOUR_RUN_ID --view-id YOUR_SAVED_VIEW_ID \
  --config /private/tmp/reading-model.json \
  --request-id YOUR_STABLE_SINGLE_TRIAL_ID \
  --credential-env CO_SCIENTIST_READING_KEY --execute-real-call
```

seed视图需同时传`--seed-id`。缺少执行标志在读取配置/凭据/数据库前拒绝。
成功回放/失败不会触发自动付费重试；trial输出本次Attempt身份、finish_reason、完整provider_usage及本次Attempt用量，不混入Run既有用量。
显式--request-id用于固定本次身份；省略时保留旧CLI的随机新身份行为，不能把再次运行新身份当回放。
已授权的一次真实P04及Codex初审见[审阅包](trials/w1-l2-first-real-p04-review/README.md)，不代表后续操作自动获授权。
若要后续在页面使用真实适配器：显式配置`--reading-model-config`和`--credential-env`（或credential-file），
并另传`--allow-real-model-calls`；只在用户点击操作时发送。缺配置/凭据或授权各自明确保存状态，没有开发替身回退。

## 输入隔离和实际材料

- 新增material_views与background_actions两小表；其余复用Run/Task/Attempt/Result，无独立服务或全科学Schema。
- view绑定Run、固定Goal、来源获取Task、版本/未知版本、访问层级、字符范围、原始文本SHA、未读范围和选择理由。
  模型转述/解释不覆盖原材料；卡片保留上下文、干预/对照、终点、观察、负结果/引用、作者解释、未证明事项与外推假设。
- 摘要视图不能升级全文，全文展平视图不能声称看到图像；source_locator指向原获取Attempt字段，视图再用字符范围定位。
  机器只能检查引用/范围/必需字段，不能证明转述科学准确或引文真的支持结论。
- P05默认读取本范围全部已保存解读；排除任何记录必须明确理由，当前切片不允许排除有已记录负结果的记录。
  综合保留全部选中卡片和原文视图、矛盾/竞争解释和限制；不作M05证据评级或M06 Dossier。
  看不到的反证仍可能存在；显式裁剪/缺失范围不能当作已审查全篇。
- 容量不足停止且不发模型请求，不静默截断、丢负结果或换小模型。可显式选择较小范围/分次P04，或调整配置；没有自动分块综合平台。
- P06_OPEN的实际USER恰四项：goal_context、neutral_overview、source_discovery_capabilities、generic_search_constraints。
  它是单独调用，不接收定向seed/优先机制/兄弟query/评审答案。P06_DIRECTED可读中性packet，各自产生问题身份。
- P03定向计划、执行查询、分页和fetch持续保存seed上下文；原宽查询保持独立。共享宽材料允许，兄弟定向材料/解读不能进入开放分支。
  输入通过后端白名单组装，review_only/expected/critical_failures不从案例评审或来源额外元数据进入模型。

## readiness与机械状态

P07检查可解释目标、可追溯起点、情境/负结果、备择、所需阅读和实际近邻检索尝试，按所请求具体程度给理由/引用。
ready只允许开始有依据的猜想：不要求未知因果桥已证实、完成判别预测或固定论文/全文配额；traceable anchor不是固定文献数量规则。
retrieve_more必须列精确缺失事实、下一查询/阅读及其作用；unable_to_prepare是当前准备问题，不是科学否定。
模型请求/解析/输入配置失败没有readiness决定。当前示例只验证这些输出契约和机械分支，不验证分类科学正确性。

无进展指纹同时覆盖原文视图、P04阅读（观察、情境、负结果、作者解释、限制/外推和待读请求）、
P05背景包（中性概览、竞争解释、研究问题、知识关系及其依据、限制/选择与裁剪）、实际查询覆盖和请求具体程度。
同一原文经重新阅读新增实质信息并更新包后可再次P07；不强制必须取得另一篇文献。
临时view/finding/reading/query引用映射到内容后去重，来源身份/版本和访问范围保留。
仅换packet/记录ID、时间戳、顺序或重复保存相同内容仍为no_progress，不调用模型、不形成科学否定。
比较历史P07时按新规则重算其已保存输入，不依赖旧版source-only指纹，也不修改历史事实；新结果标记p07-preparation-content-v2。
此检查是结构化内容比较，不是科学价值或自然语言语义等价判定；同义改写仍可能被视为变化。
没有自动无限循环；补充检索、阅读、综合和再次检查均需显式操作。
每个seed的最近完成readiness绑定自己的固定packet。Run状态表示最近操作的机械状态，不能把一个seed ready当作全局科学完成。
失败/无进展不会覆盖已有完成决定，页面保留全部历史。

结果应用幂等，成功调用本地回放。未知发送与响应保存失败留下的in_flight均阻断新模型任务，须显式恢复/核实/授权；不承诺外部exactly-once。
已确认失败可以另起显式动作，保留历史；真实模型配置变化不能静默恢复旧任务。单进程loopback、单数据库运行者，无远程认证。

## 实际验证和证据

[浏览器报告](verification/w1-l2/browser.json)、[完整开发执行/最终消息/原始响应gzip](verification/w1-l2/development-execution.json.gz)、
[页面](verification/w1-l2/workspace.png)、[已保存解读](verification/w1-l2/saved-reading.png)、
[seed](verification/w1-l2/seeds.png)、[刷新](verification/w1-l2/after-refresh.png)、[移动](verification/w1-l2/mobile-seeds.png)。
报告来自真实HTTP页面和SQLite，不是静态HTML内置结果。14个准备动作、13个开发替身Attempt、3条保存解读；
一个定向seed需补资料，开放seed可ready；相同检查不重发。刷新POST新增0，原L1材料与固定Brief均不变，无JS错误。
P03计划未在该浏览器流程执行；LiteraturePort接入/seed意图继承/分页/fetch用明确响应夹具离线验证，本轮无新增公共检索。
早期浏览器脚本两处等待/隐藏控件选择问题已修正，诊断数据库保留在runs下；未放松CSP。

```sh
PYTHONPATH=src python -m pytest -q -s tests/next
python -m ruff check src/co_scientist_next tests/next scripts/w1_l2_browser.py
python -m ruff format --check src/co_scientist_next tests/next scripts/w1_l2_browser.py
node --check src/co_scientist_next/frontend/app.js
node --check src/co_scientist_next/frontend/background.js
python -m build --wheel --no-isolation
# 明确工程验收；需要Playwright/Chromium，既有已获取材料和development-reading服务
python scripts/w1_l2_browser.py --url http://127.0.0.1:8786 --run-id YOUR_RUN_ID --evidence /tmp/w1-l2-browser
```

真实供应商网络/计费/模型语义表现、专家科学审阅、开放/定向质量比较、科学有效性、P08及后续链均未验证。
本轮不合并；没有新增需要总控改变M00规则的跨模块冲突。
