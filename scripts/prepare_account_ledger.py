"""Prepare local ledger evidence and reports, without DB or network access."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.ledger.preparation import check_preparation, preparation_template  # noqa: E402
from app.services.ledger.preparation_report import (  # noqa: E402
    CHECK_LABELS,
    render_preparation_report,
)


def _json_file(folder, name, value):
    with (folder / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("init", help="Create empty, explicitly incomplete templates")
    create.add_argument("--output-dir", type=Path, required=True)
    check = commands.add_parser("check", help="Check files and write JSON/Korean Markdown reports")
    check.add_argument("manifest", type=Path)
    check.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = args.output_dir.resolve()
        output.relative_to((ROOT / "backups").resolve())
        result = check_preparation(args.manifest) if args.command == "check" else None
        # Reserve a new directory; interrupted output remains, never overwritten on retry.
        output.mkdir(parents=True, exist_ok=False)
        if result is not None:
            _json_file(output, "report.json", result)
            with (output / "report.md").open("x", encoding="utf-8") as stream:
                stream.write(render_preparation_report(result))
            print(
                json.dumps(
                    {
                        "status": result["status"],
                        "blockers": len(result["blockers"]),
                        "stored": False,
                    }
                )
            )
            return 0 if result["status"] == "ready_for_review" else 2
        _json_file(output, "manifest.json", preparation_template())
        balance = {
            "account_id": None,
            "as_of": None,
            "source_record_hash": None,
            "cash_basis": "settled",
            "cash": {"KRW": None, "USD": None},
            "receivables": {"KRW": None, "USD": None},
            "payables": {"KRW": None, "USD": None},
            "positions": None,
        }
        for name in ("opening.json", "closing.json"):
            _json_file(output, name, balance)
        _json_file(
            output,
            "mapping.json",
            {
                "version": "statement_csv_v1",
                "columns": {},
                "constants": {"quality": "provisional"},
                "value_maps": {},
            },
        )
        lines = [
            "# 운영 원장 자료 준비",
            "",
            "빈 템플릿입니다. 실제 잔고·수수료·세금을 0으로 추정하지 마세요.",
            "원본은 이 폴더 안에 복사해 보존하고 manifest에는 이 폴더 기준 상대 경로를 입력하세요.",
            "기초 잔고는 시작일 전날, 기말 잔고는 종료일의 정산 잔고입니다.",
            "가용 매수금액은 정산 잔고로 사용할 수 없습니다.",
            "각 잔고 source_record_hash에는 근거 원본 파일 전체의 SHA-256을 입력하세요.",
            "금액·수량은 소수 문자열입니다. 없음을 확인한 경우만 0 또는 빈 positions를 입력하세요.",
            "statements의 각 객체에는 csv, mapping, period_start, period_end 필드를 입력하세요.",
            "매핑은 실제 열 제목·거래 유형·통화·시간대·금액 부호·수수료·세금을 확인해 작성하세요.",
            "quality=verified는 사용자의 증거 확인 선언입니다. 도구가 검증했다는 뜻이 아닙니다.",
            "기간은 한국시간 기준입니다. observed_at은 종료일 이후의 시간대 포함 확인 시각입니다.",
            "자세한 절차: 저장소 docs/ledger_operating_preparation_2026_09_23.md",
            "",
            "## 확인 항목",
            "",
        ]
        lines.extend(f"- {key}: {label}" for key, label in CHECK_LABELS.items())
        lines.extend(
            [
                "",
                "원본·잔고·보고서는 비공개이며 암호화되지 않습니다. 외부 업로드를 피하세요.",
                "",
            ]
        )
        with (output / "README.md").open("x", encoding="utf-8") as stream:
            stream.write("\n".join(lines))
        print(json.dumps({"status": "template_created", "stored": False}))
        return 0
    except (OSError, ValueError, TypeError, RuntimeError):
        print(
            json.dumps({"status": "failed", "reason": "ledger_preparation_failed"}), file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
