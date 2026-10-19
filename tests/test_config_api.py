"""Config-management API: GET/PUT /config/models - validated, secret-safe (R50 #208)."""

import tomllib

from fastapi.testclient import TestClient

from codingdude.config import config_home
from codingdude.server import create_app

TEST_TOKEN = "cd-" + "integration"


def client(tmp_path, monkeypatch=None):
    import os
    if monkeypatch is not None:
        monkeypatch.setenv('CODEDUDE_HOME', str(tmp_path / 'home'))
    else:
        os.environ['CODEDUDE_HOME'] = str(tmp_path / 'home')
    app = create_app(home=tmp_path / "home", token=TEST_TOKEN, allow_testclient=True)
    return TestClient(app, headers={"Authorization": f"Bearer {TEST_TOKEN}"})


def test_get_returns_lineup_and_provider_presence(tmp_path, monkeypatch):
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    c = client(tmp_path)
    r = c.get("/config/models")
    assert r.status_code == 200
    body = r.json()
    assert body["models"]["main"]  # defaults present
    assert body["models"]["request_limit"] >= 1
    assert body["thinking_levels"] == ["minimal", "low", "medium", "high", "xhigh"]
    # providers: presence booleans only - never values
    assert set(body["providers"]) == {"deepseek", "zai", "github"}
    assert all(isinstance(v, bool) for v in body["providers"].values())


def test_get_never_leaks_provider_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "sk-secret-value")
    c = client(tmp_path)
    raw = c.get("/config/models").text
    assert "sk-secret-value" not in raw


def test_put_roundtrip_writes_valid_toml(tmp_path, monkeypatch):
    c = client(tmp_path)
    lineup = c.get("/config/models").json()["models"]
    lineup["main"] = "zai:glm-5.3"
    lineup["thinking"] = "low"
    lineup["pricing"] = {"glm-5.3": {"input": 0.5, "output": 2.0}}
    r = c.put("/config/models", json={"models": lineup})
    assert r.status_code == 200, r.text
    assert r.json()["saved"]["main"] == "zai:glm-5.3"

    cfg_path = config_home() / "config.toml"
    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    assert raw["models"]["main"] == "zai:glm-5.3"
    assert raw["models"]["thinking"] == "low"
    assert raw["models"]["pricing"]["glm-5.3"]["output"] == 2.0

    # GET reflects the save
    assert c.get("/config/models").json()["models"]["thinking"] == "low"


def test_put_preserves_other_sections(tmp_path):
    c = client(tmp_path)
    cfg = config_home() / "config.toml"
    cfg.write_text(
        "[models]\nmain = \"deepseek:deepseek-v4-pro\"\n"
        "[shell]\ndefault = \"powershell\"\n"
        "[delegation]\nmax_cost_usd = 5.0\n"
        "[providers]\nzai = \"stored-key\"\n",
        encoding="utf-8",
    )
    lineup = c.get("/config/models").json()["models"]
    lineup["main"] = "zai:glm-5.3"
    assert c.put("/config/models", json={"models": lineup}).status_code == 200
    raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert raw["shell"]["default"] == "powershell"
    assert raw["delegation"]["max_cost_usd"] == 5.0
    assert raw["providers"]["zai"] == "stored-key"


def test_put_rejects_bad_thinking(tmp_path):
    c = client(tmp_path)
    lineup = c.get("/config/models").json()["models"]
    lineup["thinking"] = "ultra"
    r = c.put("/config/models", json={"models": lineup})
    assert r.status_code == 422
    assert "thinking" in r.json()["detail"]


def test_put_rejects_model_without_provider(tmp_path):
    c = client(tmp_path)
    lineup = c.get("/config/models").json()["models"]
    lineup["fallback"] = "just-a-model-name"
    r = c.put("/config/models", json={"models": lineup})
    assert r.status_code == 422
    assert "provider:model" in r.json()["detail"]


def test_put_rejects_bad_pricing_shape(tmp_path):
    c = client(tmp_path)
    lineup = c.get("/config/models").json()["models"]
    lineup["pricing"] = {"m": {"input": "cheap"}}
    r = c.put("/config/models", json={"models": lineup})
    assert r.status_code == 422


def test_put_rejects_negative_request_limit(tmp_path):
    c = client(tmp_path)
    lineup = c.get("/config/models").json()["models"]
    lineup["request_limit"] = 0
    r = c.put("/config/models", json={"models": lineup})
    assert r.status_code == 422


def test_put_rejects_unknown_fields(tmp_path):
    c = client(tmp_path)
    r = c.put("/config/models", json={"models": {"main": "zai:g", "bogus": 1}})
    assert r.status_code == 422
