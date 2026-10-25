# 开发与验证说明

修改围绕可核验的工程行为展开，功能边界与文档保持一致。

## 开发环境

Windows、64位Python3.11或3.12。软件检查无需HYSYS或AI密钥：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_remote.ps1
.\.venv\Scripts\python.exe -m pytest -m "not hysys" -q
.\.venv\Scripts\python.exe -m ruff check app tests scripts
```

实机验证在具备许可证及基础案例的工作站执行，见[验证记录](docs/validation.md)。

## 修改原则

- 输入解析、模型判断、COM执行与结果校验职责分离。
- 不把AI值、预置输出或夹具标记为真实HYSYS结果。
- 歧义返回明确阻断项，不自动确认新假设。
- COM对象在所属STA线程使用，只关闭应用拥有的会话。
- 单位、反应和流量基准变化须验证计量与守恒。
- 不为通过验收放宽检查或隐藏警告。

提交说明包含问题、最终行为、验证和限制。添加能验证行为的测试；纯文档修订核对链接与命令。软件测试与实机验证分别说明。

.env、.venv、runs、.hsc、RDP及凭据不入库。考核原文、私人参考资料及草稿不属于产品文档。
