# Workbench v0.4 实施验收

基准：`21213ed0d7863547aff5c081e75bfb0c4f875ec6`，分支 `codex/workbench-v0.4-backend`。
不修改 `src/co_scientist/`、Native Profile、Prompt、schema、历史 Run 或 canonical；未 push。

## 里程碑

- M1：完成。真实 CoreRunner + MockTransport，经 HTTP/浏览器创建、授权、后台执行、重连、结果与原生导出。
- M2：接口和离线假密钥验证完成。默认禁止 LIVE dispatch；未验证真实账户/价格/外部网络，不能称 live-certified。
- M3：默认配置的版本化 builder、字段保留和 fail-closed 兼容性检查完成；**自定义执行未完成、禁止启动**。

## 对交接包 ACCEPTANCE.md 的证据

| ID | 结果 | 实际证据 / 限制 |
|---|---|---|
| A01 | PASS | loopback-only CLI；浏览器访问五页；无 CDN/外部请求；CSP、Host 与 Origin 检查 |
| A02 | PASS | 浏览器完整 Mock G0→G3；COMPLETE/FINAL_WINNER，10 候选及五项 Trace |
| A03 | PASS | API Mock 使用空凭据；驱动主动拒绝真实 socket；pytest 同样拒绝 socket |
| A04 | PASS | prepared events=[]；export 409；Native runtime/DB 不创建 |
| A05 | PASS | 关闭创建页、重启 HTTP 服务、重开同 Run；原独立驱动继续至终局 |
| A06 | PASS | 重复 start 返回同一 PID；OS 锁防双驱动；终态 resume 不增加事件 |
| A07 | PASS | SSE Last-Event-ID 从后续 sequence 补发；观察层不应用科学事件 |
| A08 | PASS | Native replay；μ 递减、σ 与 decisive 保留；浏览器实际观察到 pending 候选 |
| A09 | PASS | 完整原文/预测/证伪/Ethics/Reflection/Ranking/谱系；Run 级原生来源事实明确标注，未编造逐 Claim 支持 |
| A10 | PASS | 原生 stop 得到 PARTIAL，未显示正式 winner；正式结果需三项 Native barrier 条件 |
| A11 | PASS | stop 非 pause；终态零派发；中断 Native checkpoint 恢复及重建 Web 会话 |
| A12 | PASS | 一致性 RunService.export 和 ZIP；busy 409 后可重新生成；原 Native 并发/幂等测试仍通过 |
| A13 | PASS | 假密钥保存/覆盖/清除、错误不回显、刷新输入清空、数据库/Run/导出无 sentinel、服务重启丢失 |
| A14 | PASS | 假 LIVE Run 创建时冻结邮箱；改变设置不改变原 plan；无效邮箱 422 |
| A15 | PASS（离线边界） | 缺确认/风险/价格拒绝；跨 Run 授权拒绝；默认 LIVE start 403；未执行真实 LIVE |
| A16 | PASS（目录与拒绝） | 默认角色标为已适配但账户未验证，其他模型标未验证并拒绝；无在线账户探测 |
| A17 | 安全阻断 | 非默认组合可存草稿但预检拒绝；不冒称已完成自定义执行 |
| A18 | PASS | 逻辑 ID 与固定 Data Root；拒绝非法 ID/任意路径/多余字段；下载受控 |
| A19 | PASS（模拟身份） | 测试中模拟旧 code identity，恢复/导出 409；未操作用户历史 Run |
| A20 | PASS | Python 3.12 全套离线回归、API tests、真实 Chromium/loopback 完整 Mock；没有科学网络请求 |

## 实测结果

- 全离线 suite：126 passed / 0 failed，370.36s（该快照含前 5 个 Web tests）。
- 最后只读算子/来源投影修正后：Web focused 5 passed，148.81s。
- 补充凭据覆盖/清除/无会话测试：1 passed / 5 deselected，1.53s。
- 安装当前源码新构建的 wheel 后，API/准备态/假凭据/终止/导出 smoke：5 passed / 1 deselected，10.46s；CLI help 与六个前端资源正常。
- 最终只读浏览器检查另验证 prepared 取消后可重新打开授权，以及本地 Trace 导入不会被标成服务器运行。
- Ruff（新增 Web 代码与测试）、targeted mypy 8 modules、compile、JS syntax、diff check 通过。
- 新增可复现浏览器验收 `tests/web_browser.py`；真实重启 HTTP 服务后同一原生驱动继续。
- 远程 CI 尚未运行；已接入原有 3.11/3.12 matrix，浏览器步骤在 3.12 上运行。

以上数字不拼成“127 项最终快照全套通过”：最后的只读 UI/投影修正由 focused/API/浏览器复验覆盖。
中间发现并修正了测试 helper 重复打开 httpx client、CSP 不允许测试 eval、启动等待和 provider 名称断言错误。
没有放宽生产 CSP、科学输出校验或 Native 授权/预算保护。

## 持久 Mock 证据

Run：`ideation-g3-20261022-aa5e0414bc554c1f8f7a257ad1510152`

- COMPLETE / FINAL_WINNER；winner `hyp-offspring-g1-slot-0`。
- G0/G1/G2/G3 候选：4/2/2/2；13 decisive matches、26 posterior projections、396 events。
- 6 次 reproduction（5 crossover、1 mutation），未强制算子抽样。
- 52 次模拟 model calls、1 次 Native root-retrieval call；真实科学 HTTP = 0。
- 模拟账务 0.002196 USD、终局活动预留 0；不是实际付费或科学证据。
- 目录：`/Users/lemintea/Documents/co-scientist-workbench-acceptance-20261022/`。
- `data/runs/<run-id>/exports/` 为原生五文件；`native-trace.zip` 为 Web 下载结果。
- `browser-report.json`、最终 desktop/mobile/results 截图及独立只读检查保留；原 Run 路径未搬迁。

## 仍需处理

1. M3 自定义模型/代数/预算的实际调度和完整 Mock 兼容矩阵；目前明确拒绝，不自动 fallback。
2. 真实 LIVE 账号、实时价格和网络行为未在本任务验证，需要独立授权。
3. 单用户 POSIX 本地部署；不提供远程认证、多 worker、Windows 或 OS 凭据库。
4. Native 恢复语义未重写；并未穷举全部 OS kill/crash 窗口。Web 故障使用独立 attention 状态并保留 Native checkpoint。
5. 原发行校验清单保持历史身份；本分支对 README/打包元数据的修改不冒称通过旧的整目录发行 hash。
