-- Expand the persisted advisory type allowlist without changing existing rows.

create table if not exists public.advisory_capabilities (
    capability text primary key,
    enabled boolean not null default true,
    applied_at timestamptz not null default now()
);

alter table public.advisory_jobs
    drop constraint if exists advisory_jobs_analysis_type_check;

alter table public.advisory_jobs
    add constraint advisory_jobs_analysis_type_check
    check (
        analysis_type in (
            'undervalued_us_stocks',
            'etf_rebalancing',
            'post_earnings_opportunities',
            'ai_beneficiaries',
            'high_dividend_etfs',
            'sec_filing_risk',
            'etf_overlap',
            'sector_outlook',
            'profit_taking_review',
            'high_upside_speculative_stocks'
        )
    );

alter table public.advisory_analyses
    drop constraint if exists advisory_analyses_analysis_type_check;

alter table public.advisory_analyses
    add constraint advisory_analyses_analysis_type_check
    check (
        analysis_type in (
            'undervalued_us_stocks',
            'etf_rebalancing',
            'post_earnings_opportunities',
            'ai_beneficiaries',
            'high_dividend_etfs',
            'sec_filing_risk',
            'etf_overlap',
            'sector_outlook',
            'profit_taking_review',
            'high_upside_speculative_stocks'
        )
    );

insert into public.advisory_capabilities (capability, enabled)
values ('high_upside_speculative_stocks', true)
on conflict (capability) do update
set enabled = excluded.enabled,
    applied_at = now();
