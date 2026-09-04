import runpy

import pytest

from mocklinear import serve


def test_the_module_entry_point_exits_with_the_result_of_serve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serve, "main", lambda: 3)
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("mocklinear", run_name="__main__")
    assert exit_info.value.code == 3
