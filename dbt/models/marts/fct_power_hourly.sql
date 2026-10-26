-- Grain: one row per hour (UTC). Market, generation totals and the national weather proxy.
with power as (
    select * from {{ ref('int_power_hourly') }}
),

weather as (
    select * from {{ ref('int_weather_hourly') }}
)

select
    power.hour_utc,
    {{ to_local('power.hour_utc') }} as hour_local,
    {{ date_key(to_local('power.hour_utc')) }} as date_key,
    extract(hour from {{ to_local('power.hour_utc') }})::integer as hour_key,
    power.price_eur_mwh,
    power.grid_load_mwh,
    power.total_generation_mwh,
    power.renewable_generation_mwh,
    power.conventional_generation_mwh,
    power.storage_generation_mwh,
    power.wind_generation_mwh,
    power.solar_generation_mwh,
    power.renewable_share,
    power.price_eur_mwh < 0 as is_negative_price,
    power.is_complete,
    weather.avg_temperature_c,
    weather.avg_wind_speed_100m_ms,
    weather.north_wind_speed_100m_ms,
    weather.avg_shortwave_radiation_w_m2,
    weather.avg_cloud_cover_pct,
    coalesce(weather.locations_reported, 0) as weather_locations_reported
from power
left join weather on power.hour_utc = weather.hour_utc
