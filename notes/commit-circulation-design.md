# commit-circulation — 2026-11-10

写了一个 commit_circulation 模块，衡量变更在代码库不同区域之间的流通程度：

- cross_area_ratio：一次 commit 同时触碰 ≥2 个顶层目录的比例
- area_coupling：相邻 commit 的区域集合的 Jaccard 相似度均值，衡量"每次改动的形状"是否稳定
- reach_breadth：被多个 commit 共同触碰的区域占全部区域的比例（共享区域比）
- bridge_commit_ratio：首次连接两个此前从未在同一 commit 出现过的区域的 commit 比例

设计思路：一个健康的项目不应该每个模块都在自己的气泡里演化。core 改了，
tests 和 docs 应该跟着动；如果长期只有 iamai/ 自己在变，而 tests/ 和
docs/ 各走各的，说明知识没有在区域之间流通——silo 在形成。

分类体系：
- interconnected (≥0.80)：几乎每个 commit 都跨域
- flowing (0.60–0.79)：良好的跨域传粉，偶尔有单域批次
- adequate (0.40–0.59)：混合状态
- siloed (0.20–0.39)：多数 commit 停留在一个区域内
- isolated (<0.20)：区域完全独立演化

这个模块和 commit_memory（记忆）以及 commit_metabolism（代谢）形成互补：
记忆衡量"是否记得过去"，代谢衡量"吸收是否高效"，循环衡量"知识是否流动"。
三者一起构成代码库健康度的三个维度：记住、吸收、传播。
