# Game Development Checklist

As of: 2026-09-20
Sources: msitarzewski/agency-agents — game-development division (game-designer, economy-designer, narrative-designer, level-designer, game-audio-engineer, technical-artist, unity-architect, unity/godot-multiplayer-engineer, unreal-systems-engineer; 22 personas reviewed)
https://github.com/msitarzewski/agency-agents/tree/main/game-development

Use when: building games or game-adjacent systems (economy sims, multiplayer backends, interactive narrative). Engine-specific tactics noted; checks are engine-agnostic unless tagged.

## Design

- [ ] Define 3–5 design pillars: non-negotiable player experiences. Every feature traces to one.
- [ ] Name the "fun hypothesis" — the single thing that must feel good for the game to work. Prototype that first.
- [ ] Every mechanic documented with: purpose, player-experience goal, inputs, outputs, edge cases, failure states.
- [ ] Every system answers: what does the player feel? what decision are they making?
- [ ] No complexity without meaningful choice behind it.
- [ ] Economy: every variable (cost, reward, duration, cooldown) has a written rationale — no magic numbers; model faucet/drain balance and inflation over a play lifetime.
- [ ] Narrative/level: gate progression by taught skills, not by lore the player may skip.

## Multiplayer (all engines)

- [ ] Server owns all game-state truth — position, health, score, ownership. Clients send requests, never write state.
- [ ] Persistent replicated state vs one-time events: two distinct mechanisms; never mix them.
- [ ] Bandwidth: any per-frame replicated value needs a dirty-check; count updates/sec per client.
- [ ] Design for 200ms latency, not LAN — test every mechanic at real ping; interpolate/extrapolate on the client, decide on the server.
- [ ] Cheat surface enumerated: what does full client trust enable? (speed, teleport, item dupe, aim).
- [ ] Determinism plan for rollback/simulation if competitive.
- [ ] Authority model written down per subsystem before implementation.

## Engine specifics (Unity / Unreal / Godot)

- [ ] [Unreal] Per-frame logic in C++; Blueprint VM overhead is a liability at tick frequency.
- [ ] [Unreal] All UObject-derived pointers declared `UPROPERTY()` or expect surprise GC.
- [ ] [Unity/Godot] NetworkVariable/replication types chosen by update rate; profile bandwidth spikes.
- [ ] Shaders/tech-art: verify LODs, overdraw, and target-frame budget on min-spec hardware, not the dev rig.
- [ ] Audio: ducking/priority rules defined — more simultaneous sounds than voices is the normal case, not the exception.

## Failure modes (observed in source personas)

- Mechanics added because they're plausible, not because they serve a pillar.
- Client-authority shortcuts during prototyping that survive into production.
- Magic-number economies tuned by feel only — drift unplayable at month 3.
- Multiplayer tested on localhost only; 150ms-ping jitter discovered at launch.

## Rejected

- Engine tutorials and per-editor boilerplate (Roblox avatar pipelines, Blender add-on specifics, shader-graph node recipes) — platform docs cover these better than a checklist can.
- Persona rosters per engine (12 near-identical engine personas compress to the four checks above).
