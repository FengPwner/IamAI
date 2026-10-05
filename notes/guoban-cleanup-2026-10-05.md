# guoban 整理记录（2026-10-05）

应仓库主人要求做了一次内容整理（选项 A）。

## 1. 合并两套内容文件

早期有一版「模板写手」用固定词库写、并把同一句反复落笔，留下三个重复很重的文件：
`guoban/notes.md`、`guoban/poems.md`、`guoban/thoughts.md`。

现已把这些内容**去重后并入**现行的三个文件（各加一节「旧版补录」）：

| 旧文件 | 并入 |
|---|---|
| `guoban/notes.md` | `guoban/guoban-note.md` |
| `guoban/poems.md` | `guoban/guoban-poem.md` |
| `guoban/thoughts.md` | `guoban/guoban-thought.md` |

随后删除了这三个旧文件。

## 2. 清理重复片段（`guoban/code/`）

模板写手把同一段代码重复落了好几次，而且 `020` 号被两个文件同时占用。每个片段保留一份：

- 保留：`008-window-index.py`、`012-chunk-append.py`、`020-read-token.py`、`026-sign-commit.py`、`028-stable-pick.py`
- 删除：`009-window-index.py`、`020-stable-pick.py`、`027-sign-commit.py`、`031-stable-pick.py`

## 3. 未改动

已推送的历史 commit 一律不改写——留着比抹掉更有价值。
