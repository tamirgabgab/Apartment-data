-- Initial schema for apartment price tracking.
-- The website reads pre-computed static JSON, so no table is exposed to the anon role:
-- RLS is enabled with no policies, and only the ingestion jobs (postgres role) read and write.

create table public.localities (
    locality_code     integer primary key,          -- CBS locality code (semel yishuv)
    name_he           text not null,
    name_en           text,
    municipal_status  text,                         -- e.g. 'עירייה', 'מועצה מקומית'
    district          text,
    sub_district      text,
    population        integer,
    is_city           boolean not null default false,
    updated_at        timestamptz not null default now()
);

create table public.locality_aliases (
    alias          text primary key,                -- normalized alternative spelling
    locality_code  integer not null references public.localities (locality_code)
);

create table public.deals (
    deal_id              text primary key,          -- source key or stable hash
    source               text not null,             -- 'nadlan', 'yad2', 'madlan'
    deal_date            date not null,
    price_ils            numeric(14, 2) not null,
    locality_code        integer references public.localities (locality_code),
    locality_name_raw    text,                      -- as reported, before mapping
    street               text,
    house_number         text,
    gush                 integer,
    helka                integer,
    sub_helka            integer,
    rooms                numeric(4, 1),
    area_sqm             numeric(8, 2),
    floor                smallint,
    build_year           smallint,
    property_type        text,
    deal_nature          text,
    fraction_sold        numeric(6, 5),
    is_new_construction  boolean,
    is_valid             boolean not null default true,
    invalid_reason       text,
    fetched_at           timestamptz not null default now()
);

create index deals_locality_date_idx on public.deals (locality_code, deal_date);
create index deals_valid_locality_date_idx on public.deals (locality_code, deal_date) where is_valid;

create table public.official_indices (
    series_code  text not null,                     -- e.g. CBS series id
    series_name  text not null,
    period       date not null,                     -- first day of the period
    value        numeric(14, 4) not null,
    base_period  text,
    fetched_at   timestamptz not null default now(),
    primary key (series_code, period)
);

create table public.city_price_stats (
    locality_code              integer not null references public.localities (locality_code),
    period                     date not null,       -- first day of the quarter
    segment                    text not null,       -- 'all', 'rooms_le3', 'rooms_4', 'rooms_5plus', 'new', 'second_hand'
    n_deals                    integer not null,
    median_price               numeric(14, 2),
    median_price_per_sqm       numeric(10, 2),
    p25_price_per_sqm          numeric(10, 2),
    p75_price_per_sqm          numeric(10, 2),
    real_median_price_per_sqm  numeric(10, 2),      -- CPI-deflated
    is_reliable                boolean not null,
    is_provisional             boolean not null,
    computed_at                timestamptz not null default now(),
    primary key (locality_code, period, segment)
);

create table public.ingestion_runs (
    run_id        bigint generated always as identity primary key,
    source        text not null,
    started_at    timestamptz not null default now(),
    finished_at   timestamptz,
    status        text not null default 'running',  -- 'running', 'success', 'failed'
    rows_fetched  integer,
    message       text
);

alter table public.localities enable row level security;
alter table public.locality_aliases enable row level security;
alter table public.deals enable row level security;
alter table public.official_indices enable row level security;
alter table public.city_price_stats enable row level security;
alter table public.ingestion_runs enable row level security;
