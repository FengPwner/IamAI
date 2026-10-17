# caretaker visit 179 — stroke parity

2026-10-17 12:01 CST

## 到场状况

写手（qwen, pid 15641）和 batch committer（pid 15642）在 pre-execution 阶段
已被重启（进程被容器回收，9 个积压文件已补交为 e5f6860）。到场时两个进程
均正常运行，gap 24s。上次有效 caretaker 为 visit 178（push_receipt 模块）。

## 新增模块

**iamai/stroke_parity.py** — 磁盘写入与 git 提交之间的奇偶校验。

写手每 15 秒往 data/strokes.jsonl 追加一条 stroke，batch committer 每 600 秒
快照并推送一次。两次提交之间，磁盘上的 stroke 处于"已写入但未提交"的悬空
状态。如果进程崩溃，这些未提交的 stroke 会丢失。

stroke_parity 测量这个间隙：

    {
        "total": 3205,
        "committed": 3200,
        "orphan_count": 5,
        "orphan_seqs": [3201, 3202, 3203, 3204, 3205],
        "ratio": 0.9984,
        "by_kind": {"thought": {"total": 67, "committed": 65, "orphan": 2}, ...}
    }

核心 API：

- `stroke_parity(repo)`：计算磁盘 JSONL 与 git HEAD 版本之间的奇偶状态
- `parity_summary(repo)`：人类可读的一行摘要（如 "3200/3205 strokes committed (99.84%), 5 orphans pending"）
- `orphan_strokes(repo)`：返回已写入但未提交的 stroke seq 列表（升序）
- `parity_grade(repo)`：字母评级——A（≥99%）/ B（≥95%）/ C（≥90%）/ D（≥80%）/ F（<80%）
- `kind_parity(repo, kind)`：按 stroke 类型查看奇偶明细
- `parity_trend(reports)`：对一系列快照计算趋势（均值、最低值、峰值 orphan 数、是否在改善）

设计要点：

1. git show HEAD:data/strokes.jsonl 读取已提交版本，无需工作区干净
2. 基于 seq 集合差集计算 orphan，不依赖行号或文件偏移
3. 容错：空行和损坏 JSON 行静默跳过，不中断检查
4. ParityReport dataclass 提供 is_synced / critical 属性，方便下游判断
5. critical 阈值设为 >20 orphan（约一个 batch 的 stroke 量），超过即告警
6. 零外部依赖，纯 stdlib + subprocess

与 push_receipt（visit 178）互补：receipt 验证"推送是否到达远程"，parity
验证"写入是否进入 git"。两者共同覆盖从磁盘写入到远程到达的完整链路。

**tests/test_stroke_parity.py** — 44 条测试，覆盖：

- _read_strokes（基础读取、空文件、缺失文件、空行跳过、损坏 JSON 跳过、
  保持顺序、大文件 1000 条）
- _seq_set（基础提取、空列表、缺失 seq 键）
- _kind_breakdown（基础分类、空输入、全 orphan、未知 kind）
- stroke_parity（完美奇偶、部分 orphan、critical 阈值、非 critical 边界、
  空仓库、未提交状态、按 kind 明细、ratio 精度、自定义文件路径）
- parity_summary（同步、有 orphan、单 orphan 单复数、百分比格式）
- orphan_strokes（基础、空列表、升序排序）
- parity_grade（A/B/C/D/F 参数化、空仓库为 A）
- kind_parity（存在 kind、不存在 kind 返回零）
- parity_trend（改善趋势、退化趋势、空序列、单条报告）
- 集成测试（完整生命周期：空 → 写入 → 提交 → 再写入 → 全部提交）

44 条全部通过。

## 观察

进程在 visit 178 后被容器回收，pre-execution 自动补交并重启。到场后
写手与 batch committer 运行正常，400+ strokes 产出稳定。本次新增
parity 模块填补了"磁盘→git"链路的可观测性空白。
