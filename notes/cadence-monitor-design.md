# cadence-monitor — 2026-11-01

写了一个 cadence_monitor 模块，用来度量写手节奏：

- stroke gap：两条相邻 stroke 之间的时间差，目标 15s
- batch gap：两次相邻 commit 之间的时间差，目标 600s
- health 三档：healthy（<=1.5x）、slowing（<=3x）、stalled（>3x）

设计原则是纯观测、无副作用——只读 strokes.jsonl 尾部和 git log，不
写任何状态文件。这样 caretaker 可以随时调用，不用担心和 writer /
batch 进程互相干扰。

整体健康取 stroke 和 batch 中较差的一档。理由字段会列出哪个维度
不达标以及实际比率，方便 caretaker 直接拿去写 commit message。
