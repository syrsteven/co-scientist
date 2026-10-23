# Workbench 与本地 API

正式入口是 `co-scientist-web`（FastAPI + 随包静态前端），不是未接线的静态演示。
只监听 127.0.0.1，默认禁止 LIVE；无跨域、多用户鉴权或公网部署支持。
前端使用同源 session Cookie、CSRF 和 Host/Origin 校验，不接受任意磁盘路径/命令。
密钥经本地后端内存处理，不回显或写入日志；后台驱动通过私有 stdin 接收。

## 已实现的 `/api/v1` 接口

| 功能 | 接口 |
| --- | --- |
| 会话与健康 | session、health |
| 项目/草稿 | projects GET/POST、projects/{id} GET/PATCH；drafts GET/POST、drafts/{id} PATCH |
| 配置 | config/defaults、config/models、config/preflight |
| 设置 | settings/status、settings/credentials/{provider} PUT/DELETE、settings/pubmed PUT/DELETE、settings/validation POST |
| 创建/授权/执行 | runs GET/POST、runs/{id}/authorize/start/stop/resume POST |
| 只读监控 | runs/{id}/status、events、stream、monitor GET |
| 科研详情 | leaderboard、candidates/{id}、lineage、rankings GET（Run 路径下） |
| 导出 | runs/{id}/trace GET、exports POST、exports/{id} GET（ZIP） |

见 `src/co_scientist_web/app.py` 中实际路由及类型校验；`tests/test_web.py` 和可靠性测试提供调用示例。
账户 validation 只检查本地配置状态，不做在线权限探测。自定义组合未验证时明确拒绝，不隐式回退。

`monitor?after=<sequence>` 分页返回最多 1000 条已提交原生事件；SSE 支持 sequence 续传。
默认实时监控不生成完整 Trace，不扫描全部 artifacts；详情/导出使用原生固定快照，阻塞工作放入线程。
SNAPSHOT_BUSY 返回可重试状态，不停止科学驱动。导出保留五项原生格式与不可覆盖规则。

监控重连是只读行为；`POST resume` 是可能付费的执行操作，非终态必须提交
`{"confirm_execution":true}`，再次通过原生身份/授权/锁/预算检查。终态不派发。
prepared 禁止 stop/resume。浏览器刷新、打开项目、重连 SSE 不能恢复科研执行。
后台 job 的 finished/interrupted/terminal 只是观察信息，不代替 Native Run 状态。

历史 Trace 可只读导入，不等于接管任意历史 CLI 目录。旧 Cockpit 仅作兼容源码保留，
不能用于本版 G3 运行管理；不为 UI 改写原生 rating 事件。未来接入网页请复用本 API/RunService，
不要在前端计算 μ/σ、推断来源或用未来事件补齐历史回放。Human-in-the-loop 不在当前范围。
