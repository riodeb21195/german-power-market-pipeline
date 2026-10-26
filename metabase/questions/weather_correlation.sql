-- Correlation of weather with price and renewable share, per season
select
    season,
    hours_observed,
    round(corr_price_wind::numeric, 2) as price_vs_wind,
    round(corr_price_radiation::numeric, 2) as price_vs_solar_radiation,
    round(corr_price_temperature::numeric, 2) as price_vs_temperature,
    round(corr_share_wind::numeric, 2) as renewables_vs_wind,
    round(corr_share_radiation::numeric, 2) as renewables_vs_solar_radiation,
    round(price_change_per_wind_ms::numeric, 1) as eur_mwh_per_wind_ms
from analytics_marts.mart_weather_correlation
order by season_order
