-- One row per hour: price, load, generation totals, renewable share and a completeness flag
with generation as (
    select
        hour_utc,
        sum(generation_mwh) as total_generation_mwh,
        sum(generation_mwh) filter (where is_renewable) as renewable_generation_mwh,
        sum(generation_mwh) filter (where category = 'conventional') as conventional_generation_mwh,
        sum(generation_mwh) filter (where category = 'storage') as storage_generation_mwh,
        sum(generation_mwh) filter (
            where energy_source_slug in ('wind_onshore', 'wind_offshore')
        ) as wind_generation_mwh,
        sum(generation_mwh) filter (where energy_source_slug = 'solar') as solar_generation_mwh,
        count(*) filter (where required_for_completeness) as required_sources_reported
    from {{ ref('int_generation_hourly') }}
    group by hour_utc
),

required as (
    select count(*) as required_sources
    from {{ ref('smard_series') }}
    where required_for_completeness
),

market as (
    select * from {{ ref('int_market_hourly') }}
),

hours as (
    select hour_utc from market
    union
    select hour_utc from generation
)

select
    hours.hour_utc,
    market.price_eur_mwh,
    market.grid_load_mwh,
    generation.total_generation_mwh,
    coalesce(generation.renewable_generation_mwh, 0) as renewable_generation_mwh,
    coalesce(generation.conventional_generation_mwh, 0) as conventional_generation_mwh,
    coalesce(generation.storage_generation_mwh, 0) as storage_generation_mwh,
    generation.wind_generation_mwh,
    generation.solar_generation_mwh,
    coalesce(generation.renewable_generation_mwh, 0)
    / nullif(generation.total_generation_mwh, 0) as renewable_share,
    (
        market.price_eur_mwh is not null
        and market.grid_load_mwh is not null
        and coalesce(generation.required_sources_reported, 0) = required.required_sources
    ) as is_complete
from hours
cross join required
left join market on hours.hour_utc = market.hour_utc
left join generation on hours.hour_utc = generation.hour_utc
