"""Windows labels Akira's notifications "Akira": its id is given a name, in the person's
own part of the registry, and only when the name is not already there.

The real registry is never touched here: a fake stands in for `winreg`.
"""

from __future__ import annotations

from akira.ui import shell


class FakeRegistry:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_WRITE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.keys: dict[str, dict[str, str]] = {}
        self.writes = 0

    def CreateKeyEx(self, root, path, reserved, access):  # noqa: N802 - winreg's name
        assert root == "HKCU", "only the person's own part of the registry"
        values = self.keys.setdefault(path, {})

        class Key:
            def __enter__(self):
                return values

            def __exit__(self, *exc):
                return False

        return Key()

    def QueryValueEx(self, key, name):  # noqa: N802
        if name not in key:
            raise FileNotFoundError(name)
        return key[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):  # noqa: N802
        key[name] = value
        self.writes += 1


def test_the_id_is_named_akira_once():
    registry = FakeRegistry()
    assert shell.name_for_notifications(registry)
    values = registry.keys[r"Software\Classes\AppUserModelId" + "\\" + shell.APP_ID]
    assert values["DisplayName"] == "Akira"
    assert values["IconUri"].endswith("akira-logo.png")
    writes = registry.writes
    # Started again, nothing is written.
    assert not shell.name_for_notifications(registry)
    assert registry.writes == writes


def test_a_registry_that_refuses_changes_nothing_else():
    class Refusing(FakeRegistry):
        def CreateKeyEx(self, *args):  # noqa: N802
            raise PermissionError("denied")

    assert not shell.name_for_notifications(Refusing())
