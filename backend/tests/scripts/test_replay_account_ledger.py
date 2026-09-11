import csv
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.services.ledger.io import read_events_csv

ROOT = Path(__file__).resolve().parents[3]


def test_csv_preserves_decimal_text_and_unknown_cost():
    rows = read_events_csv(
        "revision,gross_amount,fee,settlement_confirmed\n1,12.000000000001,,true\n"
    )
    assert rows == [
        {
            "revision": 1,
            "gross_amount": "12.000000000001",
            "fee": None,
            "settlement_confirmed": True,
        }
    ]


@pytest.mark.parametrize("text", ["fee,fee\n1,2", "fee,tax\n1", "fee\n1,2"])
def test_invalid_csv_shape_is_rejected(text):
    with pytest.raises(ValueError):
        read_events_csv(text)


def test_synthetic_example_reconciles_and_refuses_overwrite(tmp_path):
    source = ROOT / "docs/examples/account_ledger_synthetic.json"
    before = source.read_bytes()
    output = tmp_path / "result.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/replay_account_ledger.py"),
        str(source),
        "--output",
        str(output),
    ]
    subprocess.run(command, check=True, capture_output=True)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["reconciliation"]["status"] == "matched"
    assert result["balances"]["cash"]["USD"] == "907.5"
    frozen = output.read_bytes()
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert output.read_bytes() == frozen
    assert source.read_bytes() == before


def test_csv_and_json_event_inputs_replay_equivalently(tmp_path):
    payload = json.loads(
        (ROOT / "docs/examples/account_ledger_synthetic.json").read_text(encoding="utf-8")
    )
    events = payload.pop("events")
    fields = list(dict.fromkeys(key for event in events for key in event))
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(
        {
            key: (str(value).lower() if isinstance(value, bool) else value)
            for key, value in event.items()
        }
        for event in events
    )
    csv_path = tmp_path / "events.csv"
    csv_path.write_text(stream.getvalue(), encoding="utf-8")
    source = tmp_path / "input.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "result.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/replay_account_ledger.py"),
            str(source),
            "--events-csv",
            str(csv_path),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
    )
    assert json.loads(output.read_text(encoding="utf-8"))["reconciliation"]["status"] == "matched"
