# 工作站验证入口

首次部署见[安装与运行](getting-started.md)，当前验证范围与实机记录见[验证记录](validation.md)，网页操作见[展示指南](web-demo.md)。

## 验证流程

1. 确认许可证、基础案例、实际.env和同一Windows会话。
2. 运行探针，核对all_required及报告路径。
3. 需要隔离AI因素时使用run_toluene_check.cmd；它只做结构化诊断。
4. 使用run_full_acceptance.cmd执行两个主要场景的真实AI与HYSYS验证。
5. 需要可选界面辅助依赖时使用run_deadline_acceptance.cmd。
6. 使用run_generalization.cmd执行三个额外反应。
7. 保留验收汇总与各任务结果，再做网页和重启演练。

脚本的确认步骤用于约定假设；若AI新增假设超出约定，停止自动验收并在网页审查，不自动放行。

## 数据核验

任务应有对应输入、规格、决策、事件、结果与案例。验收汇总位于acceptance-时间戳目录，实际案例在任务编号目录。

确认source=hysys、结果有效、转化率或工况符合要求、质量及元素衡算通过，并在HYSYS核对设备状态。求解稳定性判断不替代全部原生设备收敛属性。

失败时保留报告及部分案例，按[问题排查](troubleshooting.md)处理。
