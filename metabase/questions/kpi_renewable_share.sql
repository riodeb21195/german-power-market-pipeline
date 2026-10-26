-- Renewable share of total generation over all complete hours
select
    round((sum(renewable_generation_mwh) / sum(total_generation_mwh) * 100)::numeric, 1)
        as renewable_share_pct
from analytics_marts.fct_power_hourly
where is_complete
