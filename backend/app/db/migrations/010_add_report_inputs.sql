-- 010: 리포트 입력 스냅샷 (additive)
-- 리포트 생성 당시의 데이터 품질(제공자/신선도/뉴스 컨텍스트)을 JSONB로 보존해
-- 사후 검증과 프론트 데이터 품질 배지(Phase 4-4)에 사용한다.

alter table reports add column if not exists report_inputs jsonb;
