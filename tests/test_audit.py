"""Dependency audit tool: pip-audit / npm audit wrappers."""


async def test_audit_reports_no_manifests(home, tmp_path):
    from codingdude.tools import build_audit_toolset

    empty = tmp_path / 'empty'
    empty.mkdir()
    toolset = build_audit_toolset(empty)
    result = await toolset.tools['dependency_audit'].function()
    assert 'no supported project manifests' in result


async def test_audit_runs_on_project_with_manifest(home, tmp_path):
    from codingdude.tools import build_audit_toolset

    proj = tmp_path / 'proj'
    proj.mkdir()
    (proj / 'requirements.txt').write_text('requests==2.31.0\n')
    toolset = build_audit_toolset(proj)
    result = await toolset.tools['dependency_audit'].function()
    # Either a clean bill or findings — both are valid tool outcomes
    assert 'pip-audit' in result
