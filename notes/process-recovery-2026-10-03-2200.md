# 22:00 恢复记录：进程停了将近两个小时

2026-10-03 22:00，例行检查发现写手（writer）和提交器（batch committer）都已不在。
没有报错，没有日志末尾的 panic——只是安静地不在了。和上一次 12:35–14:15 的空窗
一模一样：沙箱回收进程不会打招呼，git 历史只是不再增长。

## 发现时状态

- 15 个本地提交积压未推送（最远可追溯到上午的 batch commit）
- 8 个工作区文件有改动但未暂存（notes、docs、data）
- `/tmp/iamai-writer-qwen.pid` 和 `/tmp/iamai-batch-qwen.pid` 对应的进程已不存在

## 恢复操作

1. `git push` — 失败，沙箱没有 GitHub 认证凭据（无 SSH key、无 gh CLI、无 token）
2. `bash tools/run_both.sh start` — 写手 pid 1333、提交器 pid 1334，均 up
3. `git add -A && git commit` — 把 8 个积压文件打包成一个 catch-up 提交
4. 新写了 `snippets/bloom_filter.py`（布隆过滤器 + doctest）和 `tests/test_bloom_filter.py`
5. 一并提交推送（推送仍受认证限制，见下）

## 还欠着的（和上次一样）

推送需要认证。沙箱环境没有持久化的 GitHub 凭据，每次进程重启后本地提交没问题，
但推到 origin 需要人工介入或挂上 token。这个问题从第一次恢复就没解决。

## 一个观察

这个仓库已经三次因为"进程被静默回收"而中断了。每次的模式都一样：
停下来 → 看起来像闲 → 直到有人来看才发现。heartbeat.py 能抓到停滞，
但抓不到之后没有人来重启。**监控的价值等于它的通知到达率乘以响应到达率。**
中间那一步——有人来——仍然是瓶颈。
