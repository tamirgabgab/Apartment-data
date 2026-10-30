-- CBS average prices by district and big city (Price Statistics Monthly tables 2.2 and 4.9).
-- One row per kind (sale / rent), place, quarter and rooms group, from the newest edition.

create table public.cbs_average_prices (
    kind            text not null check (kind in ('sale', 'rent')),
    geo_level       text not null check (geo_level in ('national', 'district', 'city')),
    geo_code        integer not null,                -- 0, district number, or CBS locality code
    period          date not null,                   -- first day of the quarter
    rooms           text not null,                   -- 'all' or a range such as '2.5-3'
    avg_price       numeric(12, 1),                  -- NIS (sale price, or monthly rent)
    n_deals         integer,                         -- sale only
    sampling_error  numeric(10, 4),                  -- rent only
    edition         text not null,                   -- 'YYYY-MM' publication the value comes from
    fetched_at      timestamptz not null default now(),
    primary key (kind, geo_level, geo_code, period, rooms)
);

alter table public.cbs_average_prices enable row level security;
