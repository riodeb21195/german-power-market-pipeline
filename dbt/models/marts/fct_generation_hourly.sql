-- Grain: one row per hour and energy source
select
    gen.hour_utc,
    md5(gen.energy_source_slug) as energy_source_key,
    {{ date_key(to_local('gen.hour_utc')) }} as date_key,
    extract(hour from {{ to_local('gen.hour_utc') }})::integer as hour_key,
    gen.generation_mwh
from {{ ref('int_generation_hourly') }} as gen
