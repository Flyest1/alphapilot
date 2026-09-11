import json
import subprocess
import sys
from pathlib import Path


def test_local_audit_creates_traceable_report_and_refuses_overwrite(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"cycles": [{"id": "legacy"}], "histories": {}}))
    output = tmp_path / "audit.json"
    script = Path(__file__).resolve().parents[3] / "scripts" / "audit_recommendations.py"
    command = [
        sys.executable,
        str(script),
        str(source),
        "--as-of",
        "2026-09-10",
        "--output",
        str(output),
    ]
    run = subprocess.run(command, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["excluded_reasons"] == {"missing_original_decision": 1}
    assert len(report["input_sha256"]) == 64
    original = output.read_bytes()
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert output.read_bytes() == original
