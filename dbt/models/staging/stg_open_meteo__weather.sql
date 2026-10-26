with source as (
    select * from {{ source('raw', 'weather_hourly') }}
)

select
    location as location_slug,
    ts as hour_utc,
    temperature_2m as temperature_c,
    wind_speed_100m / 3.6 as wind_speed_100m_ms,
    shortwave_radiation as shortwave_radiation_w_m2,
    cloud_cover as cloud_cover_pct,
    loaded_at
from source
where ts >= {{ local_day_start("'" ~ var('analysis_start_date') ~ "'") }}
