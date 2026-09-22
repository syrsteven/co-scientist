# 模型目录与参考价格

核验日期：2026-09-17。这是官方公开报价快照，不是账户授权、适配兼容性或真实账单证明。价格会变化；历史 Run 不因目录更新而修改。

## 公开模型与基础报价

每百万 tokens；输入指非缓存输入。USD 与 CNY 不直接相加。未覆盖 Batch、Fast/Priority、地区附加费、缓存存储/写入及搜索等工具收费。完整条件在设置的价格卡片和官方来源中查看。

| 供应商 | API model ID | 适用基础条件 | 输入 | 输出 | 币种 |
|---|---|---|---:|---:|---|
| OpenAI | `gpt-6-astra` | Standard short context | 10 | 50 | USD |
| OpenAI | `gpt-5.6-sol` | Standard short context，当前优惠 | 4 | 20 | USD |
| OpenAI | `gpt-5.6-terra` | Standard short context | 2 | 12 | USD |
| OpenAI | `gpt-5.6-luna` | Standard short context | 0.2 | 1.2 | USD |
| OpenAI | `gpt-5.5` | Standard，<272K context | 5 | 30 | USD |
| DeepSeek | `deepseek-flash` | 谷时 / 峰时 | 0.15 / 0.30 | 0.60 / 1.20 | USD |
| DeepSeek | `deepseek-v4-pro` | 谷时 / 峰时 | 0.66 / 1.32 | 1.98 / 3.96 | USD |
| Qwen | `qwen3.8-max` | 北京，≤1M 输入 | 12 | 36 | CNY |
| Qwen | `qwen3.7-plus` | 北京，≤256K 输入，标价 | 2 | 8 | CNY |
| Qwen | `qwen3.8-flash` | 北京，≤1M 输入 | 0.8 | 2.7 | CNY |
| Qwen | `qwen3.7-flash` | 北京，≤32K 输入 | 0.2 | 0.8 | CNY |
| Gemini | `gemini-3.8-flash` | Standard 付费，至 2026-12-31 | 0.75 | 3.75 | USD |
| Gemini | `gemini-3.7-flash` | 同上 | 0.75 | 3.75 | USD |
| Gemini | `gemini-3.5-flash-lite` | Standard 付费文本 | 0.3 | 2.5 | USD |
| Gemini | `gemini-3.1-pro-preview` | Preview，输入≤200K | 2 | 12 | USD |
| Claude | `claude-fable-5-1` | Standard；仅展示，适配待验证 | 10 | 50 | USD |
| Claude | `claude-opus-5` | Standard | 5 | 25 | USD |
| Claude | `claude-sonnet-5` | Standard | 2 | 10 | USD |
| Claude | `claude-haiku-4-5-20251001` | Standard | 1 | 5 | USD |

来源：[OpenAI 模型目录](https://developers.openai.com/api/docs/models)、[OpenAI 定价](https://developers.openai.com/api/docs/pricing)；[DeepSeek 定价与型号](https://api-docs.deepseek.com/quick_start/pricing)；[阿里云百炼定价](https://help.aliyun.com/zh/model-studio/model-pricing)；[Gemini 定价](https://ai.google.dev/gemini-api/docs/pricing)；[Claude 型号](https://platform.claude.com/docs/en/models/overview)、[Claude 定价](https://platform.claude.com/docs/en/about-claude/pricing)。

重要条件：

- OpenAI 长上下文输入/输出分别为 Astra 20/75、Sol 8/30、Terra 4/18、Luna 0.4/1.8、GPT-5.5 10/45；缓存命中价另列。Sol 当前优惠至少至 2026-11-21。不要将 ChatGPT 订阅或 Codex 额度当 API 额度。
- DeepSeek 的 `deepseek-flash` 是当前 V4.1 Flash。工作日 UTC 01:00–04:00、06:00–10:00 是峰时。旧 `deepseek-v4-flash` 别名不能锁定旧版本；旧搜索摘要中的报价可能失效，本次直接核对了官方页面正文。
- Qwen 当前 adapter 使用北京 endpoint，故列人民币北京价。Plus 超过 256K 输入时为 6/24；官方另有未列终止日期的限时八折，本目录不以折扣代替标价。3.7 Flash 超过 32K 至 256K 为 0.6/2.4，再到 1M 为 1.2/4.8。
- Gemini 3.8/3.7 Flash 自 2027-01-01 为 1.5/7.5，当前缓存命中 0.075、之后 0.15；输出含思考 tokens。3.1 Pro Preview 超过 200K 为 4/18；缓存存储另计。
- Claude Fable 5.1 使用 always-on adaptive thinking，当前 adapter 未验证其必要配置，不放入可直接选择的快捷项。其余也只是已接入供应商，不代表此次已对每个新型号做真实调用验证。

## 在项目中使用

设置 → 模型连接 → 选择供应商 → 选择模型，或填写精确自定义 ID → 校验 → 保存新配置 → 在已配置 API key 的终端执行生成的命令。

目录不会替换已有 Run 的冻结模型；选择型号本身不发送请求。自定义型号不在目录时显示“未匹配到参考报价”，不把价格当作零。密钥只通过运行进程环境变量传递，网页不存储密钥。

当前一个 Run 仍固定一个模型。角色级多模型路由和单/多模型实验平台尚未实现，不能通过下拉菜单模拟合作模式。开始跨供应商研究比较前，请先解决[审计报告](reports/2026-09-17-paper-alignment-audit.md)中的 scientific_context、提示词和评估输入问题。

## 为什么成本页面仍可能显示未定价

设置页是参考价；成本页面是持久化调用账本。当前真实调用缺少可验证的完整价格映射，不能把新目录价格倒灌为历史实际成本。正确后续实现应冻结模型/地区/服务层级/时间档/缓存类别的价格版本，绑定真实 usage，区分估算、供应商账单和未定价。USD 预算在账目未定价时不是可靠账单硬限额。

维护位置：`src/co_scientist/application/model_catalog.py`。更新时同时核对官方 ID、地区、单位、上下文阶梯、缓存、思考计费及日期，修改目录测试；未知兼容性仍标记未验证。
