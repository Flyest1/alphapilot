# AlphaPilot Backend

AlphaPilot의 FastAPI 백엔드입니다. 설치, Supabase 마이그레이션, Oracle VM 배포,
Render 롤백, 스케줄러와 보안 범위는 루트 `README.md`를 참고하세요.

## 기존 데이터베이스를 연결하는 추가 로컬 실행

다른 서버가 같은 Supabase를 사용하고 있을 때, 로컬 백엔드를 시작하는 것만으로
설정을 바꾸거나 기존 자문 작업을 재실행하지 않도록 두 환경변수를 지정할 수 있습니다.

```sh
cd /path/to/alphapilot/backend
STARTUP_UPGRADE_LEGACY_AI_MODEL=false \
STARTUP_RECOVER_ADVISORY_JOBS=false \
OPENAI_API_KEY= SCHEDULER_SECRET= \
TOSS_INVEST_CLIENT_ID= TOSS_INVEST_CLIENT_SECRET= TOSS_INVEST_ACCOUNT_ID= \
TELEGRAM_BOT_TOKEN= TELEGRAM_CHAT_ID= \
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18000 --no-access-log
```

기존 `backend/.env`의 Supabase와 접속 토큰 설정은 그대로 읽습니다.
프론트엔드 주소는 `FRONTEND_ORIGIN`에, 백엔드 주소는 프론트엔드의
`VITE_API_BASE_URL`에 맞춰 설정하세요. 명령에서 비워 둔 키는 해당 실행에만 적용되며
`.env` 원본을 바꾸지 않습니다. `--reload`나 여러 worker 없이 단일 프로세스로 실행합니다.

- `STARTUP_UPGRADE_LEGACY_AI_MODEL`: 기본 `true`. `false`이면 시작할 때 저장된 이전
  기본 AI 모델을 새 기본값으로 갱신하는 DB 쓰기를 생략합니다. 저장된 모델을 그대로
  사용하며, 설정 화면에서 직접 저장하는 기능은 유지됩니다. DB에 설정이 없을 때의
  환경변수 기본 모델 정규화는 기존대로 동작합니다.
- `STARTUP_RECOVER_ADVISORY_JOBS`: 기본 `true`. `false`이면 시작할 때 미완료 자문 작업을
  조회·완료 처리·재실행하지 않습니다. 수동으로 새 자문을 요청하는 기능은 유지됩니다.
  기존 미완료 작업은 다른 서버에서 복구하거나 별도로 확인해야 합니다.

두 옵션은 읽기 전용 모드가 아닙니다. 대시보드 조회도 환율 설정과 시세 캐시를 저장할 수
있고, 오래된 자문·수동 리포트 작업 조회는 상태를 실패로 갱신할 수 있습니다. 자산·설정 저장과
수동 리포트·자문 요청도 DB에 기록됩니다. **운영 데이터 변경 없이 검증하려면 앱 화면을
열지 말고, 필요한 테이블만 직접 읽기 전용으로 조회하세요.**

명령에서 OpenAI 키를 비우면 AI 호출은 비활성화되며 리포트는 기술 분석 대체 경로를
사용합니다. 자문은 설정과 원천 데이터에 따라 제한된 결과를 낼 수 있습니다. Toss 자격과
Telegram 자격도 비워 브로커 접속과 외부 알림을 끄고, 빈 스케줄러 비밀값은 스케줄러
엔드포인트 접근을 막습니다. 무료 시세·뉴스 조회는 가능하며 외부 서비스 가용성에 따라
실패하거나 지연될 수 있습니다. 두 기동 옵션만으로 유료 API 호출이 차단되는 것은
아니므로, 비용을 승인하기 전에는 OpenAI 키를 비워 두세요.
