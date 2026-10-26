with source as (
    select * from {{ source('raw', 'smard_timeseries') }}
)

select
    filter_id,
    region,
    ts as hour_utc,
    value,
    loaded_at
from source
where ts >= {{ local_day_start("'" ~ var('analysis_start_date') ~ "'") }}
