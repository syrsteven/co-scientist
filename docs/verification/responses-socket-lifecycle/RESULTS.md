# TUN与Responses正文读取：复现与修复

基线main `b677c7f94f588aa71c3f453a13620f4e6bb0ad6c`，独立分支`codex/responses-socket-lifecycle`。原工作区及PR17历史交付不改。本轮只修传输，不恢复任何uncertain任务。

## 已确认原因

Python3.12 stdlib `urllib.request.AbstractHTTPHandler.do_open`在收到响应头后关闭HTTPConnection持有的socket引用；HTTPResponse的makefile仍可读。
此时socket._closed可能为true但fileno仍有效，不能仅看_closed跳过所有活跃读取的超时。
当`HTTPResponse.read1`恰好读完Content-Length声明的正文，会关闭最后的文件引用，socket.fileno变为-1。
旧循环下一次为了读取EOF先执行socket.settimeout，触发OSError/EBADF9。完整响应已经读到，却走transport uncertain路径，无法保存完整response ID/usage。

[实际修复前复现](before-fix-reproduction.json)：三条无凭据GET都收到完整401 JSON（151字节），第二轮读取前设置超时均报errno9/fd=-1。
这证明存在应用读取缺陷；不证明历史P09一定收到了相同内容，也不改判其uncertain/未知费用。旧P09仅有TRANSPORT_ERROR，无法倒推出确切errno或恢复丢失响应。
之前仅一次`read()`的连通性测试漏掉EOF迭代，不能代表适配器完整路径；本轮补足了相同生产读取函数的验证。

## 改动

`read_response_body`抽出原有有界读取循环，只有fileno>=0时设置逐读超时；fd已经释放时让HTTPResponse返回正常EOF。
保持socket timeout与总期限、16MB限制、Content-Length不足检测和不重试。活跃fd的真实错误仍抛出，不捕获一切OSError伪装成功。
安全诊断增加EBADF数字错误码到类型与记录双重允许列表，不保存原始异常字符串。
`actual_request`、模型、Prompt、政策、科学输入与调用身份均不变。

## 无凭据真实网络验证

同一生产正文读取函数，固定`GET https://api.openai.com/v1/models`，不发Authorization、不读取模型密钥、不生成内容、不访问数据库：

| 路径 | 结果 | 耗时 | 证据 |
|---|---|---|---|
| 系统默认、未export | 完整401 JSON | 约0.83秒 | system.json |
| 应用ProxyHandler({})，保留OS/TUN路由 | 完整401 JSON | 约0.83秒 | direct.json |
| 显式HTTP(S)7897，另设all_proxy=socks5 | 完整401 JSON | 约0.90秒 | explicit.json |

未export进程的http_proxy/https_proxy/all_proxy均未设置，但urllib仍发现macOS系统HTTP(S)代理127.0.0.1:7897；默认应用可能使用系统代理。
`direct`明确禁用urllib应用代理发现，在现有操作系统路由下也成功；没有改网络/TUN配置，没有证明出口节点或TUN内部链路。
HTTP(S)在本次显式配置选用HTTP CONNECT；不声称Python urllib实际使用all_proxy的SOCKS5。
401是无鉴权预期结果，证明HTTP完整读取，不证明付费POST、长响应、真实模型能力或所有网络条件可靠。

```sh
# 使用现有coscientist Python，运行在独立修复工作目录；不会读取密钥
PYTHONPATH=src python scripts/check_responses_transport.py --route system
PYTHONPATH=src python scripts/check_responses_transport.py --route direct
export https_proxy=http://127.0.0.1:7897 http_proxy=http://127.0.0.1:7897 all_proxy=socks5://127.0.0.1:7897
PYTHONPATH=src python scripts/check_responses_transport.py --route explicit --proxy http://127.0.0.1:7897
```

一次命令只发一次GET，无自动切换或重试；输出仅安全配置、状态、正文hash/长度及阶段，不输出正文/鉴权。

## 验证记录

现有conda coscientist Python3.12.11/pytest8.4.2/Ruff0.16.6。
新增测试先在修复前复现Content-Length失败（1失败、2通过），修复后通过；新增EBADF诊断测试曾发现第二层允许列表缺少该码，补齐后通过。
Focused：`env -u OPENAI_API_KEY PYTHONPATH=src python -m pytest -q tests/next/test_responses_background.py tests/next/test_reading_model.py`：73通过。
Final全量：`env -u OPENAI_API_KEY PYTHONPATH=src python -m pytest -q tests/next`：**382通过、0失败/跳过，51.18秒**（373既有+9新增）。见[完整输出](pytest-final.txt)。
全仓Ruff沿用CI的3项旧迁移I001路径豁免通过，5份改动Python format --check及git diff --check通过。
`python -m build --no-isolation --outdir /private/tmp/response-socket-fix-build` wheel/sdist成功；仓库外no-deps/no-index安装后生产reader导入成功，[构建哈希](build.json)。
最终全量通过后仅合并了测试内import分组、补文档，未改变运行逻辑；首次Ruff发现该import顺序后已修正并复核通过。
原真实库与指定隔离试跑库SHA256均与上一轮完成时一致；原工作区232项内容/index/status指纹通过。

全量回归覆盖已成功调用回放、跨进程同ID查询、未确定提交不重发、密钥保护；新增真实socketpair/HTTPResponse用例覆盖200/401 × Content-Length/chunked/connection-close，以及正文截断/活跃settimeout错误/EBADF脱敏。没有修改全局禁止真实网络断言，HTTP测试仅loopback。
无模型POST或旧库恢复；旧G3全套、真实模型生成、跨Python版本本机全量、科学/伦理有效性未运行/未验证。原科学Prompt/候选/政策/记录未改。science_validated=false。
