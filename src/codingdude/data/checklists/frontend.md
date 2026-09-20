# Frontend checklist

As of: 2026-09-20
Source: https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-frontend-developer.md
Use when: building or reviewing a web frontend.

## Checklist
- [ ] Core Web Vitals budgeted from the start: LCP < 2.5s, INP/FID < 100-200ms, CLS < 0.1.
- [ ] Code splitting + lazy loading for routes/heavy components; bundle size tracked (performance budgets in CI).
- [ ] Images optimized: modern formats (WebP/AVIF), responsive sizing, lazy-loaded below the fold.
- [ ] Accessibility: WCAG 2.1 AA — semantic HTML first, ARIA only where semantics can't express it, full keyboard navigation, visible focus, contrast, `prefers-reduced-motion` respected.
- [ ] Lists rendering large datasets virtualized.
- [ ] Mobile-first responsive design; tested on real device widths.
- [ ] State management chosen to fit app complexity (local state → context → store); no global store by default.
- [ ] Error handling with user-visible feedback (not silent failures, not console-only).
- [ ] Component tests for behavior + e2e tests for critical flows; lint gate in CI.
- [ ] Zero console errors in production; real-user monitoring if traffic justifies.

## Failure modes
- Accessibility retrofitted after launch — ARIA sprinkled on div soup instead of semantic HTML.
- Layout shift from unreserved image/ad space (CLS).
- Bundle bloat: one giant chunk, everything imported eagerly.
- Undefined identifiers crashing at runtime — bundlers don't catch them; lint must gate (lesson from our own repo).

## Rejected
- Framework choice essays, PWA/service-worker boilerplate, editor-integration niche.
