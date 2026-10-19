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
"""R16: delegation task briefs — verified symbols + contract excerpt."""

from codingdude.delegation import (
    DelegationBrief,
    brief_prompt,
    build_brief,
    candidate_symbols,
)


def _make_repo(tmp_path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'auth.py').write_text('def loginUser(): ...\n')
    (tmp_path / 'docs' / 'specs').mkdir(parents=True)
    (tmp_path / 'docs' / 'specs' / 'R1-auth.md').write_text(
        '# R1 auth\n\n## Contract\n- codingdude.auth.loginUser\n'
    )


def test_candidate_symbols_are_identifier_tokens():
    toks = candidate_symbols('check loginUser and _run_captured in tools.py')
    assert 'loginUser' in toks and '_run_captured' in toks
    assert len(toks) == len(set(toks))


def test_build_brief_verifies_symbols_against_workdir(tmp_path):
    _make_repo(tmp_path)
    brief = build_brief('inspect loginUser please', tmp_path, budget=40)
    assert brief.symbols == ['loginUser']  # 'inspect'/'please' don't exist
    assert brief.budget == 40


def test_build_brief_pulls_contract_mentioning_symbol(tmp_path):
    _make_repo(tmp_path)
    brief = build_brief('review loginUser', tmp_path, budget=40)
    assert brief.contract is not None
    assert 'loginUser' in brief.contract
    assert brief.contract_source == 'docs/specs/R1-auth.md'


def test_build_brief_no_contract_without_matching_symbol(tmp_path):
    _make_repo(tmp_path)
    brief = build_brief('unrelated work only', tmp_path, budget=40)
    assert brief.symbols == []
    assert brief.contract is None


def test_brief_prompt_bare_task_when_no_context():
    brief = DelegationBrief(task='do the thing', budget=40)
    assert brief_prompt(brief) == 'do the thing'


def test_brief_prompt_includes_symbols_and_contract():
    brief = DelegationBrief(
        task='review loginUser', budget=40, symbols=['loginUser'],
        contract='- codingdude.auth.loginUser',
        contract_source='docs/specs/R1-auth.md',
    )
    out = brief_prompt(brief)
    assert out.startswith('review loginUser')
    assert 'Relevant symbols: loginUser' in out
    assert 'docs/specs/R1-auth.md' in out
    assert 'codingdude.auth.loginUser' in out
