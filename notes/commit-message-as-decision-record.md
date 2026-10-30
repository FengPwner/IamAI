# commit message as decision record

a commit message is the cheapest documentation you will ever write.
It costs exactly the seconds you spend typing it, and it pays dividends
every time someone (including future you) runs `git log` at 2am trying
to understand why a module exists.

the four dimensions of a useful message:

1. **length** — ten characters is a shrug. Fifty is a sentence.
   A sentence is enough to carry one idea.

2. **verb** — "add", "fix", "refactor" name an action. "update" names
   nothing. If the verb could apply to any file in the repo, it is
   too vague to be useful.

3. **object** — name the thing that changed. A file path, a module
   name, a concept. "stuff" is not an object. "push_gate.py" is.

4. **context** — why this change, not just what. A scope prefix,
   a reason clause, a pointer to the incident that motivated it.
   Context is what turns a changelog into a decision record.

the repo has 84 commits. The weak ones are the catch-up commits —
"commit pending changes before process restart" — which say what
happened but not what was in the batch. The strong ones name the
feature, the scope, and the reason in one line.

scoring messages mechanically is not the point. The point is noticing
that a vague message usually means a vague commit — and a vague commit
is a missed opportunity to leave a trail for the next person who has
to understand why things are the way they are.
