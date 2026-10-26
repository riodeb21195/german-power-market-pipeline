-- Renewable + conventional + storage must equal total generation (tolerance for float sums).
select
    hour_utc,
    total_generation_mwh,
    renewable_generation_mwh + conventional_generation_mwh + storage_generation_mwh as category_sum
from {{ ref('fct_power_hourly') }}
where
    total_generation_mwh is not null
    and abs(
        total_generation_mwh
        - (renewable_generation_mwh + conventional_generation_mwh + storage_generation_mwh)
    ) > 0.01
