# 测试统计与版本对应

## 先说明commit的边界

此前196与193两次运行时，`git rev-parse HEAD`均为基线main
`e705953818feb866dddfcb8093fbc6230e02978f`，但都带有未提交修改。
**它们不是对干净e705树的测试，也没有各自独立的commit。** 当时没有保存完整工作树树哈希；
不能事后把某个commit冒充为这两次历史运行的精确快照。原始简短pytest输出附在tests/。

本轮把最终应用代码、测试及适配器说明提交为
`796a94b497978e7010cf5f3a2ae5e0cef926085e`，然后在该commit上重新完成全量新系统回归。
PR后续提交仅增加审阅包/证据/STATUS，不再改变src或tests；代码哈希见manifest.json。

| 记录 | 实际版本 | 命令范围 | 结果 |
|---|---|---|---|
| historical-196-full.txt | HEAD=e705，带超时、完整usage、固定trial身份等未提交修改；尚无最后兼容性补丁/测试 | `PYTHONPATH=src /Users/lemintea/Documents/co-scientist/.venv/bin/python -m pytest -q tests/next` | 196 passed，0 failed，0 skipped；含4项HTTP |
| historical-193-non-http.txt | HEAD=e705，带最后兼容性补丁及新增1项测试的未提交修改 | 同一Python；`PYTHONPATH=src python -m pytest -q tests/next --ignore=tests/next/test_background_http.py --ignore=tests/next/test_goal_workspace_http.py --ignore=tests/next/test_literature_http.py` | 193 passed，0 failed，0 skipped；4项HTTP未采集，不能计作跳过或通过 |
| final-197-full.txt | **796a94b497978e7010cf5f3a2ae5e0cef926085e** | `OPENAI_API_KEY= DEEPSEEK_API_KEY= PYTHONPATH=src /Users/lemintea/Documents/co-scientist/.venv/bin/python -m pytest -q tests/next` | **197 passed，0 failed，0 skipped**，含4项HTTP |

以上实际运行cwd为`/private/tmp/co-scientist-w1-l2-trial-preparation`；本机既有环境Python3.11.4，pytest8.4.2。
复现可使用满足项目依赖的Python3.11/3.12环境，不强制创建.venv。无需真实模型凭据。
本轮本地Python3.12**未运行**；远端CI结果应单独查看，不能用本机结果代替。

## 数量为何不同

- 基线新系统已有183项；196版增加13项：6个非法timeout配置参数、6个推理响应/截断/空正文/不完整JSON分支、1个固定身份CLI回放测试。
- 最后补丁增加`test_legacy_request_shape_kept_for_saved_success_replay`一项，因此最终完整集合为197项。
- 上次由于全量复跑的自动审批审查模型容量不足，未执行那次全量；未绕过审批。改在沙箱中排除下面4项本地HTTP测试，197−4=193。
- 最初另一次全量在沙箱内为192 passed/4 failed，4个失败均在127.0.0.1绑定被拒阶段；获准本地端口后196项全过。
  该基础设施失败不计为成功，也不隐去。
- 本轮重新申请并取得本地HTTP回归执行权限；**最终197项已全过，原先的4项缺口已补齐**。

4项HTTP测试（不是4个文件）：

```text
tests/next/test_background_http.py::test_background_api_saved_page_and_restart
tests/next/test_goal_workspace_http.py::test_page_api_persistence_readonly_get_and_restart
tests/next/test_goal_workspace_http.py::test_restart_and_get_do_not_recover_unfinished_goal_without_explicit_post
tests/next/test_literature_http.py::test_http_acquisition_duplicate_submission_and_restart
```

## 最后兼容性补丁的原因

旧配置没有timeout_seconds，已保存的actual_request只有endpoint/body。
若为了显示默认90秒而给所有旧请求补上timeout_seconds，M15 TaskCalls在恢复时逐字比较request_json，
会把本应成功回放的旧调用识别为“稳定调用键被用于不同实际输入”。
最后补丁只在配置**显式含timeout_seconds时**把它放进actual_request；省略时保持旧请求形状，传输仍采用原90秒。
本次真实试跑明确设置600秒，实际保存请求含600；这不是覆盖推理参数或给旧记录迁移/重写。
新增测试锁定旧形状不变及显式600秒行为；其他测试验证真实HTTP body和M15 request一致、成功/失败不自动重发。

## 检查类型分开

pytest均为离线夹具/本地HTTP工程检查，绝非新增真实模型阅读。tests内的INVENTED-TEST凭据是假值。
本审阅包的trial-*文件属于此前唯一一次真实P04，不能把夹具成功数当真实调用次数或科学有效性。
Ruff、format、diff检查及便携审阅包校验另有记录；旧G3全套回归和浏览器科学审阅本轮**未运行**。
