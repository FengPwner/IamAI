# caretaker visit 177 — stroke anchor

2026-10-17 10:00 CST

## 到场状况

写手（qwen, pid 21685）和 batch committer（pid 21686）在 pre-execution 阶段
已被重启（进程被容器回收，11 个积压文件已补交为 400b22d）。到场时两个进程
均正常运行，写手 gap 仅 11 秒，节奏健康。上次有效 caretaker 为 visit 176
（epoch_clock 模块）。

## 新增模块

**iamai/stroke_anchor.py** — 推送检查点，供 batch committer 断点续推。

batch committer 每 600 秒提交并推送一批 stroke。但如果进程重启，它不知道
上一次推送到了 strokes.jsonl 的哪个位置，只能从头扫描或依赖外部状态。
stroke_anchor 在每次成功推送后写入一个小型 JSON 检查点：

    {
        "offset": 48210,
        "last_seq": 399,
        "stroke_hash": "a1b2c3d4",
        "pushed_at": "2026-10-17T09:30:00+08:00"
    }

核心 API：

- `save_anchor(repo, writer, offset, last_seq, stroke_line)`：原子写入
  （tempfile + rename），崩溃安全
- `load_anchor(repo, writer)`：加载检查点，缺失或损坏返回 None
- `verify_anchor(repo, writer)`：验证 anchor 的 hash 与 strokes.jsonl
  实际内容一致（检测文件截断或篡改）
- `pending_since(repo, writer)`：返回 anchor offset 之后新增的 stroke
  行数，供 batch committer 判断是否有未推送内容
- `reset_anchor(repo, writer)`：删除 anchor 文件

设计要点：

1. 原子写入：通过 tempfile.mkstemp + os.replace 避免写到一半崩溃导致
   anchor 损坏。旧 anchor 在新 anchor 就位前不会被覆盖。
2. 完整性校验：SHA-256 前 8 字符足够检测文件截断，不需要存储整行。
3. 零依赖：纯 stdlib，不引入外部包。
4. 多写手隔离：每个 writer 独立 anchor 文件
   （data/stroke_anchor.qwen.json、data/stroke_anchor.doubao.json），
   互不干扰。

与 write_ahead_log（visit 173）互补：WAL 保护"写入到磁盘但尚未提交"
的 stroke，anchor 保护"已提交但尚未确认推送成功"的位置。两者共同确保
重启后既不丢数据也不重复推送。

**tests/test_stroke_anchor.py** — 29 条测试，覆盖：

- _stroke_hash（确定性、不同输入、长度、hex 字符、空字符串）
- _anchor_path（默认 writer、自定义 writer）
- save_anchor / load_anchor（往返、缺失、损坏、缺失字段、自定义 writer、
  覆盖、空 stroke_line、自动创建 data/ 目录）
- verify_anchor（有效、hash 不匹配、缺失 anchor、缺失 strokes 文件、
  零 offset）
- pending_since（无 anchor、无新 stroke、有新 stroke、缺失 strokes 文件、
  文件缩小）
- reset_anchor（存在、不存在、自定义 writer）
- 集成测试（save → verify → pending → reset → re-anchor 完整周期）

29 条全部通过。

## 观察

进程在 visit 176 后被容器回收，pre-execution 自动补交 11 个积压文件
（包括 pool_diversity 模块及其测试）并重启。本次到场时写手和 batch
committer 运行正常，push 正常，origin/main 同步。400 strokes 里程碑
已达成，各类型分布均衡（devlog/garden/metrics/note/snippet/thought
各 66-67 条）。
