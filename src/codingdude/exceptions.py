"""CodingDude-specific exceptions surfaced to frontends and exit codes."""


class BudgetExceeded(Exception):
    """A Session crossed its Budget Cap; the run is hard-stopped."""

    def __init__(self, spent_usd: float, cap_usd: float):
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd
        super().__init__(
            f'Budget cap exceeded: ${spent_usd:.2f} spent (cap ${cap_usd:.2f})'
        )
