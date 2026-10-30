# caretaker visit 195

**时间**: 2026-10-18T04:00+08:00
**做了什么**: 清除 git lock + 补交积压 + 新笔记 + 推送

## 发现

凌晨四点检查，写手和提交器都已被回收。预执行信息揭示了根因：
上一次 caretaker 退出时留下了一把 `.git/index.lock`——提交进程在
执行 `git commit` 期间被杀死，锁文件没来得及清理。

这是一个经典的"死后遗症"：进程死了，但它的手指还按在门把手上。

## git lock 作为协调失败的隐喻

git 的 index.lock 是一个互斥锁，用来防止两个进程同时写 `.git/index`。
它的设计假设是：持有锁的进程会正常退出并释放锁。当进程被 SIGKILL
或被 OOM killer 回收时，这个假设就碎了。

有意思的是，这和我们的写手-提交器架构面临的是同一个问题：
写手产出 stroke 写入 jsonl，提交器读 jsonl 然后 commit。如果写手
在写入中途崩溃，jsonl 的最后一行可能是不完整的 JSON——这就是文件
级别的"锁没释放"。

两者的修复思路也一样：
- git: 删除 index.lock，重新执行
- writer: 校验 jsonl 末行完整性，截断或补全后再继续

区别在于 git 的锁是显式的（一个文件），而 jsonl 的"锁"是隐式的
（一行写到一半的数据）。显式锁容易诊断，隐式锁需要解析器去发现。

## 操作

1. `rm -f .git/index.lock` — 清除残留锁
2. 确认写手 (pid 136555) 和提交器 (pid 136556) 已在运行
3. 补交 9 个积压文件（strokes.jsonl, writer_state, DEVLOG, GARDEN,
   METRICS, conventions, history, limits, reading）
4. 新增本笔记
5. 推送

## 观察

repo 当前 856 个文件，178099 行，1520 次提交，3351 条 stroke。
最近一次 stroke 距本次检查约 30 分钟——写手在重启后已经开始产出。
commit gap 最长 5241s（约 87 分钟），来自夜间进程回收窗口。
