# API 参考

[返回项目首页](../README.md)

服务默认地址 http://127.0.0.1:8000 ，交互式接口文档 http://127.0.0.1:8000/docs 。字段以运行版本生成的OpenAPI文档为准。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | /api/runtime | 启动时源文件版本与时间，不含配置或密钥 |
| GET | /api/health | 配置及已保存探针状态 |
| POST | /api/specs/parse | 自然语言提取草稿 |
| POST | /api/specs/prepare | 校验、选择及归一化 |
| POST | /api/specs/validate | 校验正式规格 |
| POST | /api/workflows/submit | 解析与校验，完整时自动创建及入队 |
| POST | /api/runs | 创建运行，可指定auto_start |
| GET | /api/runs | 历史 |
| GET | /api/runs/{id} | 状态、规格、决策与结果 |
| POST | /api/runs/{id}/cancel | 请求取消 |
| GET | /api/runs/{id}/events | 已保存事件的SSE快照 |
| GET | /api/runs/{id}/artifacts/{filename} | 下载允许类型的任务文件 |

## 显式审查流程

如需保证先审查再执行，分步调用：

1. 向/api/specs/parse提交包含text字段的完整工艺描述。
2. 阅读返回spec与issues，补充输入，确认有依据的assumptions。
3. 将草稿本身提交/api/specs/prepare。
4. executable=true且模型有执行支持时，将返回spec交给/api/runs，并提供original_text及auto_start=true。
5. 轮询任务详情，终态后核验result与文件。

## 结果解释

- executable：规格满足规则；环境就绪另取决于执行器、案例和许可证。
- source：正式结果应为hysys；测试数据须保持测试标识。
- converged：应用结果接受状态，结合稳定性、目标转化率与衡算；仍应核对设备状态。
- validation：质量与元素衡算，多工况按工况组织。
- case_paths：案例路径，通过任务文件接口下载。
- warnings：运行警告及辅助操作关注项。

调用者须检查HTTP状态码和detail。不要仅以是否存在result判断全部错误。
