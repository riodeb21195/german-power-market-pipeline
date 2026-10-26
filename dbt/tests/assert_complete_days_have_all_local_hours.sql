-- Every local day that is fully in the past must have exactly as many hours as the day has
-- (23/24/25 because of daylight saving time). Catches gaps and timezone bugs.
-- Days before the first loaded hour and the still-incomplete recent days are skipped.
with bounds as (
    select
        min(hour_utc) as first_hour,
        max(hour_utc) filter (where is_complete) as last_complete_hour
    from {{ ref('fct_power_hourly') }}
),

per_day as (
    select
        date_key,
        count(*) as fact_hours
    from {{ ref('fct_power_hourly') }}
    group by date_key
)

select
    dates.date_day,
    dates.hours_in_day,
    coalesce(per_day.fact_hours, 0) as fact_hours
from {{ ref('dim_date') }} as dates
cross join bounds
left join per_day on dates.date_key = per_day.date_key
where
    {{ local_day_start('dates.date_day') }} >= bounds.first_hour
    and {{ local_day_start('dates.date_day + 1') }} <= bounds.last_complete_hour
    and coalesce(per_day.fact_hours, 0) <> dates.hours_in_day
