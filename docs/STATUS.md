# 项目状态 — 原P09显式恢复与真实P10

## PR17/18合并后连续执行（2026-11-05）

PR17固定head `baa0240a34276123c9e823435674f94ba3716333` → merge `468386cdbbf9d25d201d726c1e3084514225def9`。
PR18固定head `3a324cea29d9114527e68d7cbe548063513662bb` → merge/本轮起点main `9dfd07e8b690a907fce46479fec2f09a3686a572`。
两项各4项CI成功后合并；仅STATUS冲突，保留两份交付事实，src/tests/scripts与PR18相同。main两项CI也成功后才执行付费恢复。
独立分支`codex/p09-explicit-recovery`，本轮交付PR不合并；实际执行代码`32abb8f89236ca262a4576d0adea9b506691b1c5`。

| 维度 | 本轮事实 |
|---|---|
| 恢复入口 | 限定原P09Task/Attempt，完整请求hash不变；M15显式重复执行/收费/store风险授权、同call_key追加previous_id。原Attempt保持uncertain，只增加retry_authorization；重复命令/崩溃/再次uncertain/已有ID均不再POST，不全局解除旧调用阻断 |
| 真实P09 | 新增1次恢复POST、2次同ID GET；completed/解析有效/pass。原Task 250e3e6dea7a430fb07e71080c20a345，新Attempt69fa1539d29047608a2eb8178126b5eb关联原da49fb…，原错误/未知usage不变 |
| 条件P10／M12 | 仅真实P09有效pass及来源核验后组装全部5份原文；1次POST、2次同ID GET，completed/proceed_to_R1，停awaiting_r1。未执行R1或科学准入，无候选修补 |
| 请求 | 固定Goal/候选/用途/政策/Prompt及gpt-6.1-sol/high/32768/JSON/无temperature/600秒/后台store=true/truncation=disabled不变；P09 31644字节，P10 59369字节，未裁剪 |
| 用量 | P09 input8611/output1541（reasoning511）/total10152；P10 input15668/output2018（reasoning776）/total17686。完整provider usage保存，每个ID最后累计值计一次，不累加GET；费用及历史unknown仍null。finish_reason未返回，不补stop |
| 页面 | 明确P08历史调用与当前P09/P10，展示真实结果、development政策、原uncertain及恢复谱系、等待R1。无凭据页面实际刷新2次/服务重启，所有逻辑行及39条Attempt相同，未新增供应商请求；不谎称SQLite文件字节不变 |
| 检查与保护 | 新增11项恢复测试，全量393通过、0失败/跳过；Ruff/JS/构建/仓库外安装及审阅包验证通过。原真实库字节、候选/来源/历史科学记录及232项工作区改动保持；试跑库只新增授权/恢复/P10事实 |
| 初审与科学 | Codex初审待独立人工复核；未把科学未知自动拒绝/阻断，但R0未逐项点名原候选ANXA11/SUN1措辞弱化及所有阴性覆盖，原问题保留。science_validated=false；真实执行不使非生产政策变生产，未验证科学准确性/稳定性 |

[恢复入口/命令](P09_EXPLICIT_RECOVERY.md) · [完整真实记录与审阅](trials/p09-recovery-real/README.md) · [ZIP](trials/p09-recovery-real-review.zip) · [SHA256](trials/p09-recovery-real-review.zip.sha256)。
不执行R1、检索、生成、候选修补或其他模块。无原响应证据时未推测ID或改判旧调用；本轮授权已使用，后续不自动重试。以下历史状态原样保留。

# 项目状态 — Responses正文结束时的socket生命周期修复

## TUN／代理对照与窄传输修复（2026-11-05）

起点main `b677c7f94f588aa71c3f453a13620f4e6bb0ad6c`；独立分支`codex/responses-socket-lifecycle`。不合并本轮PR，不重发P09/P08 uncertain，不执行任何科学模块。

| 维度 | 本轮事实 |
|---|---|
| 已复现缺陷 | 旧Responses read1循环在Content-Length正文恰好读完后，下一轮对已释放的连接socket(fd=-1)执行settimeout，触发EBADF并丢弃已读完整响应。系统默认、无应用代理、显式7897代理三条无凭据GET均复现；不是“必须export代理”能解决的问题 |
| 修复 | 保留活跃fd的逐读超时；fd已释放时让HTTPResponse返回EOF，不对失效fd设超时。总deadline/截断/大小限制/无重试不变；安全诊断允许列表增加EBADF，不记录原始异常或凭据 |
| 连通性 | 修复后共用生产读取函数的三条GET均收到完整401 JSON。禁用应用代理也通（约0.83秒）；无export时urllib仍发现macOS系统HTTP(S)代理7897，因此“未export”不等于“没有系统代理”。不推断或修改TUN规则 |
| 历史与科学 | 本轮付费模型POST0、模型密钥读取0；不访问或改写真实执行数据库。既有uncertain/未知费用保持，不因复现客户端缺陷推定历史供应商结果。science_validated=false |
| 检查 | 真实socketpair+HTTPResponse回归覆盖200/401及三种报文结束方式、截断/活跃错误/安全错误码。新系统382通过（373既有+9新增），Ruff/format及wheel/sdist构建/仓库外安装通过；不声称真实模型POST/生产科学恢复已验收 |

[复现、修复、无凭据测试命令与限制](verification/responses-socket-lifecycle/RESULTS.md)。用户要求的长期记忆只记录确认事实、正确诊断方式与禁止自动重试；历史科学输出/原工作区232项不变。下方历史状态原样保留。

# 项目状态 — Candidate Ethics／R0 非生产真实试跑

## PR16合并后授权执行（2026-11-05）

PR16固定head `77a0aca200cb640d29d7f044d6773076476581b6` 重核4项CI成功、clean无冲突/新增阻断后合并；实际merge及本轮起点 `b677c7f94f588aa71c3f453a13620f4e6bb0ad6c`。
独立分支 `codex/candidate-review-real-results`，交付PR保持未合并；无生产逻辑/Prompt/政策变更。

| 维度 | 本轮事实 |
|---|---|
| 输入 | 唯一既定隔离试跑库inspect通过；准备哈希1890c42d…951、完整31644字节请求与总控接受包一致。候选/Goal/5份原文、2026-11-05-v1非生产政策及配置原样；未重新prepare/覆盖/回滚/另库执行 |
| 真实P09 | 一次Responses POST尝试，Task 250e3e6dea7a430fb07e71080c20a345 / Attempt da49fb3eb36c4e8aadee6f34e0757d15。读取响应阶段传输错误，单调耗时2.649582998秒；未取得ID/完整响应，保存uncertain，Run/Task blocked，供应商执行/收费未知 |
| P10／M12 | 没有有效真实P09 completed/pass，因此P10未组装、未创建/发送。无GET查询，无重试/模型切换/政策修补；此技术阻断不是伦理拒绝或R0科学阻断 |
| 用量 | 完整本地可得usage的token/cost/tool_units均null，provider_usage与finish_reason未返回，不补0或stop；历史两个P08 uncertain及未知用量不变 |
| 页面 | 无凭据、无发送授权进程显示真实执行标识/非生产政策/无ID停止。实际刷新2次并重启后33条Attempt全行不变，无新增供应商请求；试跑库文件hash因启动过程有变化，如实记录，不声称重启前后字节相同 |
| 交付 | 脱敏实际请求、Attempt/错误/未知usage、前后inspect、候选及原文、政策绑定、初审未验证项、页面证据、离线核验脚本、审阅ZIP及SHA256已导出；无数据库或凭据提交 |
| 验证与保护 | 新系统373通过、0失败/跳过；Ruff/JS/diff与包核验见检查报告。原真实库字节哈希、原科学记录及原工作区232项内容/index/status保持。没有新科学输出可供实质初审 |
| 科学边界 | execution_mode=real_model、policy_mode=development；science_validated=false。无伦理决定、无R0结论、无科学准入；未执行R1、检索、重生成、候选修补或其他模块。真实P09/P10准确性和独立专家审阅均未验证 |

[结果/命令/完整证据](trials/candidate-review-nonprod-real/README.md) · [Codex初审，待独立人工复核](trials/candidate-review-nonprod-real/REVIEW.md) · [审阅ZIP](trials/candidate-review-nonprod-real-review.zip) · [ZIP SHA256](trials/candidate-review-nonprod-real-review.zip.sha256)。
原Accepted/Proposed状态及历史设计/科学输出均不改。本轮授权一次P09已使用；无ID uncertain后停止，任何未来恢复均需另行明确授权，不能用新Run/任务/数据库绕过。以下历史状态原样保留。

# 项目状态 — Candidate Ethics／R0 非生产真实试跑准备

## PR15合并后连续准备（2026-11-05）

PR15固定head `988aabd00743722ae9e622ffd7c519614dbbf15a` 经4项CI成功、无冲突及新增阻断后合并；实际merge及本轮起点 `d6e20cb1744ffad2e844d6ab5e23d9ad55c244e0`。独立分支 `codex/candidate-review-real-preparation`；本轮新PR保持未合并。

| 维度 | 本轮事实 |
|---|---|
| 政策 | 版本化development／非生产政策，限定非临床机制假说阅读、评议与方法开发；不授权患者、动物/人体或实际实验。显式pass→continue/reject→stop/incomplete→hold，仅适用于本次试验，无生产默认通过 |
| 后端／M12 | 政策成熟度与执行方式分别记录。隔离试跑固定P09/P10身份、完整输入及配置；只有真实Responses completed且有效pass、M15来源完整的P09才能组装P10，fixture或伪改标签不能替代 |
| 准备包 | 原真实库只读一致性快照到唯一指定隔离库；候选/Goal/5份原文及历史科学记录不改。完整未发送P09为31644字节；P10仅模板且真实pass字段null、不可执行。无P09/P10 Task/Attempt/结论 |
| 恢复与保护 | 后续命令另需显式POST/同ID查询授权；先只读验证数据库身份，再打开写连接；已有Attempt不重发、无ID uncertain停止。旧两次uncertain/未知用量不变，无全局放行 |
| 页面 | 仅必要状态调整：非生产政策与真实适配器未配置凭据/未授权分别展示，准备快照审查记录0、固定身份和P10前提清楚可见。浏览器刷新前后库哈希及记录不变 |
| 验证 | 见本轮验证报告：新系统回归、Ruff、JS、构建、跨进程恢复、实际只读准备包/来源一致性及浏览器证据；没有用替身结果冒充真实P09 pass |
| 真实／科学 | 真实模型请求0、模型密钥读取0；原真实库字节及原工作区232项改动不变。science_validated=false；真实P09/P10、政策成熟度、伦理准确性和独立科学审阅未验证；未执行R1、重新生成或新检索 |

[政策全文、拟议用途、完整P09、P10条件组装与后续命令](preparations/candidate-review-real-trial/README.md) · [本轮检查及页面证据](verification/candidate-review-real-preparation/RESULTS.md)。
原候选措辞失真及历史初审保留，不修补输出、不把初审放入模型请求。原Accepted/Proposed状态不变，无需变更M00科学规则。以下历史记录原样保留。

# 项目状态 — W1 Candidate Ethics／R0 最小纵向切片

## PR14合并后连续开发（2026-11-05）

PR14固定head `cd815066dba167fc6c7faa016226719c7fe468be` 重新核对4项CI成功/无冲突或新增阻断后合并。
实际merge/本轮最新main起点 `c90ce9365fa3c90f25e52bb77ee9fc551073a669`；独立分支 `codex/w1-candidate-ethics-r0`，新PR保持未合并。

| 维度 | 本轮实际状态 |
|---|---|
| 后端 | 独立P09/P10 Task及冻结输入/候选内容哈希/用途/政策/Prompt/配置。显式decision_policy承载Candidate Ethics非二态语义；开发pass/reject/incomplete为明确示例，无生产默认政策。缺配置、解析/技术失败不形成伦理/科学决定 |
| R0边界 | 同Run/Goal/候选/内容的有效Candidate Ethics pass才建立P10；实际来源文本和访问范围入模。核心事实阻断需定位候选、可靠原文及核心性，助手转述/记忆不作原文；未知/局部问题/争议交R1，不修补候选 |
| M12/M15 | 仅pass到awaiting_r0，其他按配置stop/hold；P10停awaiting_r1或candidate_r0_blocked，无R1。复用Attempt/Result/Responses持久ID、成功回放、显式同ID查询、uncertain不自动重发；仅验证完成生成的窄迁移来源作用域，旧两个uncertain不改判、不全局放行 |
| 页面 | 展示候选主张、假设/预测/实际原文入口；候选伦理政策/理由/风险、R0定位问题/未知/R1事项。显式执行/恢复/同ID查询，技术内容折叠，开发替身与生产未配置清楚可见。真实浏览器操作并刷新后2个fixture Attempts与DB哈希保持 |
| 输入交付 | 真实DIRECT候选内容原样复制到隔离开发夹具，源身份/来源保持，禁止覆盖已有DB。P09/P10完整未发送请求29504/53714字节，开发政策/替身pass清楚标识；生产政策及真实P09 pass缺失，不伪造可执行生产P10 |
| 验证 | 最终新系统355通过、0失败/跳过（328已有+27新增，含8项loopback HTTP与跨进程恢复）；Ruff全仓沿用CI既有豁免、3份JS、Python格式、wheel/sdist构建及仓库外安装导入、哈希/输入/刷新检查通过 |
| 真实与科学状态 | 本轮真实模型请求0、模型密钥读取0；原真实库仅文件哈希核对、字节不变，无替身写入；原工作区232项保持。science_validated=false；替身不是伦理分类或科学准确性验证。未执行R1及后续模块 |

[最小实施/政策采用/启动及API](W1_CANDIDATE_REVIEW.md) · [未发送请求与开发结果](preparations/candidate-ethics-r0-unsent/) · [测试/构建/页面证据](verification/candidate-ethics-r0/RESULTS.md)。
原P08作者措辞失真问题保留在原初审，不修补原输出，不进入被测审查输入。
未配置生产政策，未运行真实P09/P10/独立专家复核/旧G3全量/本机Python3.11全量，科学有效性未验证；没有需改变M00科学流程的跨模块冲突。原Accepted/Proposed状态不变。以下历史状态原文保留。

# 项目状态 — P08 DIRECT 首次 Responses 后台真实结果

## 同Run显式迁移与单次真实生成（2026-11-05）

基线main `9f7ca42f5aca6344df2467faa08a569b483d800e`；独立分支 `codex/p08-responses-real-single`，本轮PR保持未合并。
按本轮用户明确授权，在原真实库备份/只读重算预览后确认四项风险，唯一后继Task `175a05d2d2aa4830a6e1bd974907e0dd`，重复确认返回同一任务；另经专属入口记录单次付费授权。

| 维度 | 本轮事实 |
|---|---|
| 实际调用 | DIRECT：1次Responses POST、4次同ID GET；queued→in_progress→completed即停止，查询间隔≥15秒、20分钟/60次以内，无重发/切换/新增检索或其他科学模块 |
| 固定输入/配置 | 原Run/Goal/seed/P05包/P07 ready与w1-p08-single-v1原样；仅既定候选身份planned-p08-direct→planned-p08-direct-responses。实际HTTP请求145411字节≤262144，六字段USER、无审阅/兄弟输入；gpt-6.1-sol/high/32768/JSON，无temperature，background/store=true、truncation=disabled、socket/总期限各600秒 |
| 保存结果 | response resp_0880c479f87ca5bf006aebe66dbbe887d297c8a8e4104c3708，completed、无incomplete_details/error、候选契约通过；不可变候选已存，Run awaiting_candidate_ethics，未准入/评分/科学通过 |
| 用量 | input39126/output8543（含reasoning1034）/total47669；cache_write39123/cached0等完整provider_usage均保留；费用未知。早期状态与历史消耗null不填0，不累加同任务GET返回的重复用量 |
| 历史保护 | SQLite备份仓库外保存，仅在原真实库执行。原Task/action/两次uncertain/error/请求/未知用量全行不变；备份12张表的所有原行全字段仍相同，含原Brief/原文/P04/P05/P07。迁移与新执行不解决旧调用 |
| 页面持久化 | 新无凭据/未授权页面进程读取原库：显示原uncertain及后继、completed/用量/完整候选；实际刷新+3次GET，DB字节哈希和Attempt计数保持，无新增POST或查询。原工作区232项指纹不变 |
| 初审 | Codex初审，待独立人工复核；22条原文位置→候选字段对照。发现ANXA11 induces被弱化为相关、SUN1 leading to被弱化为伴随等；不修补输出。释放阶段新猜想/方向与对象发现、干预选择性/测量可行性均待验证 |
| 工程检查 | 项目Python3.12.11/pytest8.4.2新系统328通过、0失败/跳过（含7项获准loopback HTTP）；全仓Ruff沿用CI既有豁免、核验脚本format、JS、实际响应字节/哈希/候选/引用/间隔/历史/刷新检查。初次base Python3.11.5/pytest7.4.0有65 setup errors（263通过），如实记录后改用现有项目环境，无修改测试掩盖错误 |
| 真实/科学边界 | 本次真实Responses链已返回一个候选；不代表生成方法稳定、科学/伦理正确、新颖或实验可行。Goal Ethics仍开发测试；science_validated=false。未执行ASSUMPTION_STRUCTURED、Candidate Ethics、R0或其他下游模块；独立人工/专家复核及旧G3全量未运行 |

[实际请求、每次响应/状态/usage、候选全文、22项初审、备份来源与SHA256](trials/p08-direct-responses-real/README.md)。原始候选/P04/P05/P07不改，原设计状态不变。下方历史状态原文保留。

# 项目状态 — P08显式迁移入口

## 窄范围迁移入口（2026-11-04）

基线远端main `df78cc8cf37eb6671d9b4842c7fbb6e04f6ff76d`；独立分支 `codex/p08-explicit-migration`，提交PR保持未合并。
原工作区232项改动保留；原真实库仅SQLite只读预览，无迁移/新Task/新Attempt/模型请求，未读取模型凭据。

| 维度 | 本轮事实 |
|---|---|
| 迁移预览 | 原Task/双uncertain Attempts、行/冻结请求哈希、新配置/消息/输入哈希、原/新候选关系、可能重复执行/收费及store=true风险；CLI mode=ro不初始化schema |
| 原子创建 | 重新校验预览及四项显式确认后，同Run一次事务创建唯一后继Task、身份预留、迁移和确认事实；源唯一约束/重复同预览幂等，事务提交前后进程退出测试通过；创建不联网 |
| 专属放行 | 只允许该后继Task在每次继续时核对源记录哈希后豁免指定旧Attempts；不全局解锁，不改旧uncertain/错误/请求/未知用量；其他未解决调用仍阻断 |
| 执行/恢复 | 迁移不带付费授权；后继另行显式同意并要求已配置/授权适配器。沿用Responses ID持久化/同ID查询，首次无ID uncertain不自动重发；跨进程只GET、已成功不重提交 |
| 页面 | 只读预览/四项确认、原旧记录/后继关联/未运行状态、另行执行授权；IAB实际操作→创建→刷新保留，新Task0 Attempts/执行按钮禁用；独立夹具非真实Run |
| 真实交付 | 原Task和双Attempts只读预览、完整未发送新请求及SHA256在preparations/p08-explicit-migration；原库前后哈希一致。仅候选身份改为planned-p08-direct-responses，科学Prompt/六字段其余内容不改 |
| 验证 | 最终328 passed、0 failed/skipped（301原有+27新增）；7项HTTP均获准运行；Ruff/47文件format、JS、源Prompt/准备包未改及导出哈希检查通过 |
| 真实/科学边界 | 真实迁移0、真实模型请求0、无ASSUMPTION_STRUCTURED或下游真实科学执行；science_validated=false。仅工程离线夹具，不扩大科学/伦理验收 |

[短实施说明与命令](P08_EXPLICIT_MIGRATION.md) · [真实只读预览/新请求](preparations/p08-explicit-migration) · [测试/页面证据](verification/p08-explicit-migration/RESULTS.md)。
尚未执行真实迁移/真实Responses链、未审阅生成表现/科学有效性；本机Python3.12、旧G3全套、专家评审未运行。
原M00/W1设计状态不变。以下历史状态原文保留。

# 项目状态 — Responses 后台传输修复

## 独立传输可靠性修复（2026-11-04）

起始main经远端核实为 `db37b47598c167d586b743f51f6a078e3c2b0cf6`；独立分支 `codex/responses-background-transport`，提交独立PR，保持未合并。
原工作区232项内容/暂存/状态指纹保持；原真实Run/Task和两次uncertain只读核查，费用/请求/状态不改。

| 维度 | 本轮事实 |
|---|---|
| 传输 | 新Responses后台窄适配器；脱敏代理事实、connect/请求写入/等响应头/读正文、单调耗时；socket与总期限分别显式600秒，无隐藏重试；历史根因未知 |
| M15/M12 | 原子保存ID及响应后只显式GET同ID；跨进程继续、查询错误不重建；queued/in_progress/unknown等待，只有completed且完整候选契约通过才保存；原uncertain阻断不绕过 |
| 输入/配置 | 科学Prompt w1-p08-single-v1与六字段原样；Sol/high/32768/JSON，无temperature、输入不裁剪，145401字节；新执行配置显式store=true及保留确认，与旧store=false请求不伪装一致 |
| 页面 | 远端ID、最近观测状态、等待时长、最近查询结果/断连、显式同ID查询；无ID提交不确定单独提示；IAB及HTTP刷新/重启持久化验证 |
| 验证 | 最终新系统301通过、0失败/跳过；Ruff/44文件format、JS、准备包/请求/SHA256/diff检查通过；6项本地HTTP均获准运行，不跳过 |
| 真实与科学边界 | 本轮模型请求0次，未读取真实凭据；不执行ASSUMPTION_STRUCTURED或下游模块。science_validated=false；真实供应商后台链/模型表现/科学有效性未验证 |
| 仍待处理 | 原两次uncertain费用/执行未知；迁移仅方案，需另行授权和窄入口，不能新Run绕过；供应商保留/组织例外待确认；DNS硬期限限制明确 |

[实现、状态转换与迁移方案](RESPONSES_BACKGROUND.md) · [完整实际请求及配置](preparations/responses-background) · [测试与页面证据](verification/responses-background/RESULTS.md)。
历史设计与原始科学请求/结果不改，W1仍Proposed。本机Python3.12、旧G3全量、真实付费调用、科学/伦理分类验收均未运行。

## 以下为历史状态（原文保留）

# 项目状态 — P08最小生成切片

## P08最小单次生成切片（2026-11-04）

实际起点main5eba330d593a10c711c8b2737bd4180ea5d8ccaa；独立分支codex/p08-minimal-generation，PR保持未合并。原工作区232项改动/暂存指纹不变。

| 维度 | 本轮实际状态 |
|---|---|
| backend_implemented | DIRECT/ASSUMPTION_STRUCTURED两种单次方式；严格六字段固定USER、版本/配置/身份；Result内不可变候选与来源关联；必要P08局部结构/引用校验，不做科学判断 |
| M12_integrated | 同Run/Goal/seed/固定P05包的成功ready放行；非ready/跨seed/包不匹配/最新未解决调用阻断；仅执行generation.P08，停awaiting_candidate_ethics，不创建伦理/R0任务 |
| M15 | 复用实际消息、响应/错误、完整usage、成功回放、显式uncertain恢复；输入超限不发送不裁剪；未知不填0 |
| frontend_integrated | ready选择/两种方式/调用方ID、显式生成、候选章节、来源/版本/状态/用量；开发模式清楚可见，刷新只读；修正异步操作后Run按钮busy复位 |
| 实际输入 | 原真实Run只读备份导出两种未发送请求，145327/145357字节≤262144；原库字节哈希不变，未创建P08任务；无示例答案/审阅/兄弟候选 |
| 工程验证 | 最终267通过（239+28）、0失败/跳过；Ruff/40个src/tests/example文件format、JS语法通过；跨进程成功回放、HTTP重启/待执行不自动发送、IAB两模式页面操作/展开/刷新验证通过 |
| 执行与科学验证 | 真实模型调用0次；浏览器仅独立库2个开发候选/2个开发Attempt。science_validated=false，真实生成表现/方法优劣/科学有效性均未验证 |

[实施边界、字段、运行命令和限制](W1_P08.md)；[真实背景未执行输入](preparations/p08-unexecuted)；[测试/页面证据](verification/p08)。
原设计及已验收修订不改；原P04/P05/P07及其科学问题不改写，Goal Ethics仍为开发测试结果。
未实现Candidate Ethics、R0、Reflection、Ranking、Evolution或完整科学Schema/平台；未运行本机Python3.12、旧G3全量、真实模型/专家评测。下列历史保持原文。

## P07同Task授权恢复与最小安全诊断（2026-11-04）

基线远端main378475b2e5a86d1c6504138bc3992dae2c977e81；独立PR分支codex/p07-transport-recovery，不合并。诊断代码909107b7a00227e70ed11f8cff1e1ab2d4eb385a。
只读检查原库/20相关文件，无可关联完整响应；这不证明原请求未执行。原Attempt0d9e7d5fd9da4bbea3ddc42608e0c184仍uncertain、原错误/未知用量不变，仅以authorize_uncertain_retry记录用户接受重复执行/收费风险。
最小补丁仅允许列表category/phase/code，不保存原始异常文本/凭据/鉴权头/请求正文到诊断；不改uncertain、成功回放或自动重试语义。
通过Store.recover/authorize_uncertain_retry/retry_task及既有BackgroundService恢复原Task55bc66f3e1a44070babcf67db99b0bac，新Attempta283b83163334165a902a00362b49c2d ordinal2/previous_id关联原Attempt；仅1次新请求。
冻结call_key/model输入/Prompt/配置/HTTP请求完全一致：148027字节，gpt-6.1-sol/high/32768/JSON object、无temperature、600秒、原262144上限。HTTP200/stop/saved，P07 decision=ready，停awaiting_generation，不执行P08。
新调用40396输入/3224输出（含reasoning876）/total43620；原调用消耗未知，两次完整总耗用/费用未知。无新Run/Task、无前序重跑、无检索/获取/视图新增，原行哈希保护。
[恢复前后/实际请求/完整响应usage/6项依据与初审](trials/p07-recovery-real/README.md)。ready仅是单模型对条件性探索准备的判断，不证明机制/实验可行性/新颖性；P05措辞弱化及原体系归属问题仍待专家复核，原结果不改。
聚焦102通过，最终新系统239通过、0失败/跳过（203+36）；Ruff/35文件format、导出/只读DB/哈希/ZIP解压检查通过，原工作区232项保持。未运行旧G3全量、本机Python3.12、浏览器、专家/科学验证。
Goal Ethics仍开发测试；science_validated=false。未执行P08、Candidate Ethics或R0。以下历史不改写。

## P04 context-v2 与独立新Run准备（2026-11-04）

实际起点main：`87668c8ee84a52aa3109830cd7dbef02d0a32f28`；独立分支`codex/p04-context-preparation`。
代码/准备数据commit：`776b202383ab47d112d5d4e95bc76c023a05014f`；后续提交仅STATUS/验证记录，独立PR不合并。

| 维度 | 本轮实际状态 |
|---|---|
| P04 | 新版本w1-l2-p04-context-v2；按实验保留Abstract/Highlights/In Brief互补情境；缺失限定当前视图；忠实保留作者诱导/相关措辞，限制单列；原字段区分来源报告/作者解释/模型外推/未建立关系 |
| 历史兼容 | 每个action固定版本；老库仅追加身份列，原v1文字保留，不重写请求/响应/结果；跨进程成功回放不重发测试通过 |
| 新Brief/Run | 新Project/Revision/Run、独立库；原科学问题及两项约束保留，新背景移除“仅检索、不执行阅读”；旧Brief/Run和原试跑文件未变 |
| Goal/伦理 | 新Run仍用明确开发模式Goal/Goal Ethics替身与示例政策，不是真实制备/伦理审查，不作为生产默认 |
| 实际材料 | 重新取得首次预印本2746字符摘要对照（与原文相同）；另取PMID35112738/PMC9016352开放全文125363字符，显式选Results小节[33770,41370)共7600字符；保留完整所得内容、未选范围与原始响应 |
| 来源边界 | 新增材料为条件依赖的无效应/作者限制对照，不是ANXA11播种研究的直接反驳、独立复现或核孔蛋白磷酸化证据；CCBY4许可及作者/DOI保留 |
| 实际发送 | 本轮5次真实公共发送（人工身份查询2、metadata2、fulltext1）均经M15；无隐藏重试；新库另有2个本地Goal开发替身Attempt，不能计真实模型调用 |
| 模型与科学模块 | **0次模型请求**，新库P04阅读/seed/readiness/背景动作均0；未在该Run执行P05–P07、P08、Candidate Ethics或R0；新Prompt模型遵从性及科学表现未验证，science_validated=false |
| 待执行配置 | gpt-6.1-sol/high/max_completion_tokens32768/JSON object，无temperature，timeout_seconds600；不读模型凭据/不授权；不自动使用替身 |
| 页面 | 已显示新Prompt版本、材料片段/范围、未授权无凭据模式及Goal测试声明；IAB刷新实测仍读取已存数据，阅读/真实模型Attempt为0，无浏览器错误 |
| 检查 | 在代码commit776b202上新系统**203 passed、0 failed、0 skipped**（原197+新6），含本地HTTP与跨进程恢复；Ruff/7文件format/JS语法/独立包校验通过 |

[准备包/恢复/页面与待执行命令](preparations/p04-context-v2/README.md) ·
[来源/选择/范围清单](preparations/p04-context-v2/material-manifest.json) ·
[验证证据](verification/p04-context-v2/RESULTS.md)。
本轮不进行真实P04试跑，不把工程检查或Codex选材当科学验收；独立专家审阅、新Prompt真实模型效果、本机Python3.12及旧G3全套回归均**未运行**。
原工作区232项改动与暂存指纹保持不变。原M00 Accepted及W1 Proposed状态不改变；不直接合并本轮PR。

## 以下为PR #8及更早的历史交付记录

## 首次真实P04：初审与独立PR交付（2026-11-03）

基线main重新fetch核实为 `e705953818feb866dddfcb8093fbc6230e02978f`。
独立分支 `codex/w1-l2-trial-preparation`；代码commit `796a94b497978e7010cf5f3a2ae5e0cef926085e`，
后续提交仅为审阅/验证证据及本状态；本轮提交独立PR，保持未合并，未改main。
用户原工作区232项改动及暂存状态指纹保持不变，不切换/不stash原工作区。

| 维度 | 当前事实 |
|---|---|
| 真实文献及访问 | 已取得Europe PMC PPR1217875预印本摘要字段2746字符；含文字Highlights/In Brief，非全文、未看图或补充 |
| 已授权单次真实P04（前一轮） | gpt-6.1-sol/high/32768/JSON object，无temperature，timeout=600秒；HTTP200/stop，saved；仅一个Attempt，无自动重发 |
| 完整用量 | 输入1477、输出2785（含reasoning1010）、合计4262；cache_write1474/cached0；cost=null；原响应/完整usage保留 |
| 本轮新真实模型调用 | **0次**，仅导出/文本初审/离线测试/代码PR；不执行P05–P07、P08、Candidate Ethics或R0 |
| 模型阅读审阅 | **Codex 初审，待独立人工复核**，35项带原文字符位置/实际字段/问题；未改原始输入、模型输出或解析结果 |
| 科学与伦理验证 | science_validated=false；Goal/Ethics仍为开发适配器事实；不声称真实伦理审查、独立发现或完整W1-L2真实阅读验收 |
| 代码 | 可选显式timeout、兼容旧请求形状、finish_reason/完整provider_usage、空正文/截断/无效JSON拒绝解读、稳定trial ID和本次Attempt用量 |
| 当前工程验证 | **197 passed、0 failed、0 skipped**，在代码commit796a94b上全量tests/next；包含此前未重跑4项HTTP |

此前196和193两次均为HEAD=e705加未提交修改，并非两个已提交版本；196+新增1项旧请求兼容性测试=197，
排除4项HTTP后=193。上轮全量复跑审批容量失败的缺口已在本轮获准回归中补齐；
详细命令/代码版本边界/历史日志见[测试证据](trials/w1-l2-first-real-p04-review/TEST_PROVENANCE.md)。
旧G3全套回归、本机Python3.12和独立专家科学审阅本轮**未运行**。

[审阅包入口](trials/w1-l2-first-real-p04-review/README.md) ·
[35项对照](trials/w1-l2-first-real-p04-review/codex-initial-review.md) ·
[ZIP](review-bundles/w1-l2-first-real-p04-review.zip)（SHA-256见旁边.sha256）。
未发布SQLite/旧替身P04–P07记录/凭据；仓库可访问路径交付，不只提供本机链接。

初审重点：SH-SY5Y情境遗漏，“未知”须限定视图，“诱导”与“伴随”的措辞层次、作者机制总结句定位、
空阴性数组不等于干预无效；固定Goal存在早期仅检索阶段的历史文字，已披露但不篡改本次输入。
以上为Codex文本初审，不是独立科学验收；原W1包仍Proposed，M00不变。

## 以下保留PR #7及更早交付的历史记录

## PR #7 总控复现修正（2026-11-03）

修正起始head：`43ca215b0e7f7ac19b353ca4107d728e1449398f`；继续同分支/PR，不合并。
原进展指纹只含材料/查询，遗漏了阅读和背景综合的实质变化，可能把补充阅读后的P07错误判成no_progress。
现以内容规范化P04卡片/待读请求、P05概览/竞争解释/关系及依据/限制/选择，与原文/查询/具体程度一起比较；
临时引用映射成对应内容并去重，不把新ID、时间戳或重复记录计作进展。不同Run/seed范围保持隔离。
历史P07按已保存input重算新指纹，历史结果不改写，无数据迁移；新记录标记p07-preparation-content-v2。
页面提示已同步。新增回归覆盖同原文有效重读、仅综合更新、重复阅读/重建包、ID/时钟变化和seed隔离。
本轮无真实付费模型调用、无新公共检索、无P08/Candidate Ethics/R0或科学验收扩展。
限制：比较结构化内容，不判断科学价值；自然语言同义改写可能触发重评。
本次检查：183 passed、0 failed、0 skipped（原176 + 新7），背景专项23项通过；
Ruff/33文件format、两JS语法、Wheel构建和新编文件空白检查通过，用户232项改动指纹未变。
页面实测以旧版P07已保存输入作相同内容检查，v2返回no_progress且无新Attempt（13→13）；刷新0 POST，无JS错误。
记录见 [progress-fix-tests.txt](verification/w1-l2/progress-fix-tests.txt)、
[页面检查](verification/w1-l2/progress-fix-browser.json)及[提示截图](verification/w1-l2/progress-fix-no-progress.png)。
未运行真实模型/付费调用、专家科学审阅及Python3.12本地回归；原科学未验证状态不变。

## 原W1-L2交付（2026-11-03，Asia/Shanghai，以下保留原验证记录）

重新fetch核实main / 起始commit：`cb3f79f987e6c14a6f8d2c5475868f17414f7a96`，PR #6已合并。
独立分支 `codex/w1-l2-reading`，checkout `/private/tmp/co-scientist-w1-l2`；独立PR，不直接合并。
最终head以该PR及 `git rev-parse HEAD` 为准。用户原工作区232项改动、暂存区与status指纹保持不变。
M00 Accepted、W0-T4接受决定不改，原W1 v0.4包仍Proposed，旧G3未改。

| 维度 | 实际状态 |
|---|---|
| 已实现 | P03计划/显式LiteraturePort执行接入、P04选定视图阅读、P05中性/单seed综合、分离P06定向与开放调用、P07逐seed readiness |
| 真实适配器 | 独立OpenAI Chat HTTP客户端、显式模型/端点/参数配置、独立凭据与授权开关、无SDK隐藏重试、实际请求/原始响应/用量记录 |
| 替身验证 | 离线夹具、模拟OpenAI HTTP、真实本地页面/SQLite持久化和恢复已验证；不计为真实模型阅读 |
| 真实模型调用是否执行 | **未执行**，本轮0次真实供应商请求/付费模型调用；只提供后续另获授权后的单次P04命令 |
| 模型阅读表现是否审阅 | **未审阅**；未做真实输出科学准确性、负结果理解或种子质量审阅 |
| 科学有效性是否验证 | **未验证，science_validated=false**；不宣称完整W1-L2已通过真实阅读验收 |
| 页面/M12 | 逐步显式操作、原文/模型解读分区、状态/负结果/来源/背景/seed/readiness/配置/用量可读；ready停等待生成，刷新不执行 |

只增加material_views与background_actions两表，复用Run/Task/Attempt/Result；无独立服务或通用图工作流。
新代码：background.py、background_ops.py、reading_model.py、background_trial.py和background.js。
Store/Scheduler/workspace及既有LiteratureService只作当前切片必要接入，不调用旧Orchestrator。
实施/操作/官方文档/输入隔离见 [W1_L2_BACKGROUND.md](W1_L2_BACKGROUND.md)。

### 运行与当前可操作页面

```sh
cd /private/tmp/co-scientist-w1-l2
PYTHONPATH=src python -m co_scientist_next.workspace --db runs/w1-l2-live.sqlite --port 8786 --development-test --development-reading --public-literature
```

已启动 `http://127.0.0.1:8786/#run=9b5abf8a5ccd496d8c45ff9a6666b20e`。
数据库是既有W1-L1真实获取事实的一致独立备份，源数据库只读、未修改；不是V5内置结果。
Goal/Ethics与本轮背景结果均清楚标为开发替身，材料是真实已取得文献。模型与公共检索各需显式启用/操作，启动不发送。
没有配置时不回退替身；真实模式没有授权时不发送。当前无真实模型凭据读取。

### 最小契约和边界

- 材料视图固定Run/Goal/seed范围、获取Task、来源/版本/位置、字符范围/SHA与裁剪理由；原始材料不被转述覆盖。
- P04保留上下文、干预/对照、实测终点、观察/负结果、作者解释、未证明与外推。摘要/片段不升级成完整全文阅读，图像/补充未读。
- P05使用实际解读与执行查询；保留所选卡片/原文/负结果/竞争解释与覆盖限制。不做M05正式评级、M06 Dossier或新颖性结论。
  排除解读需显式理由，当前不允许排除已知负结果；容量不够明确不调用，不无记录截断。
- P06_OPEN单独调用，实际输入仅Goal、中性概览、来源能力、通用约束；没有定向seed/优先机制/兄弟资料/评审答案。
  seed是问题，数量是本次配置，不成为全局科学规则；不是候选答案。
- P03保存计划不等于执行；显式执行通过LiteraturePort/M15，宽/seed意图及后续分页/fetch继续保留。兄弟定向资料/解读不能混入开放分支。
- P07 ready/retrieve_more/unable_to_prepare分别记录理由/具体程度/缺失及后续动作；无因果桥证明、判别预测完成或论文/全文配额要求。
  同资料/覆盖/具体程度不无限重复，no_progress不发模型、不改科学结论；一个seed未准备好不阻止其他seed ready。
- 技术失败/无效输出/缺配置与科学未知分离；成功本地回放，幂等结果与任务；响应保存失败留下未决发送时也不能绕过恢复继续新模型任务。
  每seed的完成决定固定在自己的packet；Run状态是最近机械操作状态，不是全局科研完成。

### 真实试跑（本轮未执行）

公开配置模板 [reading-model.explicit.json](examples/reading-model.explicit.json)故意不选model。
先另获授权、填入明确模型与支持参数，并通过独立环境变量/仓库外私密文件提供凭据。
单运行者SQLite要求先停止占用该库的页面。帮助和不带执行标志拒绝路径已验证，下面真实执行命令**未运行**：

```sh
PYTHONPATH=src python -m co_scientist_next.background_trial --db runs/w1-l2-live.sqlite --run-id YOUR_RUN_ID --view-id YOUR_SAVED_VIEW_ID --config /private/tmp/reading-model.json --credential-env CO_SCIENTIST_READING_KEY --execute-real-call
```

仅做一次P04，不自动综合或生成；seed视图另传seed-id。密钥不进公开配置/Prompt/M15/Git/日志；回显脱敏、异常信息去凭据。
实际HTTP body/模型配置/Prompt版本/完整消息/原始响应、解析错误与可得用量持久保存。成本未知为null，未用量不填0。

### 实际验证

环境macOS / Python3.11.4，复用已有环境；无新生产依赖，支持兼容conda，不强制.venv。
浏览器使用临时工具Playwright1.64.0与Chromium1248。

| 检查 | 实际结果 |
|---|---|
| `PYTHONPATH=src python -m pytest -q -s tests/next` | 176 passed，0 failed，0 skipped（原142 + 新34） |
| 输入/材料/seed隔离 | Run/Goal/来源/视图/seed/packet绑定、原文与转述分离、负结果/限制、开放四字段、评审字段隔离、P03范围继承通过 |
| 供应商模拟HTTP | 实际请求格式/响应/usage、非stop完成、HTTP302/429/503不重试、凭据回显脱敏/异常脱敏、未配置/未授权无回退均通过；不是实际供应商成功 |
| readiness | 三分支、假设未知可保留、未准备seed不阻挡其他ready、重复检查无进展停止、技术问题无科学决定通过 |
| M15/跨进程 | 真正os._exit于P04成功响应保存后、结果应用前退出；另一PID只回放，fixture发送仍1；重复应用/不确定授权谱系及响应保存失败反例通过 |
| 本地HTTP/页面 | HTTP服务子进程重启后背景/seed事实不变；实际浏览器14动作/13替身Attempt/3条解读，刷新POST=0、固定Brief与L1材料不变、无JS错误、390px无溢出 |
| Ruff / JS | check与33文件format通过；两份前端JS语法检查及Prettier通过 |
| Wheel | 构建与隔离运行通过；4份页面资源、真实客户端导入和离线P04–P07持久链可用，无真实发送 |
| 原工作区/原件 | 用户232项指纹不变；未改M00/W0/W1原件；新编文件空白检查通过 |

[tests.txt](verification/w1-l2/tests.txt)、[浏览器报告](verification/w1-l2/browser.json)、
[完整开发执行证据gzip](verification/w1-l2/development-execution.json.gz)、[页面](verification/w1-l2/workspace.png)、
[解读](verification/w1-l2/saved-reading.png)、[seed](verification/w1-l2/seeds.png)、[刷新](verification/w1-l2/after-refresh.png)、[移动](verification/w1-l2/mobile-seeds.png)。
初期浏览器脚本CSP等待/隐藏控件选择问题已修正并重跑，诊断数据库保留；没有放松CSP。
本轮P03执行接入用响应夹具验证，页面只保存未执行计划；未新增真实公共文献请求，未执行真实模型调用。

### 未实现、未运行与待审阅

未实现P08、Candidate Ethics、R0及后续模块；无候选、排名或科研完成。未建无人值守循环、全自动分块综合或知识图谱服务。
真实供应商兼容性/权限/计费/模型输出质量尚未试跑；工程引用检查不能证明引文支持、正确情境理解或seed科学价值。
真实模型上下文限制由显式技术配置和供应商错误处理，不把字节限制当token保证。
**未运行：** 真实模型/付费试跑、真实阅读表现/专家科学审阅、科学有效性与开放/定向策略评测、完整W1-L或S01–S14、湿实验、旧G3全套本地测试、Python3.12本地回归。
待专家审阅：转述准确性/负结果与情境保留、中性综合遗漏/偏向、seed是否问题、readiness具体程度是否合理。
无新增需总控修改M00规则的跨模块冲突；后续真实试跑与科学验收需另行授权。

---

## W1-L1历史交付（以下按当时状态保留）

## 当前交付（2026-11-03，Asia/Shanghai）

实际fetch核实main：`47a8a09b7730bd869843e4fc236e9a2f9f1d061f`，与用户参考一致，PR #5已合并。
本轮独立分支 `codex/w1-l1-literature`，checkout `/private/tmp/co-scientist-w1-l1`，独立PR不合并。
最终head以该PR及 `git rev-parse HEAD` 为准。原工作区232项用户改动、暂存区与status指纹未变。

M00仍Accepted；W0/W1原件保持Proposed，W0-T4已接受修订不变。**本轮只交付W1-L1，不是完整W1-L或科学验收。**

| 维度 | 实际状态 |
|---|---|
| 真实检索 | Europe PMC官方公共REST已接入；用户/开发者人工查询，未实现Agent规划；空结果/技术失败/部分完成/未穷尽分页分开 |
| 实际材料获取 | core元数据/摘要、OA PMCID全文XML已实现并实测；保存实际字节、文本、定位和访问限制；图像/补充未获取 |
| M12接入 | 已保存的completed Goal Ethics pass才可追加search/fetch任务；复核政策/Goal身份；固定Goal与旧查询不覆盖 |
| 页面接入 | 人工查询、显式翻页、来源列表、摘要/全文、数量/游标/错误/真实历史可读；伦理结果改为易读状态和理由，原JSON折叠；刷新只读 |
| 模型阅读 | 未实现，全部材料标“已获取、尚未解读”；没有背景发现或主张支持判定 |
| 科学能力 | `science_validated=false`；Goal筛查仍确定性开发测试，真实公共文献获取不构成真实伦理审查/生产科学链 |

实现：新增 `europe_pmc.py` / `literature_runtime.py`，沿用LiteraturePort；Store只增加小型动作索引表，
M12只增加两命名操作条件接入；workspace增加显式API/开关，页面同步接入。未连接旧G3。
每次HTTP经M15，保存实际请求、原始响应/错误、时间、调用关系和未知用量；无隐藏重试/跳转。
成功响应可回放；重复request_id不重复执行；不确定发送需显式核实，不能宣称外部exactly-once。

操作/官方依据/范围/来源证据见 [W1_L1_LITERATURE.md](W1_L1_LITERATURE.md)。
选择Europe PMC是因为同一官方公共来源提供检索、core摘要和OA全文XML，无需模型或付费凭据。
用户明确输入查询，不实现P03查询规划、P04模型阅读或后续科学方法。

```sh
cd /private/tmp/co-scientist-w1-l1
PYTHONPATH=src python -m co_scientist_next.workspace --db runs/w1-l1-live.sqlite --port 8785 --development-test --public-literature
```

当前可操作页面 `http://127.0.0.1:8785/`；主验收固定Run：
`http://127.0.0.1:8785/#run=9b5abf8a5ccd496d8c45ff9a6666b20e`。
必须分别显式启用测试Goal适配器与公共文献请求；示例政策不自动成为生产政策。

### 真实请求与页面证据

已有ALS-GOAL开发者转述保留原问题/磷酸化条件；人工宽查询：
`"amyotrophic lateral sclerosis" AND (nucleoporin OR "nuclear pore")`。
未预选具体分子；查询只是宽概念入口，不声称覆盖Goal全部条件或穷尽文献。

- 主验收5次显式动作、6次真实HTTP：第一页面5条/报告1781、返回预印本PPR1217875摘要2746字符、
  返回MED42437963对应PMC13357693全文XML（展平113989字符）、第二页5条仍未穷尽、工程不存在ID查询成功0条。
- 全文文献是review；没有认定为独立实验证据。预印本未认定同行评议或与正式版独立。
  实际来源/许可/定位及原字节均保存；DOI不同不推断独立性。
- 初期另4次诊断HTTP保留失败：2次EXT_ID身份lookup空记录、1次article单对象响应解析未匹配，及其首次查询。
  修正为官方article身份接口/单对象解析。失败未删除，不改成“没有证据”；合计10次发送都有M15 Attempt。
- 浏览器通过页面创建/保存/执行，查看摘要/全文后刷新：POST新增0，历史完全一致，无JS错误；390px无横向溢出。

[浏览器报告](verification/w1-l1/browser.json)、[固定Run](verification/w1-l1/run-snapshot.json)、
[真实请求及材料gzip](verification/w1-l1/public-acquisition.json.gz)、[初期诊断](verification/w1-l1/diagnostic-acquisition.json.gz)、
[页面](verification/w1-l1/workspace.png)、[刷新](verification/w1-l1/after-refresh.png)、[移动](verification/w1-l1/mobile.png)。
原始响应SHA-256可离线复核。记录不是夹具，取得不代表模型已经阅读或评价。

### 实际检查

macOS / Python3.11.4，复用现有Python环境，无新生产依赖；兼容conda，不强制.venv。
浏览器验收使用临时目录Playwright1.64.0和Chromium1248。

| 检查 | 结果 |
|---|---|
| `PYTHONPATH=src python -m pytest -q -s tests/next` | 142 passed，0 failed，0 skipped（原109 + 新33工程/获取检查） |
| 离线响应夹具 | 明确虚构标识；空结果、HTTP失败、部分行、分页、重复结果、各访问层级、错源/空正文/abstract-only/截断、幂等/非pass阻断均通过；不冒充真实接入 |
| 跨进程恢复 | 实际os._exit于成功HTTP保存后中断，新进程通过保存响应回放，Attempt仍1，不重新发送；原恢复测试回归通过 |
| HTTP持久化/重启 | 真实loopback子进程服务+虚构响应夹具；POST幂等、GET不重发、重启读取通过 |
| 真实公共接入 | 上述6次主验收+4次诊断M15发送，摘要/开放全文路径确已完成；没有付费模型 |
| Ruff check / format | 通过；26个Python文件格式检查通过 |
| JavaScript | node --check通过；Prettier格式化 |
| Wheel | 构建通过；隔离从wheel加载页面资源、固定Goal门及离线获取持久化通过 |
| 原件/工作区 | 未改原M00/W0/W1设计文件；用户232项改动指纹不变；新编文件空白检查通过 |

测试输出：[tests.txt](verification/w1-l1/tests.txt)。网络错误和初期解析失败保留在诊断证据，不能靠夹具通过替代真实请求。

### 已知限制、未运行及后续边界

尚未实现：自动查询生成、真实Goal模型适配器/伦理分类准确性、模型阅读、知识图谱、seed readiness、候选生成、
M03–M11科学逻辑、图像/补充获取、研究独立性/主张支持判定、全面文献覆盖；仅单进程loopback页，无远程多用户认证。
源端结果会变化，1781只是当时provider报告；已保存材料不能等同全文全部附件或科学证据已验证。

**未运行：** 付费模型/真实模型阅读、专家科学评测、完整W1-L与S01–S14科学流程、湿实验、旧G3全套本地测试、Python3.12本地回归。
没有新增需要总控裁决的跨模块冲突。进一步科学能力需要另行授权与验收。

---

## W0-T4历史交付（以下按当时状态保留）

## 当前交付（2026-11-03）

PR #4 固定 head `c6f7e0949f9353bfcd9ea1d8be28daef273f8292` 复核未变，4项CI成功，
无新增阻断、状态检查或冲突；按该SHA约束合并。合并 commit / 本轮实际起始 main：
`aa2cc7fe0a2b12398ba71d8dcc0c75a0c230a004`。本地 main 已更新。
独立分支 `codex/w0-t4-goal-workspace`，checkout `/private/tmp/co-scientist-w0-t4`。
本轮新PR不合并；最终head以该PR及 `git rev-parse HEAD` 为准。
原工作区仍在原分支/HEAD，232项用户改动、暂存区与status指纹保持一致。

| 维度 | 本轮实际状态 |
|---|---|
| 后端 | M01 prepare_goal、M02 screen_goal最小契约/输入保留/持久化实现；确定性开发适配器；真实供应商尚未接入 |
| M12 | 两命名操作的条件推进已接入；只有completed pass进入awaiting_background，未创建背景或Generation任务 |
| 页面 | 创建/保存Brief、固定Run、显式执行、结果与澄清展示、刷新读取SQLite已接入 |
| 科学验证 | `science_validated=false`；自然语言抽取、关键歧义判断、伦理分类准确性和真实模型表现未验证 |

W1原7文件逐字节保存于 `design/w1-method-v0.4-proposed/`，保持Proposed；
原ZIP及V5参考哈希见 `design/w1-v04-source-integrity.json`。
V5只参考布局/视觉，不导入其内置案例或假候选。M00 Accepted、旧W0/真实案例原件及旧G3保持原状。
用户已接受修订单列 [W0_T4_DECISIONS.md](W0_T4_DECISIONS.md)：P08六字段一致的采用示例、
DIRECT/ASSUMPTION_STRUCTURED单次方式、R0明确事实错误政策（未实施）、Goal Ethics完成决定仅pass/reject。
Candidate Ethics不改；W1整包不转Accepted。

实现文件：`goal.py`、`workspace.py`、`frontend/*`；Store新增Goal/Run配置表与原子结果应用，
Scheduler增加当前两操作的条件分支；pyproject打包页面资源。另有两组Goal/HTTP测试、浏览器脚本、
源文件完整性记录、采用示例、决策/操作文档及实际验证记录。新运行链不依赖旧Orchestrator。

启动（兼容现有Python/conda，不强制新环境，无新生产依赖）：

```sh
PYTHONPATH=src python -m co_scientist_next.workspace --db runs/goal-workspace.sqlite --port 8784 --development-test
```

交付时已启动页面 http://127.0.0.1:8784/ ，实际数据库 `runs/w0-t4-live.sqlite`。
显式开发模式和政策示例需主动启用；不带开发参数不会连接真实模型或加载默认政策。
操作/适配边界详见 [W0_T4_WORKSPACE.md](W0_T4_WORKSPACE.md)。

### 本轮实际检查

环境：macOS、Python3.11.4，使用已有 `/Users/lemintea/Documents/co-scientist/.venv/bin/python`；
Playwright1.64.0仅装入临时工具目录，实际Chromium1248，未添加生产浏览器依赖。

| 检查 | 结果 |
|---|---|
| `PYTHONPATH=src python -m pytest -q -s tests/next` | 109 passed，0 failed，0 skipped；含原80项回归和29项新增工程检查 |
| 跨进程恢复 | 实际os._exit中断于prepare成功调用保存后；不同PID恢复，prepare发送1次、screen1次；另含原恢复/不确定发送回归 |
| HTTP持久化/恢复 | 子进程服务重启可读原Run；未完成运行GET/启动不执行，显式POST才恢复，保存成功调用不重发 |
| 浏览器真实页面操作 | pass/reject/澄清/风险信息缺失/无效输出/技术失败/缺政策；刷新新增POST为0，草稿更新不改固定Run，无页面JS错误 |
| 布局 | 桌面和390px移动截图；移动无横向溢出 |
| Ruff check / format | 通过；22个Python文件格式通过 |
| JavaScript语法 | node --check通过 |
| 原附件一致性 | ZIP SHA与7文件逐字节比对通过；V5参考SHA匹配 |
| Wheel | 构建成功；隔离从wheel加载3页面资源并完成开发Goal切片 |
| 空白检查 | 新编文件通过；原附件Markdown原有行尾空格原样保留 |

测试输出：[w0-t4-tests.txt](verification/w0-t4-tests.txt)；
页面报告：[w0-t4-browser.json](verification/w0-t4-browser.json)，
[桌面](verification/w0-t4-workspace.png)、[固定Run](verification/w0-t4-fixed-run-after-edit.png)、
[移动](verification/w0-t4-mobile.png)。HTTP最初受沙箱禁止绑定loopback，授权本地主机端口后实际重跑通过。

### 剩余能力和限制

没有真实API/付费模型调用；真实适配器、生产安全政策、背景调研、Generation、Candidate Ethics、R0、
M03–M11科学实现均未接入。工程替身只复制结构化条件/返回固定情景，不能证明科研或伦理能力。
缺信息/政策、无效输入输出、技术失败为执行状态，不是第三种完成伦理决定；科学未知不自动拒绝。
原问题保守原样保存，真实自然语言条件分类和关键歧义有效性待真实适配器及专家确认。
仅单进程loopback页面，无远程/多用户认证；刷新不自动恢复。不确定外部发送需明确核实/授权，
不承诺外部exactly-once。缺政策/澄清等已停止Run需要以修订输入/政策创建新Run。

**未运行：** 真实模型能力/伦理分类科学评测、专家盲评、湿实验、完整S01–S14科学流程、
旧G3全套本地测试、Python3.12本地回归。无新增需要总控裁决的跨模块冲突；
生产政策和科学有效性仍须另行审批/评测。

---

## W0-T3历史交付（以下按当时状态保留）

更新：2026-11-02，Asia/Shanghai。本轮为公开真实开发案例采用、来源核对和 M01/M02 实施提案，
**没有实施 M01/M02 生产科学逻辑，没有执行科学模型评测或付费候选生成。**

## 起点、分支与设计状态

- 实际 fetch 后最新 main / 起始 commit：`e98404cda9ec35a82a1c363c14e315f54e240d96`。
  PR #3 已合并；W0-T0/T1、W0-T2 的代码及验收历史保留。
- 分支 `codex/w0-t3-real-cases`，工作目录 `/private/tmp/co-scientist-w0-t3`；独立 PR，本轮不合并。
  最终 head 以 PR head 和该分支 `git rev-parse HEAD` 为准。
- 原工作区仍在 `codex/preserve-local-before-w0-t2`，旧 HEAD 为
  `c2ddbda03f84d5a52f46b47d942b2cce710c919b`；未 reset/stash/覆盖用户文件。
- M00 仍是 Accepted；W0 最小设计、真实案例包、本轮采用说明和 M01/M02 提案均保持 Proposed。
  `reference/` 仍为历史材料；旧 G3 固定参考 `7313ca032e4f5f0c84578523e0f5639ad038e7af` 未删除。

## 附件与采用材料

用户给定 Downloads ZIP 路径已不存在；在项目文档目录找到唯一同名副本：
`/Users/lemintea/project/project/co-scientist/M0-M20开发文档/CoScientist_W0_Real_Cases_v0.1_PROPOSED.zip`。
实际 ZIP SHA-256 为 `8c4f695826657e45ed7b6feb8fba2a76862c73f2995d8cc8b5b421e2b47b6075`。

两个原文件原样保存至 `docs/design/w0-real-cases-proposed-v0.1/`。
其中“来源核对完成”和 R06 “独立研究”的原有文字保留，但不作为本轮已验证结论。
采用已有 ALS、AML/KIRA6 和 R01–R06，未新建另一套完整疾病案例。

`evaluation/w0_real_cases/` 的审计、材料短转述和输入选择是采用层，不改原包：
区分报告观察、作者模型输出、作者解释、开发重建和项目路由预期。
ALS 原始 Goal 的来源定位/转述、加入 iPSC 情境的开发 Brief、公开示例 Hypothesis 分开。
R01 的机制覆盖只评价给定假说拆解，不要求自由生成复述同一分子机制。

## 实际核对来源及限制

| 来源 | 本轮实际取得/核对 | 未验证部分 |
|---|---|---|
| P-01 arXiv 2502.18864v1 | 版本、标题、摘要、2025-02-26提交历史 | 各具体结果首次公开位置、预训练泄漏均未独立审计 |
| P-02 Nature DOI 10.1038/s41586-026-10644-y | 主文 HTML 的 AML/Fig.3图注与数值正文、肝纤维化段、ALS警告、引用/作者关系 | 原图独立数字化、全方法与原始数据重分析未做 |
| P-03 120页补充PDF | 所列 Note10.1/10.2/10.5/10.6、5.2、6 的具体段落与实体页码 | 部分截图cache miss；非整份内容或模型Trace的完整复核 |
| P-04 KIT研究 | Europe PMC MED30931942 官方身份/摘要；另有索引片段 | publisher重定向及PMC CAPTCHA；未核对全文方法/图 |
| P-05 选择性研究 | PubMed/Europe PMC MED33290055摘要与 DOI 10.1021/acschembio.0c00802 | 原包ScienceDirect URL 403且身份待核，ACS页面403；全文未核对 |
| P-06 HSP60研究 | Europe PMC MED34453119 官方身份/摘要与 DOI | 直接页面访问受限；全文方法及AML情境适用性未核验 |
| P-07 肝纤维化配套论文 | PMC全文HTML选定段落、作者/贡献、数据声明与计数口径 | 原始图像、样本/批次及GEO/Zenodo数据未下载对齐 |

位置、URL、访问限制、官方摘要响应哈希和研究关系详见
[来源/案例说明](W0_REAL_CASES.md)及 `evaluation/w0_real_cases/source_audit.json`。
P-08/P-09 本轮未使用、未核对。未进行当前FDA批准或临床注册库的全面搜索；
Note6有关药物安全/新颖性的模型输出不能作为当前监管或全球新颖性事实。

R06 配套论文与主文存在引用、作者及项目关联，不能默认计为独立复现；
精确样本/批次重叠仍待核实。三类推荐靶点、五种抑制剂与25药物池不混为同一分母。

## 交付范围与未实施能力

- 新增原附件两文件及完整性记录。
- 新增 `evaluation/w0_real_cases/{source_audit,materials,adoption}.json`。
- 新增 `src/co_scientist_next/development_cases.py`：仅固定数据读取、白名单导出、引用/访问一致性检查。
  `expected`、`critical_failures`、评审及评分记录有独立审阅路径，不进入导出的被测输入。
- 新增 `tests/next/test_development_cases.py` 和 `docs/verification/w0-t3.txt`。
- 新增 [W0_REAL_CASES.md](W0_REAL_CASES.md) 与 [M01_M02_PROPOSAL.md](M01_M02_PROPOSAL.md)。
  更新本STATUS、AGENTS和设计目录说明；既有 M12/M15生产实现与全部原基线未改。
- 固定模式实际可见材料是短转述，非全文。R03当前视图仅读作者评议，R05当前视图仅解释给定数值，
  不能声称已实现原任务的独立新颖性检索或原图提取。
- 开放模式只导出题目与搜索起点，不执行检索。两模式分开记录，所有材料均为公开开发集，非盲测/独立发现。
- 没有 M01/M02科学函数、完整科学Schema、M03–M09实现、检索策略、通用评测平台或新服务。

## 实际执行检查

本地 macOS / Python3.11.4，使用现有 `/Users/lemintea/Documents/co-scientist/.venv/bin/python`
运行 pytest/Ruff/build；导出也用系统 python3 成功。无新生产依赖或环境安装，不强制 .venv，允许兼容 conda。

```sh
PYTHONPATH=src python -m co_scientist_next.development_cases --case ALS-GOAL --mode fixed_materials
PYTHONPATH=src python -m co_scientist_next.development_cases --case R04 --mode fixed_materials
PYTHONPATH=src python -m co_scientist_next.development_cases --case R04 --mode open_retrieval
PYTHONPATH=src python -m pytest -q tests/next/test_development_cases.py
PYTHONPATH=src python -m pytest -q tests/next
python -m ruff check src/co_scientist_next tests/next
python -m ruff format --check src/co_scientist_next tests/next
```

| 检查 | 实际结果 |
|---|---|
| 新增数据读取/隔离/引用检查 | 28 passed，0 failed，0 skipped |
| 全部新系统工程/契约回归 | 80 passed，0 failed，0 skipped（原52 + 新28）；不是80项科学评测 |
| Ruff check/format | 通过；17个Python文件格式检查通过 |
| 实际附件ZIP比对 | ZIP哈希匹配，两个文件逐字节一致 |
| 原M00/W0文件完整性 | 既有完整性检查通过，原文状态未改 |
| 模型可见视图 | 8个输入视图×2种模式检查；无评审字段，固定/开放模式明确分离 |
| Wheel构建与隔离运行 | 构建通过；python -I仅从wheel导入数据CLI，显式--root指向案例checkout，成功导出R05 |
| Git空白检查 | 新编文件 staged检查通过；全量检查仅报告原附件Markdown四处行尾空格，按原样保留 |
| 原工作区保护 | 232个相关文件、差异、暂存区和status指纹与此前保护记录一致 |

输出见 [verification/w0-t3.txt](verification/w0-t3.txt)。外部来源访问是本轮人工核对行为，
不是应用已通过 LiteraturePort/M15 完成真实来源摄入的证明。

**未运行：** 真实M01/M02输出、付费模型、科学评分/通过率、真实开放检索评测、专家盲评、湿实验、
当前药物监管库核验、完整科学S01–S14/R01–R06执行、旧G3全套本地测试、浏览器、Python3.12本地测试。

## 待审阅及下一项编码任务

全部科学预期仍为 provisional，未有专家签名、独立共识或统计阈值。
待审阅：来源转述准确性与条件归属、给定假说Coverage、KIRA6靶点因果及新颖性边界、
材料访问限制、R06计数/数据关系、Goal/Candidate Ethics与R0的边界及适用安全政策。

提案已给出方法/Prompt草案、最小I/O、真实来源/模型接入M15所需记录及M12合法顺序。
现有固定序列 Scheduler 尚无 Ethics条件门，不能仅注册函数就宣称拒绝时不会生成候选。
建议下一项为 W0-T4：固定材料下 prepare_goal + Goal Ethics + 最小M12条件推进切片；
先保证 pass/reject/incomplete/技术失败和日志/恢复语义，Generation先保留未实施的显式后继边界，
不以替身候选冒充科学能力。具体验收条件见提案；仍需单独审查与授权，不在本轮自动启动。

## V6 手动阶段测试工作台（2026-11-06）

- PR #19 固定 head `256cc9e4f806b56ad58a664fdb4493a8dae978c3` 已复核4项CI成功、无冲突/阻断并合并；实际 main/merge `758bd4132a1792da01ab996b91d78711c494d6a2`。从该版本独立分支 `codex/v6-stage-workbench` 开发，新 PR 不合并。
- 用户 V6 附件原样保留及 SHA-256 来源记录；新工作台从实际 Project/Run 持久记录读取。V5青光眼完整静态资源作为隔离历史演示，真实 ALS 历史用独立只读入口。无静态候选数或审查结果注入实际研究。
- 后端：阅读 Chat / 生成 Responses / 审查 Responses 显式配置可并存，各任务冻结配置；凭据仅后端读取，缺失不回退。Goal前置仍为确定性开发适配器，创建Run需明确选择。增加内容版本绑定的独立人工意见及单Run原始记录导出，意见不进入科学输入。
- M12/M15：复用既有阶段、放行、成功回放、uncertain停止与同ID查询；不自动循环或恢复。不新增科学方法、M03/R1/Ranking/Evolution。长操作期间独立只读快照GET可用，单写锁拒绝并发POST，不引入任务框架。
- 页面：V6导航/科研阅读/文献统计/材料范围/政策和执行标识/长任务/笔记/导出，科研主张与技术记录分开。刷新、重启、设置及历史浏览不发供应商请求。
- 验证：新系统398 passed，失败0/跳过0；Ruff、Next所有JS语法、wheel构建通过。浏览器走通新植物问题的隔离夹具链、双模式候选、独立审查、笔记刷新/导出、第二研究隔离及历史比较；390px窄屏无整页横溢。细节与截图：`docs/workbench/verification/README.md`。
- 已启动 <http://127.0.0.1:8767/>，独立空阶段库，不写历史真实库；实际服务只做只读查看，真实模型请求0、真实文献请求0。原工作区232项改动及历史DB哈希保持。启动/人工评估路径：`docs/workbench/README.md`、`scripts/start_stage_workbench.sh`。
- 科学验证：`science_validated=false`。离线夹具不证明任意问题的科学相关性或模型质量；生产伦理政策、科学质量、用户科研评估未验证。旧G3全量/在线供应商检查未运行；历史交互未穷举所有组合。阶段库位于临时目录，长期保存需备份；服务仅用于本机单用户。

## PR #20 科研阅读与独立判断优化（2026-11-06）

- 远端复核PR #20仍Open，固定起点 `b1d357595780c389df263a7a56efb3014a18dbd3`，继续 `codex/v6-stage-workbench` 追加，保持未合并；原main基线 `758bd4132a1792da01ab996b91d78711c494d6a2`。
- 前端：候选摘要／四标签科学阅读／原始记录三级结构；机制、证据、假设、预测、证伪、P09/R0使用专用组件。当前候选内直接查看正式审查和保存独立人工意见；原文视图可绑定material_view意见，无目标或只读时明确不能保存。概览展示实际背景、候选主张和待解决问题，七项主导航保留汇总入口。
- 复用现有API/字段，无新数据字段、无后端改动，Store/M12/M15及科学Prompt/契约不变。只读浏览在长POST期间可用；409明确为本机写锁繁忙、不是模型失败，不自动重发；后端写锁完整保留。未来并发写意见需另评审。
- 真实ALS只读验收：P09真实模型+限定非生产用途pass；P10 proceed_to_R1、6项未知、8项R1核查、无达标阻断缺陷；逐条保留原文，未把ANXA11/SUN1独立人工初审问题冒充R0发现。R1未执行／能力未实现。
- 回归起始398 passed；最终403 passed（新增5项前端映射/DOM/隔离/409断连测试），失败0/跳过0。Ruff、全部Next JS语法、wheel/sdist通过。桌面及390px浏览器已验候选内意见保存/刷新、来源问题、兄弟候选与Run隔离、空新问题、V5比较和G0→G3回放；延迟夹具执行中GET刷新后两个任务仍仅两个ordinal=1 Attempt。截图、命令和限制见 `docs/workbench/reading-refinement/README.md`。
- 科学/历史保护：真实模型请求0、真实检索0；原工作区232项指纹及两历史DB SHA不变，科学原件和V5 HTML未改。science_validated=false。旧G3全量、在线供应商/检索和科学质量验收未运行，不实现M03/R1/Ranking/Evolution。


## V6 automatic research — 2026-11-07

PR #20 fixed head b93c1f5f50159cd61c205720cd95b6e2b267da57 was verified and
merged as 0e5600f55a54412e27d48b56fedf85de64305c5c; this slice starts there
on codex/v6-auto-research in an isolated worktree.

Backend/M12: persisted bounded Start, separate seed rounds, material snapshot reuse,
abstract relevance screening, traceable segments, real Goal adapter, existing P03–P10
composition, pass-only R0, pause/resume/stop and pre-send hard limits. Existing
uncertain records are untouched. OPEN isolation and P08 six-field contract retained.
Page: supplied Journey layout connected to persisted aggregation, views, candidates,
independent human notes and export. Policy maturity and execution mode are separate.
Service: http://127.0.0.1:8770/ with independent stage DB; started empty (0 attempts).

Final new-system regression: 413 passed in 61.76s, no failed/skipped tests. Ruff,
JavaScript syntax and wheel build passed. Desktop and 390px mobile viewport browser
checks passed; downloaded JSON parsed with persisted human assessment. Original
232-file workspace fingerprint and both historical database hashes unchanged.
Real model requests 0; real search requests 0; scientific quality NOT validated.
No R1/M03/Ranking/Evolution. Physical mobile device and real scientific end-to-end
quality checks: 未运行. Details, limits, commands and evidence: docs/workbench/automatic/.
science_validated=false. New PR remains unmerged.
