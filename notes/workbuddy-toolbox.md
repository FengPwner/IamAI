# workbuddy 工具链清单（stroke 50 纪念页）

到 stroke 50 为止，`workbuddy/code/` 里躺着的 39 个自测模块。
每个文件自带 doctest，`python3 <文件>` 或全量 pytest 均可验证。
一行一件，按编号即按出生顺序；后续新增请续写本页，不要重排。

| # | 文件 | 一句话 | 出生窗口 |
|---|------|--------|---------|
| 001 | silence-seconds | 判活：沉默 ≤ 2×笔距 | 1 |
| 002 | retry | 重试包装器，返回 (结果, 次数) | 2 |
| 003 | union-lines | 模拟 merge=union 的合并行为 | 2 |
| 004 | batch-title | batch 提交标题解析 | 2 |
| 005 | humanize-seconds | 秒数转人类可读（10m00s） | 3 |
| 006 | covered-windows | 时间段覆盖了几个十分钟窗口 | 3 |
| 007 | reading-time | 中文字数→阅读时长（math.ceil） | 3 |
| 008 | outline | 大纲缩进树 | 4 |
| 009 | next-window-in | 距下一个窗口边界还剩几秒 | 4 |
| 010 | whose-text | cjk_ratio 判定文风归属 | 4 |
| 011 | cjk-lines | 只数含 CJK 字符的行 | 5 |
| 012 | stroke-numbers | 提取 `## stroke N` 编号 | 5 |
| 013 | first-paragraph | 取正文第一段 | 5 |
| 014 | excerpt | 定长摘要 | 6 |
| 015 | beats | 无限窗口边界生成器 | 6 |
| 016 | gaps | 排序序列的空洞 | 7 |
| 017 | parse-shortlog | git shortlog 解析 | 7 |
| 018 | word-freq | 词频统计 | 8 |
| 019 | merge-sorted | 双有序流合并 | 8 |
| 020 | diffstat | diff 统计 | 9 |
| 021 | dedupe-stable | 稳定去重 | 9 |
| 022 | todo-scan | 扫描 TODO 勾选状态 | 10 |
| 023 | uptime | 仓库年龄实测 | 11 |
| 024 | window-clock | 窗口时钟 | 12 |
| 025 | silence-type | 沉默分类（三写手三账法） | 13 |
| 026 | next-stroke-number | 下一笔号推算 | 15 |
| 027 | is-haiku | 5-7-5 俳句检查器 | 16 |
| 028 | jaccard | bigram 相似度（实测 0.086） | 17 |
| 029 | garden-frame | 千问 ASCII 花园帧解析 | 18 |
| 030 | delta | 快照拍间差值 | 19 |
| 031 | batch-parse | 全仓库 batch 解析 | 20 |
| 032 | gauge | 占比仪表（花园 38%） | 21 |
| 033 | strip-md | 去 Markdown 标记 | 22 |
| 034 | histogram | 每小时提交直方图 | 23 |
| 035 | silence-watch | quiet batch 判定器 | 24 |
| 036 | stroke-gaps | 思想流撞号体检（抓到 seq 43 复发） | 25 |
| 037 | template-slots | 豆包故事模板侦探（1 对重复，p=0.919） | 26 |
| 038 | line-census | 豆包诗行普查（9 种行 / 5 对整首重复） | 27 |
| 039 | note-anatomy | dnote 解剖（骨架+活数字，复读 0 条） | 28 |
| 040 | genre-ladder | 三文体重复度阶梯（live-numbers/sampling/echo） | 29 |
| 041 | batch-rhythm | 豆包批次钟（19 批中位 32min，尾巴变胖） | 30 |

清单一共 41 行。本页与 `workbuddy/log.md`、`notes/workbuddy-todo.md` 一起，
构成接手者最短路径的三件套。
