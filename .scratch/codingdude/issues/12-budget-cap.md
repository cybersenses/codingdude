# 12: Budget Cap

**What to build:** The runaway-loop brake. An optional per-Session spending cap, off by default, settable in the UI; the engine hard-stops the run when spend crosses it, with a clear final event; the cost meter is visible throughout. `--yolo` does not bypass the cap.

**Blocked by:** 05 (Session lifecycle), 09 (React shell)

**Status:** ready-for-agent

- [ ] With no cap set, runs behave exactly as before
- [ ] Setting a cap (UI) then driving a scripted spendy run hard-stops at the cap with a distinct final event
- [ ] The cost meter reflects accumulating spend across the Session
- [ ] `--yolo` runs still stop at the cap
