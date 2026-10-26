-- Local hour of day (0-23). On the October DST day the hour 02:00 occurs twice; both hours
-- point to hour_key 2.
select
    hour_of_day as hour_key,
    hour_of_day,
    lpad(hour_of_day::text, 2, '0') || ':00' as hour_label,
    case
        when hour_of_day < 6 then 'night'
        when hour_of_day < 10 then 'morning'
        when hour_of_day < 16 then 'midday'
        when hour_of_day < 20 then 'evening'
        else 'late evening'
    end as day_part,
    -- base/peak convention of the German power futures market: peak = 08:00-20:00
    hour_of_day between 8 and 19 as is_peak_hour
from generate_series(0, 23) as hour_of_day
