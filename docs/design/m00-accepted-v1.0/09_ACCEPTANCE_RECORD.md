# M00 Final Design Acceptance Record

**验收结论：** `design_accepted`（已接受设计基线，不是代码/科学结果验收）  
**正式版本：** `M00-ARCH-v1.0`  
**验收日期：** 2026-11-01  
**验收依据：** 用户明确回复「接受目前M00材料」，适用于 M00 Phase 3 RC1 全量文件及随后 RC2 四文件最小修订。  
**最后一次仓库核实：** 2026-10-31，main 为 `7313ca032e4f5f0c84578523e0f5639ad038e7af`；验收时未重新拉取仓库。  

## 本次确定的设计内容

- 统一新系统；旧G3只为历史科学/算法对照，不承担正式运行兼容义务。
- 科学核查路径中R2普通缺口经M03–M06补充并回R2；R3仅由R2针对高影响问题触发并回R2。
- 同一入场候选跨Match使用相同核心科学输入（主要支持/重要反证/关键缺口/FinalReflection），只允许对称增补冻结材料，并记录真实模型输入；Ranking不发起核查。
- Goal Ethics运行顺序为M01.prepare_goal→M02.screen_goal→M01.generate_hypotheses→M02.candidate_ethics/R0；开发依赖不等于调用顺序。
- M13可消费M03/M06/M07/M10/M11成果但非阻断。
- 正常Run单一Epoch；TrueSkill只由有效决定性Match更新；父代只从已准入且达父代资格者挑选，终局在正式资格池中选择最高μ，可无Winner；不进行终局R3。

## 受控文档与交付来源

- `01_ARCHITECTURE_BASELINE.md`、`02_GLOBAL_DECISION_LOG.md`、`03_INTERFACE_OWNERSHIP_MAP.md`、`04_MODULE_DEPENDENCY_MAP.md`：RC2 四份修订内容，验收时仅将状态/版本标识升级至 accepted。
- 其余主动设计材料沿用 RC1，README、摘要、Handoff、验收清单中仅同步本次接受与RC2修订含义；三张受RC2影响的独立Mermaid图源同步内嵌图和R2普通补核查语义。
- `reference/`保留历史草案与源材料，不能取代正式 v1.0 设计。
- 文件完整性和SHA-256记录于`manifest.json`，静态检查摘要于`VALIDATION_REPORT.md`。

## 不构成授权或验收的事项

- 不代表M00已实施代码、GitHub提交、Pull Request、研究Run、科学专家评测或旧G3对照实验。
- 不自动授权M01/M09a/M11a/M14a/M15a/M20a生产代码实施；模块需遵守独立设计审批和真实验收。
- Claim粒度、检索/证据质量标准、R3风险科学阈值、M10资格/比较配额、M12停止条件等模块问题仍归相应模块和M20研究决定。
