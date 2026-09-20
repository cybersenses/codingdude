# Marketing & Growth Checklist

As of: 2026-09-20
Sources: msitarzewski/agency-agents — marketing division (seo-specialist, growth-hacker, email-strategist, content-creator, pr-communications-manager, social-media-strategist; ~35 personas reviewed, platform-specific ones triaged)
https://github.com/msitarzewski/agency-agents/tree/main/marketing

Use when: building marketing automation, CMS/SEO features, email/campaign tooling, or growth features in a product. Platform-specific personas (TikTok/Douyin/WeChat/LinkedIn strategists) reduce to the same invariants.

## SEO / Search

- [ ] White-hat only: no link schemes, cloaking, keyword stuffing, hidden text — ever; these are product-reputation liabilities, not tactics.
- [ ] Keyword cannibalization check MANDATORY before any page optimization: no two pages target the same primary keyword; title/H1 uniqueness enforced per cluster.
- [ ] hreflang sets are reciprocal — every URL links back to all others, or search engines ignore the whole set.
- [ ] No mixed-language page without `lang` tagging; untagged bilingual pages serve neither audience and dilute both.
- [ ] Recommendations cite data (positions, CTR, crawl stats) — never vague ("improve content quality").

## Email / Lifecycle

- [ ] Segmentation over broadcast: every send carries a segment definition, exit conditions, and benchmark targets. No untargeted blasts.
- [ ] Deliverability gates: SPF/DKIM/DMARC configured; complaint rate < 0.10% target, 0.30% hard stop; bounce handling automated.
- [ ] Post-MPP measurement: open rates are directional only; build reporting on CTR, CTOR, conversion, revenue-per-email.
- [ ] Behavior-triggered sends preferred over batch (multiple-x open rates); lifecycle stages each have a defined sequence with duration.
- [ ] CRM↔ESP sync designed: attribute mapping, sync frequency, rate limiting, error handling — not a fire-and-forget integration.

## Product marketing & PR

- [ ] Every claim in copy traceable to a source or metric; unverifiable superlatives cut.
- [ ] Campaign launches have a measurement plan defined before send, not after.
- [ ] Crisis/PR: response drafted from facts on hand; speculation explicitly marked.
- [ ] Growth experiments: one variable per test, defined success metric, and a kill criterion decided before launch.

## Failure modes (observed in source personas)

- Broadcast sends to whole lists — segmentation treated as optional polish.
- Open-rate-optimized decisions after Apple MPP made opens unreliable.
- SEO changes made page-by-page without cluster/cannibalization check — pages compete against each other.
- Experiments run without kill criteria — sunk-cost campaigns.

## Rejected

- Per-platform content calendars and 25+ social-channel personas (Douyin, Kuaishou, Bilibili…) — channel tactics, not durable invariants; model already knows platform norms.
- Benchmarks quoted from source ("760% more revenue") without our own measurement plan.
