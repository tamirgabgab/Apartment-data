-- Cover the locality_aliases foreign key, and drop the partial deals index:
-- the full (locality_code, deal_date) index already serves those queries and storage is limited.

create index locality_aliases_locality_code_idx on public.locality_aliases (locality_code);

drop index public.deals_valid_locality_date_idx;
