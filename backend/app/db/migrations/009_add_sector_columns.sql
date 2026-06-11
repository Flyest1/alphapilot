-- 009: 자산/후보 자산 섹터 컬럼 (additive)
-- 노출/집중도 분석(Phase 4-3)에 사용한다. 리포트 생성 시 yfinance 정보로 자동 보충된다.

alter table assets add column if not exists sector text;
alter table candidate_assets add column if not exists sector text;
