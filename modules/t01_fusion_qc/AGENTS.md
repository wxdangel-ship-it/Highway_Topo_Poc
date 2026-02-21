# t01_fusion_qc - AGENTS

## 目标
- 评估轨迹 Z 与点云局部高程估计的一致性，输出可复核的统计指标与异常区间。
- 在 patch 粒度定位参差区间，支撑文本化质检回传。

## 模块范围
- 输入：merged.laz|merged.las 点云 + raw_dat_pose.geojson 轨迹。
- 输出：metrics.json、intervals.json、summary.txt（写入 outputs/_work/t01_fusion_qc/<run_id>/）。
- 能力：patch 发现、轨迹解析、邻域高程估计、分位数统计、区间合并与报告导出。

## 禁止事项
- 不修改 t02、t03、t04、t05 任何代码或接口契约。
- 不改动其它模块 INTERFACE_CONTRACT。
- 不在 outputs/ 目录下作为开发/测试工作目录。
- 不输出超长原始逐点明细到 summary 文本。
