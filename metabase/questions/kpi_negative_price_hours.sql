-- Share of complete hours with a negative day-ahead price
select round((avg(is_negative_price::integer) * 100)::numeric, 2) as negative_price_hours_pct
from analytics_marts.fct_power_hourly
where is_complete
