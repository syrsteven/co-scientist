# Release 来源与差异

## 科研功能来源

- 成功 Run：`ideation-dev-g3-continuous-r2-20261014-836f244e5f7b4f0082c2381c85996d94`
- 开发 HEAD：`c2ddbda03f84d5a52f46b47d942b2cce710c919b`
- 实际开发 tracked diff SHA：`15de510edd71a4ade0150e8c6782b261ced81b4b7860feda6118db52d79f6dd5`
- 工作树 inventory SHA：`84d895c6aece9fc5ebc61a280e896ce427b8618ca80709064f29e3fcc29a7716`
- 原 profile SHA：`e58a964e3ad806d791702acb0991c09532c7307db3b625dc5ebd4e9fdc9cca8a`
- P1 SHA：`82d9d972ac8c4281925110fde200d0ccca25a5e21c6fd9cd7accfdcbfe82e12d`
- 冻结 Spec SHA：`000103561ed701648b3ca9b43521e174571cb4b638f6280263f55f5f6ff59874`
- 冻结 B2 Contract SHA：`4f898ba17b08221d0c641744f9e813ff3c417961fdba35c076c727a024081aca`

真实 R2 为 COMPLETE / FINAL_WINNER，9候选（1 root重复不补位）、12决定性matches、
24 posterior投影、5 crossover/1 mutation；Sol4/Flash47、PubMed20、总HTTP71。
该历史结果只是来源证据，未复制其数据库/raw/科学authority，也不复用其授权。

## 有选择的提取

不是 git archive HEAD：保留实际工作树修改与必需 untracked 包资源。
原始文件清单/hash见 `release-source-provenance.json`。
保留完整科研运行链、依赖schema、迁移包、legacy reader、prompts和skill资源。
排除 benchmark、历史独立探针/优化/ESearch smoke runner、`.planning`、历史运行/数据库/raw、
HOLDOUT、Pilot/M2数据、个人配置、凭据、缓存和原虚拟环境。
被核心 import 的旧纯类型/validation仍保留，不为减小目录破坏加载或replay。

## 必要部署修改

1. `runtime/context_planning.py`：支持版本/hash-bound包资源URI；原非URI加载规则不变。
2. `runtime/single_root.py`：PubMed联系邮箱由冻结operator配置接入。
3. 包元数据与CLI入口：增加`co_scientist.release`薄服务/命令、synthetic MockTransport。
4. profile两个tokenizer路径改为包/安装资源URI，科研参数、模型和prompt逐项不变。
5. 显式授权、独立Run目录、文件锁、停止和不可覆盖的版本化导出快照。

`deployment-changes.diff` 记录已有文件的部署差异；新增薄封装见源码清单。
diff中旧tokenizer绝对路径的开发目录前缀匿名化为`<DEVELOPMENT_REPO>`，
避免分发个人目录信息；原文件的逐字节身份以provenance中的SHA为准。
算法、随机化、R/P/配额、TrueSkill、UCB、演化、terminal barrier与native winner未重写。
新RunID/资源配置hash会改变随机身份，不保证重现历史候选文本或同一随机结果。

## 第三方资源

DeepSeek V41 JSON SHA：`81f64d1248a68ce3663e07ab3ee48b851e5df0e32d27cb98e4c9a268151e8d99`。
官方recipe的tokenizer目录采用MIT许可；许可原文随包。
核对参考 revision：`6821d6ad3681a4b137b066b76094fa82ebd0a380`，原始开发获取revision未记录，不补造。
来源：[DeepSeek V41说明](https://github.com/deepseek-ai/deepseek-recipe/tree/main/static/tokenizers/v41)。

OpenAI BPE SHA：`446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`。
tiktoken代码MIT，但未独立确认托管数据的分发许可，因此不重新分发BPE数据；
使用明确安装阶段从[官方文件](https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken)
获取/hash验证，或用户本地导入。运行期禁止自动下载。
精确版本、资源身份见`requirements.lock`和`resources/tokenizers.json`。

## 已知局限

新CLI完整离线验证，尚未通过该Release入口调用真实API；不能把历史成功自动转为新入口的live认证。
价格/模型权限定期变化，需operator确认后新授权。无机构伦理审批、生产Web服务或多租户鉴权。
macOS实测；Linux架构兼容但未实机验证；Windows文件锁暂不支持。
本包源码未发现独立许可证，所有者应决定授权分发条款，不擅自声明MIT。
本轮无付费API/PubMed调用，原开发仓库与历史记录保持不变。
