import json
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest

from mockgithub.check import main

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "github.json"


def _write(path: Path, scenario: dict[str, Any]) -> str:
    path.write_text(json.dumps(scenario), encoding="utf-8")
    return str(path)


def test_one_valid_scenario_is_reported_as_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(FIXTURE)]) == 0
    assert capsys.readouterr().out == "ok: 1 scenarios, disjoint\n"


def test_a_scenario_that_will_not_validate_names_its_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "broken.json", {"version": 1})
    assert main([path]) == 1
    assert capsys.readouterr().out == f"{path}: missing top-level key: clock\n"


def test_a_file_that_is_not_there_is_reported_not_raised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = str(tmp_path / "absent.json")
    assert main([missing]) == 1
    assert "No such file" in capsys.readouterr().out


def test_two_estates_that_share_a_human_key_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = json.loads(FIXTURE.read_text(encoding="utf-8"))
    holdout = json.loads(FIXTURE.read_text(encoding="utf-8"))
    holdout["github"]["repos"][0]["issues"] = holdout["github"]["repos"][0]["issues"][:1]
    first = _write(tmp_path / "public.json", scenario)
    second = _write(tmp_path / "holdout.json", holdout)
    assert main([first, second]) == 1
    printed = capsys.readouterr().out.splitlines()
    assert "shared repository: ExampleCo/membership-ledger" in printed
    assert "shared login: rhea-menon" in printed
    assert "shared user email: rhea.menon@ExampleCo.example" in printed
    assert "shared issue number: ExampleCo/membership-ledger#38" in printed
    assert "shared issue number: ExampleCo/membership-ledger#41" not in printed
    assert "shared pull number: ExampleCo/membership-ledger#39" in printed
    assert "shared branch name: ExampleCo/membership-ledger:main" in printed
    assert "shared commit key: ExampleCo/membership-ledger:c1" in printed
    assert "shared tag name: ExampleCo/membership-ledger:v0.8.0" in printed


def test_two_disjoint_estates_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    first = _write(tmp_path / "public.json", json.loads(FIXTURE.read_text(encoding="utf-8")))
    second = _write(tmp_path / "holdout.json", {"version": 1, "clock": "2026-03-04T10:00:00Z"})
    assert main([first, second]) == 0
    assert capsys.readouterr().out == "ok: 2 scenarios, disjoint\n"


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_the_check_is_runnable_as_a_module(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["mockgithub.check", str(FIXTURE)])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("mockgithub.check", run_name="__main__")
    assert exit_info.value.code == 0
    assert capsys.readouterr().out == "ok: 1 scenarios, disjoint\n"
