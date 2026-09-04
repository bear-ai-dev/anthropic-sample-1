import json
import time
from pathlib import Path

import pytest

from mockgithub.journal import Journal


def test_each_record_gets_a_sequence_and_lands_in_the_sink(tmp_path: Path) -> None:
    journal = Journal(str(tmp_path / "calls.jsonl"))
    journal.record({"service": "github", "tool": "get_issue"})
    journal.record({"service": "github", "tool": "list_issues"})
    lines = (tmp_path / "calls.jsonl").read_text().splitlines()
    assert [json.loads(line)["seq"] for line in lines] == [0, 1]
    assert [entry["tool"] for entry in journal.records()] == ["get_issue", "list_issues"]


def test_a_sink_line_is_one_compact_json_object_with_sorted_keys(tmp_path: Path) -> None:
    sink = tmp_path / "calls.jsonl"
    entry = Journal(str(sink)).record({"tool": "get_issue", "service": "github"})
    line = sink.read_text().splitlines()[0]
    assert line == json.dumps(entry, separators=(",", ":"), sort_keys=True)
    assert line.startswith('{"at":')


def test_a_record_is_stamped_with_a_sequence_and_a_wall_clock_time() -> None:
    before = time.time()
    entry = Journal(None).record({"service": "github", "tool": "get_issue"})
    assert entry["seq"] == 0
    assert before <= entry["at"] <= time.time()


def test_the_caller_dictionary_is_left_untouched() -> None:
    call = {"service": "github", "tool": "get_issue"}
    Journal(None).record(call)
    assert call == {"service": "github", "tool": "get_issue"}


def test_without_a_sink_records_are_kept_in_memory_only(tmp_path: Path) -> None:
    journal = Journal(None)
    journal.record({"tool": "get_issue"})
    assert len(journal.records()) == 1
    assert list(tmp_path.iterdir()) == []


def test_clearing_the_journal_restarts_the_sequence(tmp_path: Path) -> None:
    sink = tmp_path / "calls.jsonl"
    journal = Journal(str(sink))
    journal.record({"tool": "get_issue"})
    journal.clear()
    assert journal.records() == []
    assert journal.record({"tool": "list_issues"})["seq"] == 0
    assert [json.loads(line)["seq"] for line in sink.read_text().splitlines()] == [0, 0]


def test_the_returned_record_list_is_a_copy() -> None:
    journal = Journal(None)
    journal.record({"tool": "get_issue"})
    journal.records().clear()
    assert len(journal.records()) == 1


def test_a_sink_that_cannot_be_written_is_reported_and_does_not_stop_the_daemon(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unwritable = tmp_path / "no-such-directory" / "calls.jsonl"
    journal = Journal(str(unwritable))
    entry = journal.record({"service": "github", "tool": "get_me"})
    assert entry["seq"] == 0
    assert journal.records() == [entry]
    reported = capsys.readouterr().err.strip()
    assert str(unwritable) in reported
    assert "FileNotFoundError" in reported
    assert "mockgithub" in reported


def test_the_sink_file_exists_before_any_call_is_recorded(tmp_path: Path) -> None:
    sink = tmp_path / "calls.jsonl"
    journal = Journal(str(sink))
    assert sink.exists()
    assert sink.read_text() == ""
    assert journal.records() == []
    assert sink.stat().st_mode & 0o777 == 0o600
