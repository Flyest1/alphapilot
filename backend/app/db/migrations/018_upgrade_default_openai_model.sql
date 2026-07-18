-- 018: Upgrade the application OpenAI model default for existing settings rows.

alter table settings
alter column ai_model set default 'gpt-5.6-luna';

update settings
set ai_model = 'gpt-5.6-luna',
    updated_at = now()
where ai_model = 'gpt-5.4-mini';
