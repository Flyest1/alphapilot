import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

from app.config import get_environment_settings, is_supabase_configured  # noqa: E402
from app.db.supabase_client import create_repository  # noqa: E402
from app.services.market_data_service import MarketDataService  # noqa: E402
from app.services.report.tracking import PerformanceTracker  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="추천 사이클을 방향별 장벽 규칙으로 백업 후 재산출합니다."
    )
    parser.add_argument("--apply", action="store_true", help="실제 Supabase 행을 갱신합니다.")
    parser.add_argument("--limit", type=int, default=1000, help="최대 처리 행 수")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=ROOT / "backups",
        help="적용 전 JSON 백업 디렉터리",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = get_environment_settings()
    if not is_supabase_configured(env):
        print("Supabase 환경변수가 설정되지 않아 재산출을 실행할 수 없습니다.")
        return 1

    repository = create_repository(env)
    cycles = repository.list_recommendation_cycles(limit=max(1, args.limit))
    eligible = [cycle for cycle in cycles if cycle.get("status") != "superseded"]
    print(f"재산출 대상 {len(eligible)}건 (조회 {len(cycles)}건, superseded 제외)")
    if not args.apply:
        print("미리보기만 수행했습니다. 실제 적용은 --apply 옵션을 사용하세요.")
        return 0

    args.backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = args.backup_dir / f"recommendation_cycles_{timestamp}.json"
    backup_path.write_text(
        json.dumps(cycles, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tracker = PerformanceTracker(repository, MarketDataService(repository=repository))
    recalculated = tracker.recalculate_recommendation_cycles(limit=max(1, args.limit))
    print(f"백업: {backup_path}")
    print(f"재산출 완료: {recalculated}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
