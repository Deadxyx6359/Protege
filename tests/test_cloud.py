"""Claude through Anthropic's API: what is sent, to where, with which key, and what
comes back, with the network a stand-in."""

from __future__ import annotations

import json

import pytest

from akira.core import cloud
from akira.core.models import Route
from akira.core.net import client as net
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.models.base import ChatMessage, ModelError, ModelUnavailable

from test_net_call import Reply, Wire

KEY = "sk-ant-api03-" + "x" * 40


def reply(body: dict, status=200, reason="OK"):
    return Reply(status, json.dumps(body).encode(), {"Content-Type": "application/json"},
                 reason=reason)


PUBLIC = "160.79.104.10"


ANSWERED = {"content": [{"type": "thinking", "thinking": ""},
                        {"type": "text", "text": "Use SPI1 on PA5 and PA7."}],
            "stop_reason": "end_turn", "usage": {"input_tokens": 1200, "output_tokens": 300}}


@pytest.fixture
def anthropic(monkeypatch):
    def install(answer):
        site = Wire({("api.anthropic.com", "/v1/messages"): answer,
                     ("api.anthropic.com", "/v1/models/claude-opus-5-5"): answer})
        monkeypatch.setattr(net, "_resolve", lambda host, port: [PUBLIC])
        monkeypatch.setattr(net, "_open", site.open)
        return site
    return install


def claude(tmp_path, *, granted=True, key=True):
    policy = Policy()
    if granted:
        policy.grant("model.cloud", ("anthropic",))
    secrets = SecretStore(tmp_path / "secrets")
    if key:
        secrets.put(cloud.SECRET, KEY)
    return cloud.Claude(policy=lambda: policy, secrets=secrets,
                        audit=AuditLog(tmp_path / "audit.jsonl"),
                        spend=cloud.Spend(tmp_path / "cloud_usage.json"))


ASKED = [ChatMessage("system", "You are Akira."), ChatMessage("system", "Pins: D13 is PA5."),
         ChatMessage("user", "Which pins?"), ChatMessage("assistant", "Let me look."),
         ChatMessage("assistant", "SPI1."), ChatMessage("user", "And CS?")]


def test_the_request_is_opus_5_5_with_its_system_joined_and_turns_merged():
    payload = cloud.request(ASKED, "high")
    assert payload["model"] == "claude-opus-5-5"
    assert payload["system"] == "You are Akira.\n\nPins: D13 is PA5."
    assert payload["messages"] == [
        {"role": "user", "content": "Which pins?"},
        {"role": "assistant", "content": "Let me look.\n\nSPI1."},
        {"role": "user", "content": "And CS?"}]
    assert payload["output_config"] == {"effort": "high"}
    assert payload["fallbacks"] == "default"
    assert "thinking" not in payload and "temperature" not in payload, \
        "Opus 5.5 takes neither: its thinking is always on"


def test_a_conversation_never_ends_on_claudes_own_turn():
    payload = cloud.request([ChatMessage("assistant", "Hello"), ChatMessage("user", ""),
                             ChatMessage("assistant", "Hm")], "medium")
    roles = [m["role"] for m in payload["messages"]]
    assert roles[0] == "user" and roles[-1] == "user"
    assert all(m["content"] for m in payload["messages"])


def test_the_key_goes_in_its_own_header_to_anthropic_and_nowhere_else(tmp_path, anthropic):
    site = anthropic(reply(ANSWERED))
    shown = []
    result = claude(tmp_path).backend("high").generate(ASKED, on_token=shown.append)
    assert result.text == "Use SPI1 on PA5 and PA7." and shown == [result.text]
    assert (result.prompt_tokens, result.completion_tokens) == (1200, 300)
    [sent] = site.requests
    headers = {k.lower(): v for k, v in sent["headers"].items()}
    assert (sent["method"], sent["host"], sent["path"]) == ("POST", "api.anthropic.com",
                                                            "/v1/messages")
    assert headers["x-api-key"] == KEY and "authorization" not in headers
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert json.loads(sent["body"])["messages"][0] == {"role": "user", "content": "Which pins?"}
    log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "model.cloud" in log and KEY not in log and "Which pins" not in log


def test_what_claude_was_asked_and_wrote_is_added_up_for_the_month(tmp_path, anthropic):
    anthropic(reply(ANSWERED))
    found = claude(tmp_path)
    found.backend().generate(ASKED)
    anthropic(reply(ANSWERED))
    found.backend().generate(ASKED)
    assert found.spend.month() == {"read": 2400, "written": 600,
                                   "dollars": round(2400 / 1e6 * 4 + 600 / 1e6 * 20, 2)}


def test_nothing_is_sent_without_the_permission(tmp_path, anthropic):
    site = anthropic(reply(ANSWERED))
    found = claude(tmp_path, granted=False)
    assert "not allowed" in found.ready()
    with pytest.raises(ModelUnavailable, match="Not permitted"):
        found.backend().generate(ASKED)
    assert site.requests == []


def test_without_a_key_it_says_where_to_add_one(tmp_path, anthropic):
    anthropic(reply(ANSWERED))
    found = claude(tmp_path, key=False)
    assert found.ready() == "Add your Claude API key first."
    with pytest.raises(ModelUnavailable, match="model menu"):
        found.backend().generate(ASKED)


def test_a_refusal_is_said_as_one(tmp_path, anthropic):
    anthropic(reply({"content": [], "stop_reason": "refusal",
                     "stop_details": {"type": "refusal", "category": "cyber"},
                     "usage": {"input_tokens": 10, "output_tokens": 0}}))
    result = claude(tmp_path).backend().generate(ASKED)
    assert result.text == "Claude declined to answer this (cyber)."
    assert result.stop_reason == "refused"


@pytest.mark.parametrize("status,said", [(401, "refused the API key"),
                                         (429, "usage limit"), (529, "overloaded")])
def test_anthropics_refusals_are_said_in_words(tmp_path, anthropic, status, said):
    anthropic(reply({"type": "error", "error": {"message": "no"}}, status=status,
                    reason="Error"))
    with pytest.raises(ModelError, match=said):
        claude(tmp_path).backend().generate(ASKED)


def test_a_key_is_checked_before_it_is_kept_and_forgotten_on_request(tmp_path, anthropic):
    anthropic(reply({"id": "claude-opus-5-5"}))
    found = claude(tmp_path, key=False)
    assert "begin sk-ant-" in found.seal("hello")
    assert found.seal(KEY) == "" and found.has_key()
    assert found.check() == ""
    found.forget()
    assert not found.has_key()


def test_the_router_gives_claude_for_every_route_at_the_right_effort(tmp_path):
    found = claude(tmp_path)
    router = found.router()
    with router.acquire(Route.CHAT) as backend:
        assert backend.label == "Claude Opus 5.5" and backend._effort == "medium"
    with router.acquire(Route.CODE) as backend:
        assert backend._effort == "high"
    with found.router(effort="high").acquire(Route.CHAT) as backend:
        assert backend._effort == "high", "an agent's work is not an everyday answer"


def test_the_door_refuses_headers_that_are_its_own(tmp_path, anthropic):
    anthropic(reply(ANSWERED))
    policy = Policy()
    policy.grant("model.cloud", ("anthropic",))
    for bad in ({"Authorization": "x"}, {"Host": "evil"}, {"X-Ok": "a\r\nInjected: 1"}):
        with pytest.raises(ValueError):
            net.call("GET", cloud.MODEL_URL, policy=policy, capability="model.cloud",
                     scope="anthropic", hosts=(cloud.HOST,), headers=bad)
    with pytest.raises(ValueError, match="one sign-in"):
        net.call("GET", cloud.MODEL_URL, policy=policy, capability="model.cloud",
                 scope="anthropic", hosts=(cloud.HOST,), bearer=lambda: "t",
                 key=("x-api-key", lambda: KEY))
