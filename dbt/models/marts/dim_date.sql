-- Calendar of local (Europe/Berlin) dates from the analysis start to two days ahead
-- (day-ahead prices are known for tomorrow).
with days as (
    select generate_series(
        '{{ var("analysis_start_date") }}'::date,
        (current_date + 2)::date,
        interval '1 day'
    )::date as date_day
)

select
    {{ date_key('date_day') }} as date_key,
    date_day,
    extract(year from date_day)::integer as year,
    extract(quarter from date_day)::integer as quarter,
    extract(month from date_day)::integer as month,
    to_char(date_day, 'FMMonth') as month_name,
    extract(day from date_day)::integer as day_of_month,
    extract(isodow from date_day)::integer as iso_day_of_week,
    to_char(date_day, 'FMDay') as day_name,
    extract(isodow from date_day) >= 6 as is_weekend,
    extract(week from date_day)::integer as iso_week,
    -- meteorological seasons
    case
        when extract(month from date_day) in (12, 1, 2) then 'winter'
        when extract(month from date_day) in (3, 4, 5) then 'spring'
        when extract(month from date_day) in (6, 7, 8) then 'summer'
        else 'autumn'
    end as season,
    case
        when extract(month from date_day) in (12, 1, 2) then 4
        when extract(month from date_day) in (3, 4, 5) then 1
        when extract(month from date_day) in (6, 7, 8) then 2
        else 3
    end as season_order,
    -- hours of the local day: 23 or 25 on DST switch days
    extract(
        epoch from {{ local_day_start('date_day + 1') }} - {{ local_day_start('date_day') }}
    )::integer / 3600 as hours_in_day
from days
