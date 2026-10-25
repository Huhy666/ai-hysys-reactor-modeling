# 安装与运行

[返回项目首页](../README.md)

## 环境要求

| 项目 | 要求 |
|---|---|
| 系统 | 可正常使用 HYSYS 的 Windows 工作站 |
| Python | 3.11 或 3.12，64 位 |
| 模拟器 | Aspen HYSYS V15，许可证有效 |
| AI | 已配置的兼容接口、模型名称与密钥 |
| 会话 | 服务与HYSYS位于同一交互式Windows用户会话 |
| 基础案例 | 工作站本地的.hsc，含所需组分和Peng-Robinson物性包 |

源码不包含基础案例、模型凭据、虚拟环境和实机运行记录。

## 已有工作站

在原项目目录继续工作，保留.env、.venv、基础案例和runs。更新源码后按下文启动；依赖有变化时再执行安装脚本。不要复制另一台电脑的虚拟环境，也不要覆盖实际配置。

## 首次安装

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_remote.ps1
```

脚本检查Python版本及位数，创建或验证虚拟环境，安装依赖，并在.env不存在时复制模板。安装完成不等于AI或HYSYS已经验证。

## 配置

编辑根目录.env，路径按工作站实际位置填写：

```dotenv
APP_HOST=127.0.0.1
APP_PORT=8000
LLM_PROVIDER=openai
LLM_BASE_URL=
LLM_MODEL=
LLM_API_KEY=
HYSYS_VISIBLE=true
HYSYS_PROGID=HYSYS.Application
HYSYS_BASE_CASE_PATH=C:\AI-HYSYS\base-case.hsc
HYSYS_PROBE_RESULT_PATH=C:\AI-HYSYS\probe-result.json
HYSYS_ARTIFACT_DIR=C:\AI-HYSYS\runs
HYSYS_RUN_TIMEOUT_SECONDS=300
```

其余默认值见[config.py](../app/config.py)与[配置模板](../.env.example)。AI“已配置”仅表示必填项存在，不代表接口请求已经成功。

基础案例只提供数据库组分及物性环境，不应含场景计算结果。当前工作站复制基础案例并通过文件Moniker打开副本，避免依赖受限的空案例初始化流程。所需组分必须存在于该案例。

## 探测与启动

先确认HYSYS能在同一会话中正常使用，再执行：

```powershell
.\.venv\Scripts\python.exe scripts\probe_hysys.py --output C:\AI-HYSYS\probe-result.json
.\.venv\Scripts\python.exe scripts\run_server.py
```

探针输出应与HYSYS_PROBE_RESULT_PATH一致；检查all_required=true，再进行任务验收。健康页读取已保存的探针报告，不能替代本次实时探测。

双击start_web.cmd也可启动。网页：http://127.0.0.1:8000 ，接口文档：http://127.0.0.1:8000/docs 。保持服务窗口运行。浏览器与服务器在同一工作站时，localhost才指向正确的计算服务。

## 文件与重启

运行文件保存在HYSYS_ARTIFACT_DIR下：

```text
<run-id>/
  run.json
  normalized-spec.json
  decision.json
  events.jsonl
  result.json
  streams.csv
  conversion.hsc 或 equilibrium-*.hsc
acceptance-<timestamp>/
  acceptance.json
```

具体文件随执行阶段而定，验收汇总与实际任务目录分开保存。

等待任务结束，关闭服务后重新启动，确认历史仍可读取，再提交新任务。历史可读不能单独证明COM新任务执行正常。不要在求解期间结束进程。
