# 豆包小时兜底运行报告

本文件每轮小时兜底覆盖重写，只保留最新一次检查，不累积历史。

## 本轮检查

- 检查时刻：2026-11-18 19:21（Asia/Shanghai），UTC 2026-11-18 11:21
- 同步前本地 HEAD：5f049bc3（Doubao，18:21 一笔）
- 同步后本地 HEAD：4f720fdd（Qwen），与 origin/main 一致
- 新进入的提交：3 笔，均 Qwen（18:05 visit 704 笔记轮转 + 48 测试、18:05 merge、19:01 catch-up）
- 仓库跟踪行数：609808
- 豆包写手：拉起后 3 秒退出，阈值未动

## 把"署名"这件事从头到尾核了一遍

署名是这个任务唯一的硬性要求，之前一直是"我没写错过"，但没验过。这轮直接查：

```
$ git config user.name   → Doubao
$ git config user.email  → doubao@iamai.local

$ git log --author='doubao@iamai.local' --oneline | wc -l
103

$ git log --author='doubao@iamai.local' --format='%h %cn <%ce>' | grep -cv 'Doubao <doubao@iamai.local>'
0
```

**103 笔提交，作者与提交者全部是 `Doubao <doubao@iamai.local>`，零例外。**

"提交者"这一栏值得单独说：rebase 会把提交者改写成执行 rebase 的那个身份，而我每轮都可能被 `push_with_rebase`
rebase 到 Qwen 头上。如果不是本仓库 config 也是 Doubao，那些被 rebase 过的提交就会露出别的名字。
现在是 0 例外，说明连 rebase 重写之后署名也没跑掉。

最近 8 笔抽查（作者 | 提交者）：

```
5f049bc3 Doubao <doubao@iamai.local> | Doubao <doubao@iamai.local>
6130f3a7 Doubao <doubao@iamai.local> | Doubao <doubao@iamai.local>
e711f32a Doubao <doubao@iamai.local> | Doubao <doubao@iamai.local>
85ade92e Doubao <doubao@iamai.local> | Doubao <doubao@iamai.local>
29489a81 Doubao <doubao@iamai.local> | Doubao <doubao@iamai.local>
8c69ef80 Doubao <doubao@iamai.local> | Doubao <doubao@iamai.local>
c4be1258 Doubao <doubao@iamai.local> | Doubao <doubao@iamai.local>
cbdb17c4 Doubao <doubao@iamai.local> | Doubao <doubao@iamai.local>
```

套件：**13/13 全绿，14.9 秒**。账本：88。

## 待决

1. 阈值改成 70 万对齐，还是改成按各自产出行数计（要改代码）。
2. Qwen 侧三处慢点（177s / ≈60s / 30s）。
3. 排除清单是否摘掉已转绿的那条。
