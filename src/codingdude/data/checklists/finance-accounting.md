# Finance & Accounting Checklist

As of: 2026-09-20
Sources: msitarzewski/agency-agents — finance-bookkeeper-controller, finance-financial-analyst, finance-fpa-analyst, finance-investment-researcher, finance-tax-strategist
https://github.com/msitarzewski/agency-agents/tree/main/finance

Use when: building accounting/ledger software, billing reconciliation, financial reporting, budgeting/forecasting features, or investment-analysis tools. Pairs with checklists/payments-billing.md (money movement) — this covers the books.

## Checklist

- [ ] GAAP baseline: every transaction recorded per applicable standards; no exceptions, no shortcuts.
- [ ] Reconcile every balance-sheet account every period; an unreconciled balance is a defect, not a backlog item.
- [ ] Segregation of duties enforced in the data model: initiator ≠ approver ≠ recorder (role checks, not conventions).
- [ ] Every manual journal entry requires description + supporting documentation + approval before posting.
- [ ] Materiality guides urgency, not whether you investigate — trace small discrepancies to cause too.
- [ ] Never adjust prior periods silently; corrections to reported numbers carry documented disclosure.
- [ ] Close on a published schedule; delays cascade and erode trust in every downstream report.
- [ ] Immutability: posted entries are append-only; corrections are reversing entries, never edits.
- [ ] Audit readiness is a daily state — any balance producible with support within 24h.
- [ ] Driver-based forecasting: financial outputs linked to operational inputs (revenue/rep, cost/hire); name assumptions and trigger points per scenario.
- [ ] Variance analysis decomposes budget-vs-actual to root cause, not just magnitude.
- [ ] Unit economics first-class: CAC, LTV, payback, contribution margin by segment/product/channel.
- [ ] Cash flow projected separately from P&L — profitable companies die of cash starvation.
- [ ] Tax positions documented with authority citations; estimated payments calendarized.
- [ ] Investment claims quantified: thesis, valuation basis, downside case, and what would falsify the thesis.

## Failure modes (observed in source personas)

- Fast close prioritized over accurate close — speed without accuracy is noise delivered faster.
- "Adjusting entry" used as a journal-entry description (no documentation, no approval trail).
- Spreadsheet models without data validation or scenario switches — silently wrong under input drift.
- Forecast accuracy never measured, so calibration never improves.

## Rejected

- Excel-as-system-of-record patterns; vendor lists (Anaplan/Tableau/NetSuite) — tool-agnostic checks only.
- Persona voice, fake memory, industry-specific templates (AOP board decks) — kept the invariants, dropped the documents.
