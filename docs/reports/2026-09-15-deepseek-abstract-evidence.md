# DeepSeek 晶状体案例：摘要证据验证

运行 ID：`lens-deepseek-20260915-004`，模型：`deepseek-flash`。

## 已完成的真实流程

新运行完成了 3 个候选生成、PubMed ESearch、EFetch 摘要获取、3 次 initial review 和 3 次 full review。9 个外部调用均为 `domain_result_applied`，无结构解析失败，也没有重复付费重试。预置的 2 个 benchmark anchors 不计入 3 个模型生成候选。

检索返回 10 个文献记录，其中 9 篇有摘要，1 篇只有题录。查询使用 Title/Abstract 中的晶状体短语，按 relevance 排序。摘要保留原始 XML、文本段落标签和来源 ID。没有获取或宣称获取全文。

模型用量：7 次 DeepSeek 调用，28,643 input tokens + 18,000 output tokens = **46,643 tokens**。另有 2 次 PubMed 调用。未获得实际账单金额。

## 当前结果不是全流程成功

状态：`needs_attention`；原因：`review_requires_scientist_input`；当前事件序号 64。尚未进入 Tournament，也没有最终科学综合或论文性能验证。

| 候选 | 模型 full review | 实际准入情况 |
| --- | --- | --- |
| H1：手术/囊袋构型优先 | reject；not_novel | 新颖性与 critical_flaws 阻塞 |
| H2：宿主年龄优先 | pass；partially_novel | critical_flaws 阻塞，表面 pass 不等于系统准入 |
| H3：早期细胞状态优先 | pass；partially_novel | critical_flaws 阻塞，表面 pass 不等于系统准入 |

以上是模型评审和系统契约判断，未经过独立科学家验证。H1 被模型认为与已有再生策略重合；H2/H3 的评审指出因果优先性、适用物种和时间窗口等方面仍有未解决的问题。不能把这些文字直接当作科学定论。

调度器已修正为按现有 admission reducer 筛选候选：个别拒绝不再阻塞其他真正合格的候选。但本批三个候选都存在准入阻塞，合格数为 0，小于所需的 2。没有删除模型列出的缺陷，也没有降低科学门槛。

## 代码与验证

- 最终全离线回归：**670 passed，3 online deselected**；Ruff、mypy（71 source files）和 diff check 通过。
- 可冻结配置：`literature_content: abstracts`、`literature_sort: relevance`、主题限定查询。
- EFetch XML 先保存再解析，拒绝实体声明、错误 envelope、重复或无效 PMID；缺失摘要保留为 metadata。
- full review 明确引用、新颖性、证据不足和 critical_flaws 的输出要求；对新任务明确“关键缺陷”不同于一般局限性。
- 新增摘要解析、旧 metadata 兼容、raw 来源绑定、初审顺序、错误输出暂停，以及拒绝/关键缺陷/无新颖性/安全阻塞候选隔离测试。
- EFetch 接入依据：[NCBI E-utilities 文档](https://www.ncbi.nlm.nih.gov/books/NBK25499/)。

本地完整导出：项目根目录 `lens-deepseek-20260915-004-export/`。包含不可变任务、来源、原始响应、事件、候选和成本记录，目录被 Git 忽略。

## 下一步

应将这些评审反馈送入有预算约束的 Evolution，生成新的、范围更明确的可证伪假设，再完整经过初审、文献评审和准入；旧候选和拒绝记录保持不变。还需区分“致命因果缺陷”与“尚待实验检验的一般局限性”，由明确的评审契约和科学家判断支撑，不能为了跑通而清空缺陷。

当前摘要检索仍是 run-level 搜索，不是针对每项机制的系统综述；全文获取、Evolution 自动闭环和外部科学评测仍需后续实施。
