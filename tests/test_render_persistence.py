# Render capture persistence (R1 gap): image files a shell command creates
# are recorded per session in the DB, not just scannable on disk.

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from codingdude.approvals import ApprovalPolicy
from codingdude.config import load_config
from codingdude.engine import Engine


def shell_then_answer(command: str, check):
    def fn(messages, info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(
                parts=[ToolCallPart(tool_name='shell', args={'command': command})]
            )
        return ModelResponse(parts=[TextPart(content=check('done'))])

    return scripted(fn)


def scripted(fn):
    from pydantic_ai.models.function import FunctionModel

    model = FunctionModel(fn)
    return model


async def test_shell_created_image_is_recorded_in_db(home, workdir):
    from codingdude.db import Database

    engine = Engine(config=load_config(), db=Database.connect(home))
    policy = ApprovalPolicy(yolo=True)
    (workdir / 'shot.png').unlink(missing_ok=True)
    outcome = await engine.run(
        prompt='take a screenshot',
        workdir=workdir,
        model=shell_then_answer(
            'printf fake > shot.png', lambda t: 'ok' if t == 'done' else t
        ),
        approvals=policy,
    )
    assert outcome.output == 'ok'
    renders = engine._db.list_renders(
        # session id created inside run; single session in this home
        engine._db.list_sessions(workdir)[0].session_id
    )
    paths = [r['path'] for r in renders]
    assert paths == ['shot.png']
