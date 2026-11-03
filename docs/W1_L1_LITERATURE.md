# W1-L1：人工查询与真实文献获取

本轮只实现获取切片，不是完整W1-L，不是科学验收。
M00仍Accepted，W0/W1原包仍Proposed；W0-T4用户接受修订不变。

## 启动和页面操作

```sh
cd /private/tmp/co-scientist-w1-l1
PYTHONPATH=src python -m co_scientist_next.workspace \
  --db runs/w1-l1-live.sqlite --port 8785 --development-test --public-literature
```

打开 `http://127.0.0.1:8785/`。交付时已运行。
可直接打开已验证固定Run：
`http://127.0.0.1:8785/#run=9b5abf8a5ccd496d8c45ff9a6666b20e`。
使用已有兼容Python3.11/3.12或conda，无新生产依赖/真实模型密钥。

- 保存简报、显式选择开发政策、创建并执行Goal切片。
- 只有保存的completed pass开放文献操作；缺政策/澄清/reject等不会补pass。
- 人工填写Europe PMC查询，显式检索/下一页；逐篇点“获取摘要”或“尝试获取开放全文”。
- 查看实际来源、访问层级、文本、请求、数量、游标、限制和错误。原始筛查JSON折叠，主视图展示通过/拒绝和理由。
- 草稿、固定Goal和每次查询历史分开；改查询不改已保存Goal/旧检索。刷新、启动、GET仅读取，不自动执行或恢复。
- `--development-test`只启用确定性Goal适配器，`--public-literature`单独启用真实公共HTTP；两个开关都需显式传入。
  不传public开关拒绝获取。不传development开关不会伪造真实Goal pass。
- 页面明确显示“目标筛查为测试结果，文献获取为真实请求”。材料全部“已获取、尚未解读”。

查询示例（人工编写，非Agent规划）：

```text
"amyotrophic lateral sclerosis" AND (nucleoporin OR "nuclear pore")
```

这是从既有ALS-GOAL概念出发的宽查询，不预选具体分子，不是全面科学检索策略。
原Goal包含磷酸化条件，原样保存；宽查询没有覆盖所有条件，不能声称完整覆盖或文献相关性已评价。
原Goal采用既有开发者转述（P-03 Note10.1 / PDF实体p70），不是新造病例或原文逐字引用。

## 选择和官方依据

选Europe PMC公共REST：同一来源提供生物医学元数据、结构化摘要、OA子集全文XML，不需API密钥。
实际固定域名：`https://www.ebi.ac.uk/europepmc/webservices/rest/`。

| 功能 | 实际请求和范围 |
|---|---|
| search | `/search`，query原样传入，`resultType=lite`，JSON，synonym=false，relevance默认顺序，cursorMark，单页1–20条 |
| fetch metadata/abstract | `/article/{source}/{id}?resultType=core&format=json`，按来源身份取单篇；校验返回source/id一致 |
| fetch full text | core明确给出OA PMCID时请求 `/{PMCID}/fullTextXML`；验证article/body和PMCID，拒绝空正文/abstract-only文档冒充全文 |
| supplementary | 未实现；XML有链接/hasSuppl不等于取得附件；请求时明确不完整，保留已取得元数据或摘要 |

官方资料（2026-11-03核对）：
[REST说明](https://dev.europepmc.org/RestfulWebService)、
[官方参考手册](https://dev.europepmc.org/docs/EBI_Europe_PMC_Web_Service_Reference.pdf)（search/cursor、getFullTextXML章节）、
[官方发布记录](https://dev.europepmc.org/docs/Europe_PMC_RESTful_Release_Notes.pdf)（6.8新增article ID接口）。
主站文档曾403，dev官方镜像可读；尝试swagger.json返回404。没有用第三方客户端作为运行依赖。
身份接口`result`为单对象，search为`resultList.result`数组，已以实际响应分别核实。

原LiteraturePort保持不变，适配器实现search/fetch；不在接口中放检索策略或科学评价。
来源以`epmc:source:id`标识，同一页重复ID去重，原始重复行保留。
不按标题相似/DOI差异推断同一研究、配套报道或独立证据；仅保留provider显式versionList关系及原始值，标为未独立核验。
MED、PPR摘要及MED对应OA全文已实测；其他来源类型/版本关系未逐一实测。

## M15持久化、状态和恢复

仅新增`literature_actions`小表，把稳定request_id与已有Run/Task关联。
M12只增加两个命名操作search/fetch，追加人工请求任务；不建立通用工作流框架。
每次新动作原子保存计划追加、Task和请求；请求/结果/材料保存在SQLite，固定Goal和原BriefRevision不改。
执行前再次核对已应用的Goal Ethics结果、政策引用与Goal身份；不由M12判断安全或科学相关性。
所有获取结果停在literature_acquired_unread/incomplete/failed；这不是科研完成，未创建Generation等任务。

- 每次HTTP发送都经TaskCalls：保存最终URL/参数/请求头、Attempt关系、开始/完成UTC时间、响应状态/头、base64原始字节和SHA-256。
- 原始响应先保存，解析结果/实际文本后应用；摘要保留原字段字节并生成纯文本表示，全文保留完整XML字节及机械展平文本。
  文本定位指向该Task下`attempt:metadata`的`result.abstractText`或`attempt:fulltext`的`/article`；Attempt ID可从同一动作查询。
- 8MB上限是单响应技术限制：超限仅存前缀且明确truncated/incomplete，不标全文。图像、二进制附件和外链未下载；这不是PDF排版读取器。
- 不自动重试、不自动跟随重定向；HTTP错误及响应体如实保存，不能写成空检索。超时/丢响应保持uncertain/blocked。
- succeeded表示该次HTTP/解析获取操作成功，不等于查询覆盖完成；scope_complete/next_cursor独立。未知token/费用保留null，每次有响应的HTTP工具调用记录tool_units=1。
- 相同request_id和内容重复提交返回同一动作，不重新执行；同ID不同内容拒绝。新ID表示明确的新人工动作，保留旧记录。
- 成功Attempt回放不重新发送；跨进程保存成功但结果未应用的恢复已测试。刷新不恢复。
- 对ready/running动作，页面可显式恢复；未收响应会转为不确定并阻断，不默认安全重发。
  blocked动作的核实/重试授权沿用后端`Store.authorize_uncertain_retry`与`retry_task`，本页不提供无条件重发入口。
  技术已失败/获取不完整的已保存动作，可由用户新建显式动作重试，不能覆盖既有结果。

单进程、单数据库运行者、loopback同源页面；无远程部署/多用户认证。

## 实际真实请求证据

[浏览器报告](verification/w1-l1/browser.json)；
[主要请求/材料证据gzip JSON](verification/w1-l1/public-acquisition.json.gz)；
[初期接入失败证据](verification/w1-l1/diagnostic-acquisition.json.gz)。
这是实际保存的公共API响应/材料，不是测试夹具，也不意味着应用已经模型阅读。

主验收Run `9b5abf8a5ccd496d8c45ff9a6666b20e`，共5次显式动作、6次真实HTTP发送：

1. ALS概念宽查询第一页面5条元数据，provider报告1781，分页未穷尽。
2. 返回的预印本`PPR1217875`获取core摘要2746字符；[来源](https://europepmc.org/article/PPR/PPR1217875)。
   本轮没有把它认定为经同行评议或与任何正式版独立。
3. 返回的`MED:42437963`获取core与`PMC13357693`全文XML；机械展平113989字符，
   [来源](https://europepmc.org/article/MED/42437963)。文献类型是review，取得不表示验证了其主张或构成独立实验证据。
   provider license=`cc by-nc-nd`，原XML含许可信息；记录不新增再授权，图像/补充未取得。
4. 人工点击第二页，再取5条元数据，仍有后继cursor，不宣称文献穷尽。
5. 明确不存在的工程ID查询，成功0条且范围完成；只证明该人工测试查询为空，不证明ALS没有证据。

初期诊断另有4次真实HTTP（1次概念检索、2次旧EXT_ID身份lookup空记录、1次新article响应形状未匹配）。
原响应/失败未删除；最终改为article身份接口并按单对象解析。不存在底层隐藏自动重试。
合计10次实际文献HTTP发送，均有M15 Attempt；官方文档读取另计，不是应用科研请求。

[页面](verification/w1-l1/workspace.png)、[刷新后](verification/w1-l1/after-refresh.png)、
[移动](verification/w1-l1/mobile.png)。刷新新增POST=0，历史逐项相同，无JS错误；截图后续以GET读取同一真实记录更新布局。

解包核查：

```sh
python - <<'PY'
import gzip,json,base64,hashlib
with gzip.open('docs/verification/w1-l1/public-acquisition.json.gz','rt') as f: data=json.load(f)
for a in data['attempts']:
    r=a['response']; assert hashlib.sha256(base64.b64decode(r['body_base64'])).hexdigest()==r['sha256']
    print(a['id'],r['status_code'],a['request']['url'])
PY
```

## 检查和未验证

```sh
PYTHONPATH=src python -m pytest -q -s tests/next
python -m ruff check src/co_scientist_next tests/next scripts/w1_l1_browser.py
python -m ruff format --check src/co_scientist_next tests/next scripts/w1_l1_browser.py
node --check src/co_scientist_next/frontend/app.js
python -m build --wheel --no-isolation
# 可选，另装Playwright及Chromium；会明确发出少量真实公共请求
python scripts/w1_l1_browser.py --url http://127.0.0.1:8785 --evidence /tmp/w1-l1-live-evidence
```

离线fixture文件`tests/next/fixtures/europepmc_development.json`全部虚构，含明确标识；不在生产页面导入。
离线测试与上面真实证据分别记录。没有付费模型调用、自动查询、模型阅读、知识图谱、seed readiness、
候选生成、科学相关性/证据质量/独立性判断；`science_validated=false`，不标完整W1-L或科学验收。
