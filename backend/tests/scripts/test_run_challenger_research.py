import json
from pathlib import Path
import subprocess
import sys


def test_cli_preserves_input_and_refuses_to_overwrite_report(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(
        json.dumps(
            {
                "as_of": "2026-01-01",
                "assets": [],
                "costs": {"fee_rate_pct": 0.1, "kr_tax_rate_pct": 0.2, "fx_spread_pct": 0.1},
            }
        )
    )
    output = tmp_path / "report.json"
    script = Path(__file__).resolve().parents[3] / "scripts/run_challenger_research.py"
    command = [sys.executable, str(script), str(source), "--output", str(output)]
    before = source.read_bytes()
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text())
    assert len(report["experiments"]) == 16
    assert len(report["input_file_sha256"]) == 64
    assert source.read_bytes() == before
    assert subprocess.run(command, capture_output=True).returncode != 0
