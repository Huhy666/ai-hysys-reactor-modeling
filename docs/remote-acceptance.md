# 远程联调与验收

本次本地代码检查不等于远程 HYSYS 验收通过。先完成甲苯的结构化诊断，再完成真实 AI 输入和实机计算，最后录制浏览器演示。

## 1. 放置更新文件

在远程桌面中，将更新包解压到远程本地磁盘的新目录，例如 `C:\AI-HYSYS\release`。保留旧目录及其中的 `.env`、基础案例和运行记录，不覆盖它们。不要从 `\\tsclient` 或 ZIP 压缩包内部直接运行。

将远程旧项目的 `.env` 复制到新目录；也可以通过 `--env-file` 指定旧配置路径。配置发现脚本只在当前目录及 `C:\AI-HYSYS` 下查找，不会打印密钥。配置中必须有可用的 `HYSYS_BASE_CASE_PATH` 和远程本地 `HYSYS_ARTIFACT_DIR`。

基础案例应只有所需数据库和 Peng–Robinson 物性包，没有预建反应器或场景结果。不要把正式工作案例当作基础案例。每次联调都操作副本。

## 2. 先诊断甲苯

由用户在已登录 HYSYS 的同一 Windows 会话中，双击 `run_toluene_check.cmd`。脚本会询问是否接受以下假设：

- 邻、间、对二甲苯选择性各为 1/3；该比例是演示假设，不是平衡预测。
- 甲苯反应器绝热运行，零压降。

确认后，脚本检查依赖、探测 HYSYS，再通过应用 API 创建真实任务。诊断使用已知结构化输入，目的是先排除语言模型因素，**不算自然语言闭环通过**。

成功须同时满足：任务 `succeeded`、来源 `hysys`、质量和元素衡算通过、存在 `conversion.hsc`、JSON/CSV/HYSYS 文件下载正常。不得用理论计算结果替代 HYSYS 输出。

等效命令：

```powershell
.\.venv\Scripts\python.exe scripts\run_demo_checks.py --scenario toluene --require-hysys --confirm-demo-assumptions
```

如未自动找到配置：

```powershell
.\.venv\Scripts\python.exe scripts\run_demo_checks.py --discover
.\.venv\Scripts\python.exe scripts\run_demo_checks.py --env-file C:\旧项目\.env --scenario toluene --require-hysys --confirm-demo-assumptions
```

## 3. 两个必测场景的自然语言验收

确认语言模型配置有效后双击 `run_full_acceptance.cmd`。脚本通过真实模型解析自然语言，经同一规格确认、任务队列、COM 执行、读回、衡算和文件下载路径运行两个场景。

重整输入为甲烷1000 kmol/h、水2700 kmol/h，摩尔比1:2.7；按8000 h/年计。进料520℃、1350 kPa绝压。比较出口600℃和710℃，出口压力相同，压降为0。使用 HYSYS 可用热力学平衡数据仍须实机确认，脚本不会生成平衡结果。

模型如果提出约定之外的假设，脚本停止并保存解析文件，用户应在网页审查，不自动替用户确认。

```powershell
.\.venv\Scripts\python.exe scripts\run_demo_checks.py --scenario all --require-ai --require-hysys --confirm-demo-assumptions
```

验收记录位于配置的运行目录下 `acceptance-时间戳\acceptance.json`。真实任务另有独立运行编号和案例文件。报告会明确区分 `structured_diagnostic` 与 `natural_language`。

## 4. 浏览器演示与交付

```powershell
.\.venv\Scripts\python.exe scripts\run_server.py
```

在远程浏览器打开 `http://127.0.0.1:8000`。执行两个原始需求，审查假设、运行、查看表格、下载文件，并在 HYSYS 中打开对应案例核对。然后重启服务，验证历史可读且可再次运行。

必须再验证未预置反应，例如给定转化率的水煤气变换（需明确CO为转化率基准）、单工况可逆变换和平衡甲烷化。通用执行代码的存在不代表实机验收通过；逐条保存结果。

Gibbs、CSTR、PFR 当前只有选择规则，真实执行仍未实现，不能宣称已完成这些模型。两个必测场景之外的通用实机案例、录屏、GitHub 仓库、AI会话导出和正式报告仍须提供。

## 5. 失败时保留哪些信息

保留 `acceptance.json`、对应任务的 `run.json` 和 `events.jsonl`，以及已保存的案例。不要发送 `.env`、RDP配置、账号密码或模型密钥。

- `base_case` 失败：检查旧配置路径和基础案例是否位于远程本地磁盘。
- `hysys_probe` 失败：查看 `probe-result.json` 中的具体检查项；确认许可证和用户会话。
- `create_reaction_set`、`set_conversion_coefficients` 等失败：保留具体操作检查点，按实机 V15 接口继续映射。
- 求解超时：不要视为成功。检查 HYSYS 中反应集、热规格、压降、物流连接和状态；不要直接延长超时代替排错。
- 独立衡算失败：任务必须失败，保留案例排查组分顺序、计量系数和物流数据。

当前求解就绪判断依据是出口变量已知、数值稳定以及转化率目标检查；这尚不等同于已验证 V15 的原生设备收敛状态属性。正式验收需结合 HYSYS 设备状态核对。
