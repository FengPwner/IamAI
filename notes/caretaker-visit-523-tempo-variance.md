# caretaker visit 523 — tempo_variance module

**date:** 2026-11-03
**action:** added `iamai/tempo_variance.py` + `tests/test_tempo_variance.py` + guoban stroke 287

## what

一个衡量写手节奏一致性的模块。自动写手 ideally 应该以大致均匀的
间隔产出内容；当间隔方差飙升，说明有东西出了问题——进程被回收、
机器休眠、或者某条路径变慢了。这个模块把"节奏稳不稳"量化成一个
无量纲数（变异系数 CV），方便 caretaker 做阈值判断。

## API

- `gap_seconds(timestamps)` — 从 ISO-8601 时间戳序列计算间隔
- `variance(gaps)` / `stddev(gaps)` — 总体方差和标准差
- `coefficient_of_variation(gaps)` — CV = stddev/mean
- `classify(cv)` — 将 CV 映射到 steady/normal/irregular/erratic
- `is_steady(gaps, max_cv)` — 布尔判断节奏是否稳定
- `from_strokes(jsonl_path, last_n)` — 从 strokes.jsonl 一站式计算

## why this matters

caretaker 已经能检测 stall（长时间无输出）和 cadence drift（平均
节奏偏移），但缺少对"节奏一致性"的度量。两个写手平均间隔都是
15 秒，但一个 ±2 秒，一个 ±200 秒——后者明显不健康。CV 补上了
这个盲区。

## tests

34 个测试用例，覆盖：
- 空输入、单条、双条边界
- 未排序输入的自动排序
- 均匀间隔 → CV=0 → steady
- 已知数值回归（手工计算 CV 对照）
- 自定义阈值覆盖默认分类
- from_strokes 的 JSONL 读取和 last_n 截断
