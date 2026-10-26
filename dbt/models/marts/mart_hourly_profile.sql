-- When is power cheapest and greenest? Average profile per season, weekday and local hour,
-- ranked within each (season, weekday). Only complete hours are used.
with hours as (
    select
        fct.*,
        dates.season,
        dates.season_order,
        dates.iso_day_of_week,
        dates.day_name,
        dates.is_weekend
    from {{ ref('fct_power_hourly') }} as fct
    inner join {{ ref('dim_date') }} as dates on fct.date_key = dates.date_key
    where fct.is_complete
),

profile as (
    select
        season,
        season_order,
        iso_day_of_week,
        day_name,
        is_weekend,
        hour_key as hour_of_day,
        count(*) as hours_observed,
        avg(price_eur_mwh) as avg_price_eur_mwh,
        percentile_cont(0.5) within group (order by price_eur_mwh) as median_price_eur_mwh,
        avg(renewable_share) as avg_renewable_share,
        avg(is_negative_price::integer) as negative_price_hour_share,
        avg(avg_wind_speed_100m_ms) as avg_wind_speed_100m_ms,
        avg(avg_shortwave_radiation_w_m2) as avg_shortwave_radiation_w_m2
    from hours
    group by season, season_order, iso_day_of_week, day_name, is_weekend, hour_key
)

select
    *,
    rank() over (
        partition by season, iso_day_of_week order by avg_price_eur_mwh
    ) as price_rank,
    rank() over (
        partition by season, iso_day_of_week order by avg_renewable_share desc
    ) as green_rank
from profile
