-- Price and renewable share by wind speed at 100 m in northern Germany (1 m/s buckets)
select
    least(floor(north_wind_speed_100m_ms), 15)::integer as wind_speed_ms,
    count(*) as hours,
    round(avg(price_eur_mwh)::numeric, 1) as avg_price_eur_mwh,
    round((avg(renewable_share) * 100)::numeric, 1) as renewable_share_pct
from analytics_marts.fct_power_hourly
where is_complete and north_wind_speed_100m_ms is not null
group by 1
order by 1
