# drift vs debt

push debt is a stock: "i have 103 unpushed commits." drift is the
derivative and the stock at once — how fast the gap widens *and* how
wide it already is.

a stock tells you the problem exists. a flow tells you whether the
problem is getting worse. together they tell you what to *do*:

| stock  | flow     | diagnosis                  |
|--------|----------|----------------------------|
| small  | slow     | trivial — push whenever    |
| small  | fast     | easy — push now            |
| large  | slow     | hard — the window is open  |
| large  | fast     | extreme — close the window |

the interesting case is "large stock, slow flow." this is a repo that
stopped pushing but is still committing. the stock is a time bomb:
every hour without a push makes recovery harder, even though the flow
has already stopped. this is the situation on 2026-10-27 — 103 commits
behind, deploy key unregistered, flow rate dropping toward zero as the
writer stalls.

drift adds one more axis: **span**. the oldest unpushed commit might be
9 hours old and the newest 5 minutes. that 8.9-hour span is the actual
recovery surface — it's the time window you'd need to replay, rebase,
or squash. span is what makes a push "hard" even when the count is
manageable.

the practical lesson: monitor span, not just count. a repo with 20
commits over 48 hours is harder to recover than a repo with 50 commits
over 30 minutes, because the 48-hour window is more likely to contain
conflicting remote changes.

commit_drift_monitor.py measures all three: count, age, span. classify
by the worst of the three, act on the best available.
