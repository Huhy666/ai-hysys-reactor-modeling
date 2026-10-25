# AI HYSYS Web

这是一个仅在 Aspen HYSYS 工作站本地运行的中文 Web 应用。它把自然语言反应需求转换成严格建模规格，通过确定性规则选择反应器，并把 HYSYS 案例、运行事件和结果文件关联到同一条运行记录。

## 功能与支持范围

- 中文自然语言解析、规格校验、缺失信息与建模假设确认。
- 根据确定性规则选择反应器，提供选择依据。
- Conversion 与 Equilibrium 反应器的 HYSYS 建模、求解和结果读取。
- 质量与元素衡算校验、运行历史、JSON/CSV/HYSYS 文件导出。
- Gibbs、CSTR、PFR 目前仅支持模型选择判断，尚未实现自动建模与求解。

## 验证状态

截至 2026-10-26，本地 234 项非 HYSYS 测试通过。远程工作站验收截图记录甲苯歧化与甲烷蒸汽重整自然语言 API 流程通过，包含结果和案例下载。实机数据需在工作站运行目录中查看，未包含在源码仓库中。

额外反应示例已提供，实机验证仍待完成。浏览器自动化回归采用测试夹具；完整网页实机演练和重启演练需在已配置 HYSYS 的工作站进行。

双击 `start_web.cmd` 启动网页，保持服务窗口运行。`run_full_acceptance.cmd` 执行两个示例的自然语言实机验证；`run_generalization.cmd` 执行额外反应验证。

[部署与验证](docs/remote-acceptance.md) · [演示说明](docs/demo-script.md) · [技术报告](docs/report.md)

## 为什么使用基础案例模板

实机探测确认：V15 可以通过 COM 新建空案例，但当前工作站暴露的空案例物性包状态无法提交；`SimulationCases.Open()` 对本地副本返回 `E_ACCESSDENIED`。经过隔离验证，可靠流程是：

1. 手工创建一个无设备、无测试结果的 HYSYS 基础案例；
2. 只包含 HYSYS Databanks 组分表和 Peng-Robinson 物性包；
3. 每个任务把它复制到远程本地临时路径；
4. 使用 `win32com.client.GetObject()` 文件 Moniker 打开副本；
5. 修改副本、调用 `Save()`，再复制到运行目录。

基础案例是环境配置，不提交到 Git，也不包含场景结果。

## 远程工作站安装

要求：Windows、64 位 Python 3.11/3.12、Aspen HYSYS V15、有效许可证和同一交互式用户会话。

在项目目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_remote.ps1
```

然后编辑 `.env`：

```dotenv
APP_HOST=127.0.0.1
APP_PORT=8000
APP_ENV=development

LLM_PROVIDER=openai
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2

HYSYS_VISIBLE=true
HYSYS_PROGID=HYSYS.Application
HYSYS_BASE_CASE_PATH=C:\AI-HYSYS\base-case.hsc
HYSYS_PROBE_RESULT_PATH=C:\AI-HYSYS\runs\probe-result.json
HYSYS_RUN_TIMEOUT_SECONDS=300
HYSYS_ARTIFACT_DIR=C:\AI-HYSYS\runs
LOG_LEVEL=INFO
```

`HYSYS_VISIBLE=false` 时，应用仍会在首个可执行任务到达后自动启动专用
HYSYS 实例，但不显示 HYSYS 主窗口；演示或排错时建议保持 `true`。

不要把 Windows、RDP、AspenTech、许可证或语言模型密码写入代码、案例名称或日志。

## HYSYS 能力探测

在 HYSYS 工作站本机执行：

```powershell
$env:HYSYS_INTEGRATION_ENABLED="true"
.\.venv\Scripts\python.exe scripts\probe_hysys.py --output runs\probe-result.json
```

通过条件：`architecture_compatible`、`dispatch`、`version_read`、`seed_case`、`stream_round_trip`、`case_save` 全部为真，`all_required=true`。

探针只修改基础案例的临时副本。若 HYSYS 在探针前已经运行，探针不会退出用户已有的应用程序实例。

## 启动 Web 应用

```powershell
.\.venv\Scripts\python.exe scripts\run_server.py
```

在远程桌面浏览器打开：<http://127.0.0.1:8000>。

API 文档：<http://127.0.0.1:8000/docs>。

## 主要 API

- `GET /api/health`：应用、AI 和已保存 HYSYS 探针状态；
- `POST /api/specs/parse`：自然语言转草稿规格；
- `POST /api/specs/validate`：严格校验和确定性反应器选择；
- `POST /api/specs/prepare`：把可编辑草稿提升为可执行规格；
- `POST /api/workflows/submit`：AI 提取、校验，并在完整时自动创建和入队；
- `POST /api/runs`：创建可追溯运行记录；
- `GET /api/runs`、`GET /api/runs/{id}`：历史和详情；
- `POST /api/runs/{id}/cancel`：立即取消未运行任务，运行中只请求安全边界取消；
- `GET /api/runs/{id}/events`：SSE 事件快照；
- `GET /api/runs/{id}/artifacts/{filename}`：受路径和扩展名限制的文件下载。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not hysys" -v
.\.venv\Scripts\python.exe -m ruff check app tests scripts
```

只有在安装 HYSYS 的工作站上才执行：

```powershell
$env:HYSYS_INTEGRATION_ENABLED="true"
.\.venv\Scripts\python.exe -m pytest -m hysys -v -s
```

## 安全与数据边界

- Web 默认只监听 `127.0.0.1`；
- `.env`、`runs/`、日志、`.hsc`、虚拟环境和 RDP 文件均被 Git 忽略；
- COM 调用必须进入专用 STA 工作线程并串行执行；
- 仅关闭应用明确拥有的 HYSYS 实例；
- Fake 适配器只用于自动化测试，不能在生产模式返回结果；
- 结果只有在来源为 `hysys`、HYSYS 报告收敛且独立衡算通过后，才能显示为成功。

源码仓库：https://github.com/Huhy666/ai-hysys-reactor-modeling （main 分支已上传）。
