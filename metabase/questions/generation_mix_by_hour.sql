-- Average generation per local hour of day by category, complete hours only
select
    gen.hour_key as hour_of_day,
    src.category,
    round((sum(gen.generation_mwh) / count(distinct gen.hour_utc))::numeric) as avg_generation_mwh
from analytics_marts.fct_generation_hourly as gen
inner join analytics_marts.dim_energy_source as src on gen.energy_source_key = src.energy_source_key
inner join analytics_marts.fct_power_hourly as power on gen.hour_utc = power.hour_utc
where power.is_complete
group by gen.hour_key, src.category
order by gen.hour_key, src.category
