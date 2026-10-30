-- Locality position (WGS84 degrees), converted from the CBS ITM coordinate code.
alter table public.localities
    add column lat double precision,
    add column lon double precision;
