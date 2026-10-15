# 配置

唯一随包正式 profile：`co_scientist.release/resources/g3.yaml`。
它源自 `ideation_performance_dev_g3_continuous_evolution_v2.yaml`，仅 tokenizer 文件位置
改为 `resource:` URI。参数在 create 时由原 typed resolver 冻结进 Run manifest，
下游 task 使用冻结的有效配置；resume 不读取当前 YAML 获取默认值。

| 角色 | Provider/API/模型 | 配置 |
| --- | --- | --- |
| Root Generation | OpenAI Responses / gpt-6.1-sol | medium、P1、strict JSON Schema、无 temperature |
| Directive/Candidate Ethics | DeepSeek Chat Completions / deepseek-flash | 原冻结角色配置 |
| Query Planning / Source Review | DeepSeek Flash | root_literature_review@0.4.0，精确 phase |
| Reflection / Ranking / Evolution | DeepSeek Flash | 原冻结 prompt/schema 与角色容量 |

baseline 中保留的 Generation temperature=1.6 不覆盖性能版 Responses request。
新部署仍显式标记性能增强 G3 DEV，不冒用严格 G10 复现身份。
Evolution 模型侧 `evolution-per-parent-output-v1` 要求 Mutation 1 scientific parent/1 contribution，
Crossover 2 distinct parents/2 contributions；本地完整 domain validation 保留。
结构化重试反馈为 `bounded-schema-diagnostics-v2`。

运行环境变量：

- `OPENAI_API_KEY`、`DEEPSEEK_API_KEY`：只提供凭据。
- `CO_SCIENTIST_PUBMED_EMAIL`：创建时冻结，恢复继续使用原联系方式。
- `CO_SCIENTIST_RESOURCE_DIR`：安装过且 hash-valid 的 OpenAI BPE 目录。

模型/接口、thinking、output budget、context window、timeout、response cap、pricing
使用 profile 中的原有 versioned contracts；不从凭据环境静默改变模型。
tokenizer 是 offline DeepSeek V41 + tiktoken0.14.0 显式编码，校准余量保留。
动态 output 和 bounded retries 同时受上下文、提供商最大输出、reservation 和 Run envelope 限制。
最多 logical task 3 attempts；共享新增重试24、unknown-delivery pure-LLM最多1次新attempt。

预算：保守规划 $54.1303296，风险上限 $60，watchdog7200秒；模型143（初始119）、
Sol24/Flash135共享总数，PubMed48、HTTP191。未知费用保留 reservation。
冻结 pricing 是历史适用 snapshot，不声称永远有效；真实授权前须核对最新账户/价格。
若不再适用，应发布新 opt-in profile/版本并重新创建 Run，不重写历史费用。

源码包 `requirements.lock` 锁定实测依赖版本；资源清单 `tokenizers.json` 锁定 SHA。
code identity 包括包内源码、profile、prompt 和 schema。恢复要求原 identity 不变。
