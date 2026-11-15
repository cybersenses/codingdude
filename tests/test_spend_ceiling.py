# CodingDude — a personal coding agent.
# Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""R94-B (#346): a spend ceiling that fires, not a post-hoc note.

Only *request counts* were ever bounded. A single enormous request, or a long
run of large ones, was unbounded in tokens and in money, and
``[delegation].max_cost_usd`` merely appended "(note: delegation cost ...
exceeded the configured cap)" to the tool output **after** the money was spent.

Ownership, decided here rather than left as a fourth accounting of the same
money: the **run** owns the hard stop (pydantic-ai checks the limit before the
next request), the **session** keeps the ledger-based Budget Cap over many
runs, and a **delegation** gets a *slice* of both — the R93 pattern, extended
to cost and tokens.

The last test pins the honest limit: ``cost_limit`` can only be enforced when
pydantic-ai can price the model. Where it cannot, it warns and enforces
nothing — so ``total_tokens_limit`` is the ceiling that actually holds on an
unpriced provider, and the code must not pretend otherwise.
"""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits

from codingdude.delegation import child_usage_limits, delegation_abort_message
from codingdude.run_pipeline import RunServices


def _services(**models):
    """A RunServices wired to a stub config — only `models` is read here."""
    base = dict(request_limit=500, max_cost_usd=None, max_total_tokens=None)
    base.update(models)
    return RunServices(
        config=SimpleNamespace(models=SimpleNamespace(**base)),
        db=None,
        config_home=Path('.'),
        extraction_model=lambda: None,
    )


# ---- the run owns the hard ceiling -------------------------------------


def test_a_run_carries_the_configured_cost_and_token_ceilings():
    limits = _services(max_cost_usd=2.5, max_total_tokens=100_000).usage_limits()
    assert limits.cost_limit == Decimal('2.5')
    assert limits.total_tokens_limit == 100_000


def test_no_ceiling_configured_means_no_ceiling():
    """Off by default: an unconfigured run must behave exactly as before."""
    limits = _services().usage_limits()
    assert limits.cost_limit is None
    assert limits.total_tokens_limit is None
    assert limits.request_limit == 500


def test_the_run_ceiling_fires_before_the_next_request():
    """The whole point of the ticket: the call is prevented, not narrated."""
    limits = _services(max_cost_usd=1).usage_limits()
    with pytest.raises(UsageLimitExceeded, match='cost_limit'):
        limits.check_before_request(RunUsage(requests=3, cost=Decimal('1.20')))


def test_a_run_under_the_ceiling_is_untouched():
    limits = _services(max_cost_usd=5, max_total_tokens=10_000).usage_limits()
    limits.check_before_request(RunUsage(requests=3, cost=Decimal('1.20')))


def test_the_message_names_the_limit_that_fired():
    """An operator must be able to tell which ceiling stopped the run."""
    limits = _services(max_total_tokens=1000).usage_limits()
    usage = RunUsage(requests=1, input_tokens=900, output_tokens=200)
    with pytest.raises(UsageLimitExceeded) as caught:
        limits.check_before_request(usage)
    assert 'total_tokens_limit' in str(caught.value)


# ---- the limit that holds when nothing can be priced -------------------


def test_the_token_ceiling_fires_without_any_pricing_data():
    """`cost_limit` needs a priced model; the token ceiling does not, so it is
    the ceiling that holds on a provider pydantic-ai cannot price."""
    limits = _services(max_total_tokens=1000).usage_limits()
    usage = RunUsage(requests=1, input_tokens=900, output_tokens=200)
    assert usage.cost is None
    with pytest.raises(UsageLimitExceeded, match='total_tokens_limit'):
        limits.check_before_request(usage)


def test_a_cost_ceiling_cannot_fire_without_pricing():
    """Documented ceiling, pinned so nobody claims a cap that does nothing.

    `check_before_request` simply cannot fire when `usage.cost` is None; the
    loop's `check_cost` is what surfaces it, and it emits the
    `CostNotFoundWarning` the docs name. Two different seams, so both are
    pinned here rather than one standing in for the other.
    """
    from pydantic_ai.exceptions import CostNotFoundWarning

    limits = _services(max_cost_usd=0.01).usage_limits()

    # The boundary check cannot raise: there is no cost to compare.
    limits.check_before_request(RunUsage(requests=1))

    # The loop's cost check says so out loud instead of passing silently.
    with pytest.warns(CostNotFoundWarning):
        limits.check_cost(RunUsage(requests=1))


def test_the_warning_names_the_reason_it_cannot_enforce():
    from pydantic_ai.exceptions import CostNotFoundWarning

    limits = _services(max_cost_usd=0.01).usage_limits()
    with pytest.warns(CostNotFoundWarning, match='cannot be enforced'):
        limits.check_cost(RunUsage(requests=1))


# ---- every agent seam carries the ceilings ---------------------------


@pytest.mark.parametrize(
    'module', ['evaluator.py', 'planning.py', 'run_pipeline.py']
)
def test_no_agent_seam_builds_ceiling_less_limits(module):
    """`UsageLimits(request_limit=...)` with nothing else was the R94 defect.

    The evaluator pass and the planning reviewer each built one, so a run could
    carry a cost ceiling while the agents it triggered spent without one. They
    must go through `limits.spend_limits`, the single definition.
    """
    source = (Path(__file__).resolve().parent.parent / 'src' / 'codingdude' / module)
    text = source.read_text(encoding='utf-8')
    assert 'UsageLimits(request_limit=' not in text, (
        f'{module} builds UsageLimits without the configured ceilings; '
        'use limits.spend_limits'
    )


#: Every agent call a run makes. Each must pass `usage_limits`, or a configured
#: ceiling silently does not apply to that seam (R94-B #346). Listed explicitly
#: as `(module, receiver, method)` rather than discovered: the main loop reaches
#: pydantic-ai through `agent.iter`, every other seam through `.run`, and the
#: guard's `assert calls` below turns a stale entry into a failure instead of a
#: silent pass. The fix loop is the seam this was written for — part of the run,
#: billed into it, and carrying no limits at all.
_SEAMS = [
    ('engine.py', 'agent', 'iter'),             # main loop
    ('engine.py', 'retry_agent', 'run'),        # fix loop
    ('evaluator.py', 'agent', 'run'),           # evaluator pass
    ('planning.py', 'reviewer', 'run'),         # planning reviewer
    ('run_pipeline.py', 'summarizer', 'run'),
    ('run_pipeline.py', 'agent', 'run'),        # memory extraction
    ('run_pipeline.py', 'auditor', 'run'),      # claims audit
    ('run_pipeline.py', 'retry_agent', 'run'),  # claims retry
    ('vision.py', 'agent', 'run'),
    ('tools.py', 'sub_agent', 'run'),           # delegation: a slice, not the run ceiling
]


@pytest.mark.parametrize(('module', 'receiver', 'method'), _SEAMS)
def test_every_agent_call_seam_passes_usage_limits(module, receiver, method):
    import ast

    root = Path(__file__).resolve().parent.parent / 'src' / 'codingdude'
    tree = ast.parse((root / module).read_text(encoding='utf-8'))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == method
        and ast.unparse(node.func.value).endswith(receiver)
    ]
    assert calls, f'{module}: no {receiver}.{method}(...) found — guard is blind'
    for node in calls:
        assert any(kw.arg == 'usage_limits' for kw in node.keywords), (
            f'{module}:{node.lineno} {receiver}.{method}() does not pass '
            'usage_limits — the run ceiling would not reach it'
        )


def test_the_delegation_config_cost_ceiling_is_validated_at_load(home):
    """`[delegation].max_cost_usd` had no validation, so `0` or `-1` silently
    meant "no cap" and `true` would blow up mid-delegation inside
    `Decimal(str(True))`. Both are load-time errors now."""
    from codingdude.config import load_config

    home.mkdir(parents=True)
    for bad in ('0', '-1', 'true', '"2.5"'):
        (home / 'config.toml').write_text(
            f'[delegation]\nmax_cost_usd = {bad}\n', encoding='utf-8'
        )
        with pytest.raises(ValueError, match='max_cost_usd'):
            load_config()


def test_the_config_panel_payload_carries_the_ceilings(home):
    """A GET -> PUT round-trip must not clear a configured cap.

    `models_payload` feeds the Config panel; omitting the keys means the panel
    cannot show them and an unchanged save wipes them.
    """
    from codingdude.config import load_config, models_payload

    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        '[models]\nmax_cost_usd = 2.5\nmax_total_tokens = 500000\n',
        encoding='utf-8',
    )
    payload = models_payload(load_config(home))['models']
    assert payload['max_cost_usd'] == 2.5
    assert payload['max_total_tokens'] == 500000


# ---- a delegation gets a slice of the same money ----------------------


def test_a_delegation_gets_a_cost_slice_not_a_fresh_grant():
    """Same reasoning as R93's request slice: the child shares the parent's
    accumulator, so its ceiling is `already spent + this slice`."""
    limits = child_usage_limits(
        3, UsageLimits(request_limit=100), 5,
        used_cost=Decimal('0.50'), max_cost_usd=0.25,
    )
    assert limits.cost_limit == Decimal('0.75')
    assert limits.request_limit == 8


def test_the_delegation_cost_slice_never_outruns_the_run_ceiling():
    parent = UsageLimits(request_limit=100, cost_limit=Decimal('0.60'))
    limits = child_usage_limits(
        3, parent, 5, used_cost=Decimal('0.50'), max_cost_usd=0.25,
    )
    assert limits.cost_limit == Decimal('0.60')


def test_a_float_parent_ceiling_comes_back_as_a_decimal():
    """`UsageLimits` keeps whatever type it is handed — `cost_limit=0.6` stays a
    float, it is not coerced — so the slice normalises rather than letting the
    returned ceiling's type depend on the caller. Every other ceiling this
    module builds is a Decimal."""
    parent = UsageLimits(request_limit=100, cost_limit=0.6)
    tighter_parent = child_usage_limits(
        3, parent, 5, used_cost=Decimal('0.50'), max_cost_usd=0.25,
    )
    tighter_slice = child_usage_limits(
        3, parent, 5, used_cost=Decimal('0.10'), max_cost_usd=0.25,
    )
    assert tighter_parent.cost_limit == Decimal('0.6')
    assert tighter_slice.cost_limit == Decimal('0.35')
    for limits in (tighter_parent, tighter_slice):
        assert isinstance(limits.cost_limit, Decimal)


def test_a_delegation_inherits_the_run_token_ceiling_when_it_has_no_slice():
    parent = UsageLimits(request_limit=100, total_tokens_limit=5000)
    limits = child_usage_limits(3, parent, 5)
    assert limits.total_tokens_limit == 5000


def test_a_delegation_slice_without_a_parent_still_bounds_the_cost():
    limits = child_usage_limits(
        0, None, 5, used_cost=None, max_cost_usd=2,
    )
    assert limits.cost_limit == Decimal('2')


# ---- the ceiling is configuration, so its parse is part of the contract ----


def test_the_ceilings_are_read_from_config_toml(home):
    from codingdude.config import load_config

    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        '[models]\nmax_cost_usd = 2.5\nmax_total_tokens = 500000\n',
        encoding='utf-8',
    )
    models = load_config().models
    assert models.max_cost_usd == 2.5
    assert models.max_total_tokens == 500000


def test_the_ceilings_default_to_no_ceiling(home):
    from codingdude.config import load_config

    models = load_config().models
    assert models.max_cost_usd is None
    assert models.max_total_tokens is None


@pytest.mark.parametrize('bad', ['true', '"2.5"', '0', '-1'])
def test_a_malformed_cost_ceiling_is_rejected_loudly(home, bad):
    """Loud, not degraded: a silently-ignored money cap is worse than no cap,
    because the operator believes they are protected. `true` is a bool (and
    `bool` is an `int` in Python, so it would otherwise mean a cap of 1) and
    `"2.5"` is a quoted-string typo — neither may become a ceiling.

    Note the distinction from a malformed *file*: broken TOML syntax degrades
    to defaults with a warning (pre-existing behaviour). This is well-formed
    TOML carrying a value that must not be read as a ceiling.
    """
    from codingdude.config import load_config

    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        f'[models]\nmax_cost_usd = {bad}\n', encoding='utf-8'
    )
    with pytest.raises(ValueError, match='max_cost_usd'):
        load_config()


@pytest.mark.parametrize('bad', ['true', '"500000"', '0', '1.5'])
def test_a_malformed_token_ceiling_is_rejected_loudly(home, bad):
    from codingdude.config import load_config

    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        f'[models]\nmax_total_tokens = {bad}\n', encoding='utf-8'
    )
    with pytest.raises(ValueError, match='max_total_tokens'):
        load_config()


def test_the_config_template_documents_the_ceilings(home):
    from codingdude.config import load_config

    load_config()
    template = (home / 'config.toml').read_text(encoding='utf-8')
    assert 'max_cost_usd' in template
    assert 'max_total_tokens' in template


def test_a_project_override_does_not_silently_drop_the_ceilings(home, tmp_path):
    """The blocker the two-axis review caught.

    `apply_project_models` rebuilds the lineup field by field. When it forgot the
    two new keys, any project with a `.codingdude.toml [models]` override reset
    both ceilings to None — a configured cap that vanished without a word, on
    exactly the projects that thought they had one.
    """
    from codingdude.config import apply_project_models, load_config

    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        '[models]\nmax_cost_usd = 2.5\nmax_total_tokens = 500000\n',
        encoding='utf-8',
    )
    (tmp_path / '.codingdude.toml').write_text(
        '[models]\nmain = "deepseek:deepseek-v4-flash"\n', encoding='utf-8'
    )
    merged = apply_project_models(load_config(home), tmp_path).models
    assert merged.main == 'deepseek:deepseek-v4-flash'   # the override applied
    assert merged.max_cost_usd == 2.5                    # …and the cap survived
    assert merged.max_total_tokens == 500000


def test_a_project_override_may_set_its_own_ceiling(home, tmp_path):
    from codingdude.config import apply_project_models, load_config

    home.mkdir(parents=True)
    (tmp_path / '.codingdude.toml').write_text(
        '[models]\nmax_total_tokens = 250000\n', encoding='utf-8'
    )
    merged = apply_project_models(load_config(home), tmp_path).models
    assert merged.max_total_tokens == 250000


# ---- one meaning for max_cost_usd -------------------------------------


def test_the_abort_message_names_the_cost_ceiling():
    """A cost ceiling must not be reported as a request-budget overrun."""
    message = delegation_abort_message(
        'The next request would exceed the `cost_limit` of 0.75 (`cost`=0.81)',
        UsageLimits(request_limit=100, cost_limit=Decimal('0.75')),
        used_requests=3,
        max_requests=40,
    )
    assert 'cost_limit' in message
    assert 'delegation budget of 40 model requests' not in message
    assert '[delegation].max_cost_usd' in message


def test_the_abort_message_names_the_token_ceiling():
    message = delegation_abort_message(
        'The next request would exceed the total_tokens_limit of 1000',
        UsageLimits(request_limit=100, total_tokens_limit=1000),
        used_requests=1,
        max_requests=40,
    )
    assert 'total_tokens_limit' in message
    assert '[models].max_total_tokens' in message


def test_the_request_abort_messages_are_unchanged():
    """The session-vs-slice distinction is the library's blind spot, so it is
    preserved verbatim rather than generalised away."""
    session_bound = delegation_abort_message(
        'The next request would exceed the request_limit of 2',
        UsageLimits(request_limit=2),
        used_requests=2,
        max_requests=40,
    )
    assert session_bound == (
        'delegation aborted: the session request limit of 2 was reached before '
        'the delegation slice of 40 could be spent. Raise [models].request_limit '
        'or split the task.'
    )
    slice_bound = delegation_abort_message(
        'The next request would exceed the request_limit of 42',
        UsageLimits(request_limit=42),
        used_requests=2,
        max_requests=40,
    )
    assert slice_bound == (
        'delegation aborted: exceeded the delegation budget of 40 model '
        'requests. Narrow the task and delegate again with a tighter question.'
    )


def test_the_post_hoc_cost_note_is_gone():
    """`max_cost_usd` must not mean two different things at once.

    It is now a ceiling; the "(note: delegation cost ... exceeded the
    configured cap)" string was the old receipt and its survival would leave
    two differently-behaving "caps" in the code.
    """
    import codingdude.tools as tools_module

    source = Path(tools_module.__file__).read_text(encoding='utf-8')
    assert 'exceeded the configured cap of' not in source
