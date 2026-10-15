# 前端接入边界

**本版没有已上线 HTTP 管理 API 或生产网页。** 未打包静态 Workbench，更未宣称其接通后端。
当前可复用服务层为 `co_scientist.release.service.RunService`，CLI 是其真实调用方。
后续 Web 服务应薄封装此接口，不重新实现科学算法。

开发树已有 Node Cockpit 与 Python `application/cockpit.py` 原型，不能笼统称为纯静态页面。
但实测旧 `snapshot()` → `SqliteRunReadModel._ratings_and_matches()` 读取本版G3时，
因旧reader要求 `evaluation_rules_hash` 而抛出KeyError；它不是可直接部署的G3管理API。
旧control桥还返回旧`worker run`命令，不能代替本版的独立授权/恢复入口。
Python兼容源码保留，但这些原型不是受支持的Release操作接口；Node/Web资源不纳入。
没有修改旧reader或科研事件来掩盖不兼容；新前端应接下面已验证的服务/Native trace。

| 用户操作 | 已实现接口 |
| --- | --- |
| 校验 / 创建 | `validate(goal, profile)` / `create(goal, data_dir, ...)` |
| 明确授权 | `authorize(root, confirm, accept_usd, accept_unknown_risk, confirm_pricing)` |
| 启动 / 恢复 | `await execute(root)`，原生 CoreRunner.drive/Worker.run_once |
| 状态 / 费用 | `status(root)`，SQLite 只读查询和 native budget snapshot |
| 增量事件 | `events(root, after=sequence)` |
| 安全停止 | `stop(root)`，durable请求，下一执行边界原生PARTIAL |
| 候选 / rating / 谱系 / 结果 | `await export(root, output)`，原生export_trace五项文件 |

接口参数和 CLI help 已由离线测试实际调用，不是已部署 REST endpoint。
Web 接入需另行增加认证/授权、路径隔离、后台作业生命周期、TLS 和审计。
不能将请求线程阻塞7200秒或允许浏览器任意指定文件路径。
一个 Run 仅一个驱动进程，POSIX lock 阻止重复驱动；event sequence 用于增量监控。
凭据应来自服务器安全环境，不能从浏览器回显或进入 exports。

Human-in-the-loop 属于后续增强，当前没有人为更改候选准入、排序或终局选择的入口。
本版不支持远程多用户安全边界、取消已发送 HTTP 或用 stop 重开终止 slot。
