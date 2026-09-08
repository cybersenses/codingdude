"""CodingDude exception taxonomy. Everything user-visible derives from the base."""


class CodingDudeError(Exception):
    """Base for all CodingDude-specific errors."""


class BudgetExceeded(CodingDudeError):
    """A Session crossed its Budget Cap; the run is hard-stopped."""

    def __init__(self, spent_usd: float, cap_usd: float):
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd
        super().__init__(
            f'Budget cap exceeded: ${spent_usd:.2f} spent (cap ${cap_usd:.2f})'
        )


class ConfigError(CodingDudeError):
    """Configuration is invalid or contradictory."""


class GateRequired(CodingDudeError):
    """An action needs Approval; the run pauses/aborts per ADR-0003."""

    def __init__(self, command: str):
        self.command = command
        super().__init__(f'gate required for: {command}')
