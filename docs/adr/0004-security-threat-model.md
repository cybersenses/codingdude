# Security threat model: what the approval tiers do and don't defend against

CodingDude runs arbitrary model-chosen shell commands on the user's machine, gated by tiered approvals. This ADR records the actual security posture so nobody mistakes the heuristics for a sandbox.

**What we defend against (in scope):**
- Prompt-injection-driven *remote mutations*: `git push`, `gh pr create`, releases — always-gated; a pattern approval can never unlock them, only the interactive card or `--yolo`.
- Destructive filesystem operations (`rm`, deletions) — always-gated.
- Secret leakage to child processes: subprocess environments are scrubbed of variables matching KEY/TOKEN/SECRET/PASSWORD/CREDENTIAL, so a hallucinated `curl` can't exfiltrate provider keys from env.
- Path escape via file tools: all file operations resolve and must stay inside the Workdir.
- Network exposure: the server binds 127.0.0.1 with bearer/cookie auth.

**What we explicitly do NOT defend against (documented limits):**
- The shell tier check is a *heuristic regex*, not a sandbox. A compound command can reach outside the Workdir in ways the regex misses. The Workdir boundary is hard only for the file tools.
- Approved commands run with the user's full OS permissions. An approved `rm` is a real `rm`.
- `--yolo` disables all gating by explicit choice (ADR-0003); the Budget Cap is the only remaining brake.
- Web fetch allows localhost URLs so tests work — a malicious page can therefore probe local services if the agent is pointed at it.

**Future hardening options (deliberately deferred):** Windows Job Objects / containers for true filesystem and network isolation; per-command env allowlists instead of scrubbing; OS-level sandbox profiles. Revisit if CodingDude is ever run unattended (`--yolo` batch) on a machine with sensitive data.
