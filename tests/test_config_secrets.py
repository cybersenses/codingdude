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
"""Settings secret round-trip: sentinel masking, provider-key PUT, auth smoke (R50 #211)."""

import json
import tomllib

from fastapi.testclient import TestClient

from codingdude.config import config_home
from codingdude.server import create_app

TEST_TOKEN = "cd-" + "integration"
CODING_PLAN_URL = "https://api.z.ai/api/coding/paas/v4"


def client(tmp_path):
    import os

    os.environ["CODEDUDE_HOME"] = str(tmp_path / "home")
    app = create_app(home=tmp_path / "home", token=TEST_TOKEN, allow_testclient=True)
    return TestClient(app, headers={"Authorization": f"Bearer {TEST_TOKEN}"})


def seed_coding_plan(cfg):
    cfg.write_text(
        '[models]\nmain = "deepseek:deepseek-v4-pro"\nfallback = "zai:glm-5.3"\n'
        f'fallback_base_url = "{CODING_PLAN_URL}"\nthinking = "low"\n',
        encoding="utf-8")


def test_sentinel_roundtrip_does_not_clobber_provider_key(tmp_path):
    """The exact incident class from handback #2: UI echoes the masked value
    back; the PUT must ignore it, not store the mask over the real key."""
    c = client(tmp_path)
    cfg = config_home() / "config.toml"
    c.put("/config/models", json={"providers": {"zai": "sk-real-live-key"}})
    mask = c.get("/config/models").json()["providers"]["zai"]
    assert mask == "__codingdude_key_set__"
    # round-trip: GET payload echoed straight back
    r = c.put("/config/models", json={"providers": {"zai": mask}})
    assert r.status_code == 200, r.text
    raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert raw["providers"]["zai"] == "sk-real-live-key"


def test_put_provider_null_clears_and_value_sets(tmp_path):
    c = client(tmp_path)
    cfg = config_home() / "config.toml"
    r = c.put("/config/models", json={"providers": {"github": "ghp_x", "deepseek": "sk-d"}})
    assert r.status_code == 200, r.text
    raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert raw["providers"] == {"github": "ghp_x", "deepseek": "sk-d"}
    # clear one, keep the other
    r = c.put("/config/models", json={"providers": {"deepseek": None}})
    assert r.status_code == 200, r.text
    raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert raw["providers"] == {"github": "ghp_x"}


def test_put_provider_accepts_any_name_and_preserves_models(tmp_path):
    c = client(tmp_path)
    cfg = config_home() / "config.toml"
    seed_coding_plan(cfg)
    # #212: any provider name is storable — users define their own providers.
    r = c.put("/config/models", json={"providers": {"openrouter": "stored-or"}})
    assert r.status_code == 200, r.text
    raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert raw["providers"]["openrouter"] == "stored-or"
    assert raw["models"]["fallback_base_url"] == CODING_PLAN_URL  # untouched


def test_verify_reports_auth_failure_without_leaking_key(tmp_path, monkeypatch):
    from codingdude.config import load_config, verify_provider_keys

    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    cfg_path = config_home() / "config.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        '[models]\nmain = "deepseek:x"\nsubagent = "deepseek:x"\nfallback = "zai:y"\n'
        '[providers]\nzai = "sk-clobbered"\n', encoding="utf-8")

    calls = []

    def fake_transport(url, headers, body):
        calls.append((url, headers))
        return (401, '{"error":"token expired or incorrect"}')

    results = verify_provider_keys(load_config(config_home()), transport=fake_transport)
    assert results["zai"] == {
        "configured": True, "ok": False, "status": 401,
        "detail": '{"error":"token expired or incorrect"}',
    }
    # unconfigured providers are simply absent (#212)
    assert "deepseek" not in results
    # smoke hits the standard endpoint when no base url is configured
    assert calls[0][0].startswith("https://api.z.ai/api/paas/v4/chat/completions")
    assert "sk-clobbered" not in json.dumps(results)


def test_verify_ok_on_200_and_plan_model_mismatch(tmp_path, monkeypatch):
    from codingdude.config import load_config, verify_provider_keys

    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    cfg_path = config_home() / "config.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        '[models]\nmain = "deepseek:x"\nsubagent = "deepseek:x"\nfallback = "zai:y"\n'
        f'fallback_base_url = "{CODING_PLAN_URL}"\n'
        '[providers]\nzai = "sk-good"\ndeepseek = "sk-d"\n', encoding="utf-8")

    seen = {}

    def fake_transport(url, headers, body):
        seen[url] = 404 if "z.ai" in url else 200
        return (seen[url], "{}")

    results = verify_provider_keys(load_config(config_home()), transport=fake_transport)
    assert results["zai"]["ok"] is True   # 404: auth passed, smoke model not on plan
    assert results["deepseek"]["ok"] is True
    assert any("coding/paas" in u for u in seen)


def test_config_verify_route_never_echoes_keys(tmp_path, monkeypatch):
    """GET /config/verify is wired and never echoes key material."""
    c = client(tmp_path)
    c.put("/config/models", json={"providers": {"github": "ghp_whatever"}})
    monkeypatch.setattr(
        "codingdude.config.verify_provider_keys",
        lambda cfg, timeout_s=8.0, transport=None: {
            "github": {"configured": True, "ok": False, "status": 401,
                       "detail": "Bad credentials"}},
    )
    r = c.get("/config/verify")
    assert r.status_code == 200
    assert r.json()["providers"]["github"]["ok"] is False
    assert "ghp_whatever" not in r.text
