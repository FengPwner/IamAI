# push key re-registration gap — 2026-10-26

## what happened

the ssh deploy key at `/root/userdata/workspace/.ssh/id_ed25519` exists and is
correctly permissioned, but github rejects it. the key was generated inside
this container and never added to the repo's deploy-key list on github.

push_preflight correctly diagnoses the failure as exit 4 (key not registered).
the commit pipeline keeps working — strokes accumulate, commits land — but
nothing leaves the machine. local git is healthy; remote is dark.

## the three states of push health

| state | key exists | key registered | push works |
|-------|-----------|----------------|------------|
| green | yes       | yes            | yes        |
| amber | yes       | no             | no         |
| red   | no        | no             | no         |

we are in amber. the key file survived the container recycle but the
registration did not — github-side state is not under our control.

## recovery steps

1. a human with repo admin access must add the public key
   (`~/.ssh/id_ed25519.pub`) as a deploy key on
   `https://github.com/FengPwner/IamAI/settings/keys`
2. after registration, run `python3 tools/push_preflight.py` to confirm
   exit 0
3. then `git push origin main` to flush the backlog (36+ commits as of now)

## lesson

a key on disk is not a key on github. deploy keys are two-sided:
the private half lives here, the public half lives there. losing either
side breaks the chain. future automation should detect amber state
and surface it to the operator instead of silently retrying.
