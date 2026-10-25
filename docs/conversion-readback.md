# 已保存案例的诊断读回

[返回问题排查](troubleshooting.md)

转化率未达标时，先读取实际流量与反应配置，不直接归因于排序或数值精度。

## 使用方法

在原工作站项目中双击inspect_conversion_case.cmd。工具查找最近一次转化率不符且已保存conversion.hsc的失败任务，将案例复制到本地临时目录，暂停副本求解并读回已有数据。不会重新解析AI或重建反应器；结束时只关闭临时副本。

结果写入该任务的case-readback.json，重点检查：

- conversion_checks：基准组分实际进出口、目标及实际转化率。
- array_component_order_used与database_component_order：组分顺序。
- attached_reactions：基准、反应计量及转化率系数。
- reactor_controls：可用控制成员及读回。

若找不到案例，检查任务目录是否保留conversion.hsc，不以基础案例替代。后续求解超时会尝试保存solver-diagnostics.json及部分案例，是否存在取决于失败位置。

保留原记录，不修改容差或伪造结果使任务通过。输出文件可能包含输入和路径，分享前检查内容。
