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
"""Config-management API: GET/PUT /config/models - validated, secret-safe (R50 #208)."""

import tomllib

from fastapi.testclient import TestClient

from codingdude.config import config_home
from codingdude.server import create_app

TEST_TOKEN = "cd-" + "integration"


def client(tmp_path):
    import os

    os.environ["CODEDUDE_HOME"] = str(tmp_path / "home")
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
    # providers: SECRET_MASK sentinel or None only - never values; only
    # configured providers appear (#212); built-in trio stays suggested
    assert set(body["provider_prefixes"]) >= {"deepseek", "zai", "github"}
    assert all(v in (None, "__codingdude_key_set__") for v in body["providers"].values())


def test_get_never_leaks_provider_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "sk-secret-value")
    c = client(tmp_path)
    raw = c.get("/config/models").text
    assert "sk-secret-value" not in raw


def test_put_roundtrip_writes_valid_toml(tmp_path):
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
        '[models]\nmain = "deepseek:deepseek-v4-pro"\n'
        '[shell]\ndefault = "powershell"\n'
        '[delegation]\nmax_cost_usd = 5.0\n'
        '[providers]\nzai = "stored-key"\n',
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


CODING_PLAN_URL = "https://api.z.ai/api/coding/paas/v4"


def seed_coding_plan(cfg_path):
    cfg_path.write_text(
        '[models]\nmain = "deepseek:deepseek-v4-pro"\n'
        'fallback = "zai:glm-5.3"\n'
        f'fallback_base_url = "{CODING_PLAN_URL}"\n'
        'thinking = "low"\n',
        encoding="utf-8",
    )


def test_put_partial_save_keeps_coding_plan_endpoint(tmp_path):
    """Regression: a save that omits a field must not delete its stored value.

    The UI posts only what it renders; replacing the whole [models] table on
    every save silently erased the GLM coding-plan endpoint, dropping z.ai
    back to the standard API (wrong plan / rejected key).
    """
    c = client(tmp_path)
    cfg = config_home() / "config.toml"
    seed_coding_plan(cfg)
    r = c.put("/config/models", json={"models": {"main": "deepseek:deepseek-v4-pro"}})
    assert r.status_code == 200, r.text
    raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert raw["models"]["fallback_base_url"] == CODING_PLAN_URL
    assert raw["models"]["thinking"] == "low"
    assert raw["models"]["fallback"] == "zai:glm-5.3"
    assert r.json()["effective"]["models"]["fallback_base_url"] == CODING_PLAN_URL


def test_put_null_clears_only_that_field(tmp_path):
    c = client(tmp_path)
    cfg = config_home() / "config.toml"
    seed_coding_plan(cfg)
    r = c.put("/config/models", json={"models": {"fallback_base_url": None}})
    assert r.status_code == 200, r.text
    raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert "fallback_base_url" not in raw["models"]
    assert raw["models"]["fallback"] == "zai:glm-5.3"  # untouched by the clear


def test_get_warns_when_zai_fallback_lacks_coding_plan_endpoint(tmp_path):
    c = client(tmp_path)
    cfg = config_home() / "config.toml"
    cfg.write_text('[models]\nfallback = "zai:glm-5.3"\n', encoding="utf-8")
    body = c.get("/config/models").json()
    assert any("coding" in w.lower() for w in body["warnings"])

    c.put("/config/models", json={"models": {"fallback_base_url": CODING_PLAN_URL}})
    assert c.get("/config/models").json()["warnings"] == []


# ---- #321: reachable-model listing for the lineup slot picker ----


def _write_providers(text):
    cfg = config_home() / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(text, encoding="utf-8")


def test_provider_models_lists_reachable_models(tmp_path, monkeypatch):
    """#321: one GET {root}/models per OpenAI-compatible provider with the
    effective key; ids ride back sorted; the endpoint never echoes secrets."""
    import json

    from codingdude.config import list_provider_models, load_config

    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client(tmp_path)
    _write_providers('[providers]\ndeepseek = "sk-d"\n')

    calls = []

    def fake_transport(url, headers, body):
        calls.append((url, headers.get("Authorization"), body))
        return (200, json.dumps(
            {"data": [{"id": "deepseek-v4-pro"}, {"id": "deepseek-v4-flash"}]}))

    out = list_provider_models(load_config(config_home()), transport=fake_transport)
    assert out["deepseek"] == {
        "configured": True, "ok": True, "status": 200, "detail": None,
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
    }
    # catalog root + GET with a Bearer header, no body — the smoke contract
    assert calls == [("https://api.deepseek.com/v1/models", "Bearer sk-d", None)]


def test_config_provider_models_route_never_echoes_keys(tmp_path, monkeypatch):
    """GET /config/provider-models is wired and never echoes key material
    (route test mirrors test_config_verify_route_never_echoes_keys; the
    function-level tests above carry the listing logic)."""
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    c = client(tmp_path)
    c.put("/config/models", json={"providers": {"deepseek": "sk-live-secret"}})
    monkeypatch.setattr(
        "codingdude.config.list_provider_models",
        lambda cfg, timeout_s=10.0, transport=None: {
            "deepseek": {"configured": True, "ok": False, "status": 401,
                         "detail": '{"error":"invalid key"}', "models": []},
        })
    r = c.get("/config/provider-models")
    assert r.status_code == 200
    assert r.json()["providers"]["deepseek"]["configured"] is True
    assert "sk-live-secret" not in r.text


def test_provider_models_native_provider_reported_not_listed(tmp_path, monkeypatch):
    """Q4: anthropic/google have no OpenAI-compatible endpoint in the catalog —
    reported ok None with an empty list (free-text stays), no request fires."""
    from codingdude.config import list_provider_models, load_config

    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    client(tmp_path)
    _write_providers('[providers]\nanthropic = "sk-ant"\n')

    calls = []

    def fake_transport(url, headers, body):
        calls.append(url)
        return (200, "{}")

    out = list_provider_models(load_config(config_home()), transport=fake_transport)
    assert calls == []
    assert out["anthropic"]["ok"] is None
    assert out["anthropic"]["models"] == []
    assert out["anthropic"]["configured"] is True


def test_provider_models_transport_error_is_per_provider(tmp_path, monkeypatch):
    """One dead endpoint must not blind the others: ok False + empty models
    for the failed provider, its neighbours still list."""
    import json

    from codingdude.config import list_provider_models, load_config

    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    client(tmp_path)
    _write_providers('[providers]\ndeepseek = "sk-d"\nopenai = "sk-o"\n')

    def fake_transport(url, headers, body):
        if "deepseek" in url:
            return (0, "getaddrinfo failed")
        return (200, json.dumps({"data": [{"id": "gpt-4o"}]}))

    out = list_provider_models(load_config(config_home()), transport=fake_transport)
    assert out["deepseek"]["ok"] is False
    assert out["deepseek"]["models"] == []
    assert "getaddrinfo failed" in out["deepseek"]["detail"]
    assert out["openai"]["ok"] is True
    assert out["openai"]["models"] == ["gpt-4o"]


def test_provider_models_keyless_local_provider_fetches_without_auth(
        tmp_path, monkeypatch):
    """ollama (needs_key False): no key is fine — fetch with no Authorization
    header. A keyless provider that needs a key is reported unconfigured and
    never requested."""
    import json

    from codingdude.config import list_provider_models, load_config

    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    client(tmp_path)
    _write_providers(
        '[providers.ollama]\nbase_url = "http://localhost:11434/v1"\n'
        '[providers.deepseek]\nenv_var = "DEEPSEEK_X"\n')

    calls = []

    def fake_transport(url, headers, body):
        calls.append((url, headers.get("Authorization")))
        return (200, json.dumps({"data": [{"id": "llama3:8b"}]}))

    out = list_provider_models(load_config(config_home()), transport=fake_transport)
    assert calls == [("http://localhost:11434/v1/models", None)]
    assert out["ollama"]["models"] == ["llama3:8b"]
    assert out["deepseek"]["configured"] is False
    assert out["deepseek"]["models"] == []


def test_provider_models_includes_legacy_env_only_provider(tmp_path, monkeypatch):
    """The legacy trio rides on env vars alone (verify_provider_keys
    precedent): ZAI_API_KEY set with no [providers] entry still lists."""
    import json

    from codingdude.config import list_provider_models, load_config

    monkeypatch.setenv("ZAI_API_KEY", "sk-z-env")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    client(tmp_path)
    _write_providers("")

    calls = []

    def fake_transport(url, headers, body):
        calls.append((url, headers.get("Authorization")))
        return (200, json.dumps({"data": [{"id": "glm-5.3-flash"}]}))

    out = list_provider_models(load_config(config_home()), transport=fake_transport)
    assert ("https://api.z.ai/api/paas/v4/models", "Bearer sk-z-env") in calls
    assert out["zai"]["models"] == ["glm-5.3-flash"]
