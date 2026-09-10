"""Settings: what is offered, and what changing it does.

The behaviour worth pinning is that a change reaches the router immediately. A
setting that only takes effect after a restart is one people stop trusting, and
the failure is silent — the old model keeps answering.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the Qt interface is optional for the old app")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from protege.core.config import AppConfig, ModelConfig  # noqa: E402
from protege.core.models import ModelRouter, Route  # noqa: E402
from protege.ui.bridge import SettingsBridge  # noqa: E402

@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture(autouse=True)
def tiny_models_allowed(monkeypatch):
    """Let a few dozen bytes stand in for a model file.

    `discover_models` rejects anything under 100 MB, which is right in
    production. Honouring it literally here meant writing two real 200 MB files
    per test — and because pytest keeps several runs' temp directories, that put
    tens of gigabytes on disk and took the suite from 27 seconds to minutes.
    """
    monkeypatch.setattr("protege.core.config._MIN_MODEL_BYTES", 8)


def write_model(path, extra=0):
    """A file that passes the GGUF header check."""
    path.write_bytes(b"GGUF" + bytes(64 + extra))
    return path


@pytest.fixture
def models(tmp_path, monkeypatch):
    """Two plausible model files, discoverable by the config layer."""
    directory = tmp_path / "models"
    directory.mkdir()
    small = write_model(directory / "Small-3B.gguf")
    large = write_model(directory / "Large-8B.gguf", extra=1024)
    monkeypatch.setattr("protege.core.config.MODELS_DIR", directory)
    return {"dir": directory, "small": small, "large": large}


@pytest.fixture
def bridge(qt_app, models, monkeypatch, tmp_path):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))
    config = AppConfig(models={"chat": ModelConfig(path=str(models["large"]))})
    router = ModelRouter(config)
    return SettingsBridge(config, router), config, router


def test_available_models_are_listed_smallest_first(bridge, models):
    settings, _, _ = bridge
    names = [m["name"] for m in settings.availableModels]
    assert names == ["Small-3B", "Large-8B"]


def test_a_file_that_is_not_a_gguf_is_not_offered(bridge, models):
    (models["dir"] / "notes.gguf").write_bytes(b"this is not a model" * 64)
    settings, _, _ = bridge
    assert "notes" not in [m["name"] for m in settings.availableModels]


def test_every_route_is_described(bridge):
    settings, _, _ = bridge
    routes = {r["id"]: r for r in settings.routes}
    assert set(routes) == {"chat", "code", "fast", "deep"}
    assert routes["chat"]["usable"] is True
    assert routes["deep"]["usable"] is False
    assert routes["deep"]["detail"] == "not configured"


def test_assigning_a_model_reaches_the_config_and_the_router(bridge, models):
    settings, config, router = bridge

    settings.assign("code", str(models["small"]))

    assert config.models["code"].path == str(models["small"])
    assert router.resolve(Route.CODE) is Route.CODE
    assert [r for r in settings.routes if r["id"] == "code"][0]["usable"] is True


def test_assignment_is_persisted(bridge, models):
    settings, config, _ = bridge
    settings.assign("code", str(models["small"]))

    reloaded = AppConfig.load()

    assert reloaded.models["code"].path == str(models["small"])


def test_numeric_settings_are_whitelisted(bridge):
    """This is called from QML; it must not be a general attribute setter."""
    settings, config, _ = bridge

    settings.setNumber("chat", "n_ctx", 4096)
    assert config.models["chat"].n_ctx == 4096

    settings.setNumber("chat", "path", 1)
    assert config.models["chat"].path != 1
    assert isinstance(config.models["chat"].path, str)


def test_an_unknown_route_name_does_not_crash(bridge, models):
    settings, config, _ = bridge
    settings.assign("nonsense", str(models["small"]))
    # Route.parse falls back to CHAT rather than raising.
    assert config.models["chat"].path == str(models["small"])


def test_clearing_a_route_makes_it_unusable(bridge):
    settings, config, _ = bridge
    settings.assign("chat", "")
    assert [r for r in settings.routes if r["id"] == "chat"][0]["usable"] is False
