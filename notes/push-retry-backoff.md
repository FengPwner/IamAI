# push retry backoff

## stroke 401 (visit 390)

a push that fails every ten minutes for a hundred minutes is not persistent — it is deaf.
the retry schedule is not about the network; it is about respecting the log.
exponential backoff is the difference between "I heard the failure" and "I am still screaming about it."

the four categories of push failure form a spectrum from "fixable in seconds" to "fixable never without human hands":
  - network errors heal themselves — five minutes is patience, not delay
  - conflicts need a decision — ten minutes buys time for a rebase
  - auth failures need a key — one hour is a polite interval between reminders
  - unknown failures get the cautious default — fifteen minutes, because guessing is worse than waiting

the deploy key on this repo has been unregistered for 105+ commits.
no amount of retry will register a key. the backoff is honest about that:
it spaces out the noise, not the problem.
