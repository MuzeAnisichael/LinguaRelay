from __future__ import annotations

import pytest

from lingua_relay.updates import UpdateInfo, _version_tuple


def test_update_comparison() -> None:
    assert UpdateInfo("0.1.0", "0.1.1", "https://github.com/example").available
    assert not UpdateInfo("0.1.0", "0.1.0", "https://github.com/example").available
    assert _version_tuple("v2.3.4") == (2, 3, 4)


def test_invalid_update_version() -> None:
    with pytest.raises(ValueError):
        _version_tuple("latest")
