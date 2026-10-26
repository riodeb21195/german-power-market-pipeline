-- Average day-ahead price over all complete hours
select round(avg(price_eur_mwh)::numeric, 1) as avg_price_eur_mwh
from analytics_marts.fct_power_hourly
where is_complete
