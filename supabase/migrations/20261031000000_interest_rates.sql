-- Bank of Israel interest rates: monthly average rates on new mortgages by track, the policy
-- rate and the prime rate (policy rate + 1.5), in percent per year.

create table public.interest_rates (
    series_code  text not null,                     -- e.g. 'mortgage_fixed_unindexed', 'prime'
    series_name  text not null,
    period       date not null,                     -- first day of the month
    value        numeric(8, 4) not null,            -- percent per year
    fetched_at   timestamptz not null default now(),
    primary key (series_code, period)
);

alter table public.interest_rates enable row level security;
