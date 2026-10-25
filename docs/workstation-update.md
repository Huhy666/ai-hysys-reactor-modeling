# 更新工作站并核对运行版本

[返回项目首页](../README.md)

## 版本核对

Python服务会保留已经导入的模块。只替换文件或刷新浏览器，不保证旧进程使用了新后端。脚本与网页也可能从不同目录运行。

若水煤气变换被要求包含甲苯、苯和二甲苯，或拒绝kPa abs，应核对实际执行来源。当前源码支持明确的绝压写法，通用Conversion构建器不要求非甲苯反应具备芳烃组分。

新版本在启动窗口和网页状态中显示build编号，并提供/api/runtime。编号是启动时的源码快照，不会因运行中替换文件自动变化。

## 在原目录更新

1. 从仓库Code → Download ZIP下载最新源码，解压到独立目录。
2. 在旧网页服务窗口按Ctrl+C，等待退出，保留案例和运行记录。
3. 在新解压目录打开命令窗口，执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\update_workstation.ps1 -ProjectRoot C:\Users\azureuser\Newfolder
```

目标路径按实际原项目填写。工具更新app、scripts、入口、依赖声明与配置模板，先备份已有源码；实际.env、.venv、runs和已有案例保留。端口被占用时拒绝更新，不结束其他进程。依赖安装仍由setup_remote.ps1负责。

4. 回到原目录启动：

```cmd
cd /d C:\Users\azureuser\Newfolder
.venv\Scripts\python.exe scripts\run_server.py
```

5. 在原目录另开窗口核对：

```cmd
.venv\Scripts\python.exe scripts\check_runtime.py --url http://127.0.0.1:8000
```

应显示实际模块路径、单位预检通过，且Source build与Running build一致。不同则排查旧进程和端口。

6. 浏览器Ctrl+F5刷新，提交新任务。分别执行run_generalization.cmd和网页新反应验证，保存新结果。历史不能代替本次网页任务。

## 验证边界

tests/browser/check_generic_workflow.py使用实际浏览器、FastAPI、确认操作、单位转换与构建器，覆盖三类新反应；AI与COM为明确测试边界，结果保持fake。

真实AI与HYSYS的三反应入口仍是run_generalization.cmd。网页实机验收需在工作站新任务完成后另记。版本与单位预检不等于真实模拟成功。
