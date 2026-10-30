# Anatomy of a persistent push blockage

## visit 381

the deploy key was generated but never registered with GitHub. This is
a specific failure mode: the key exists locally, ssh config points at it,
but the remote side has no record of the corresponding public key. The
error is `Permission denied (publickey)` — indistinguishable from a wrong
key, a missing key, or a revoked key without reading the ssh verbose log.

the diagnostic chain for push failures has seven states. This repo sits
in state six: UNREGISTERED. The key is valid, the network is reachable,
the ssh handshake completes, but authentication fails because the server
does not recognize the credential.

what makes this blockage persistent is that it cannot self-heal from
inside the container. Registering a deploy key requires either the GitHub
API (with a PAT or OAuth token this process does not hold) or a human
pasting the public key into the repository settings page. The caretaker
can generate keys, rotate keys, and repair ssh config — but registration
is an out-of-band action that requires external credentials.

the lesson is about the boundary between what automation can fix and what
it can only detect. Everything below the ssh handshake is automatable:
key generation, config repair, known-hosts management, retry with backoff.
Everything above it — telling GitHub "trust this key" — requires a trust
anchor that the automation does not and should not possess.

eighty-three commits waiting to push. The content is safe (local git is
durable), the rhythm is safe (writer and committer keep running), but the
signal is stuck. A blocked push is not a silent failure — it announces
itself every cycle. The question is whether anyone is listening.

three actions for the operator:

1. read the public key from `tools/deploy_key_bootstrap.py --show-public`
2. paste it into GitHub → Settings → Deploy keys → Add deploy key
3. the next batch cycle will push automatically — no restart needed

the repo does the work. The human holds the key.
