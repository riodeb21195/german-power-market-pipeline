-- National weather proxy: unweighted mean over all locations plus a northern wind index
with weather as (
    select
        weather.*,
        locations.region
    from {{ ref('stg_open_meteo__weather') }} as weather
    inner join {{ ref('weather_locations') }} as locations
        on weather.location_slug = locations.location_slug
)

select
    hour_utc,
    avg(temperature_c) as avg_temperature_c,
    avg(wind_speed_100m_ms) as avg_wind_speed_100m_ms,
    avg(wind_speed_100m_ms) filter (where region = 'north') as north_wind_speed_100m_ms,
    avg(shortwave_radiation_w_m2) as avg_shortwave_radiation_w_m2,
    avg(cloud_cover_pct) as avg_cloud_cover_pct,
    count(*) as locations_reported
from weather
group by hour_utc
