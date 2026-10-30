-- Cover the locality_aliases foreign key.

create index locality_aliases_locality_code_idx on public.locality_aliases (locality_code);
