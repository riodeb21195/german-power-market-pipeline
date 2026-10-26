-- What role does the weather play? Pearson correlations and a simple linear slope between the
-- national weather proxy and price / renewable share, per season and for the whole year.
-- Correlation is not causation: wind lowers prices through the merit order, but season,
-- demand and fuel prices act at the same time.
with hours as (
    select
        fct.*,
        dates.season,
        dates.season_order
    from {{ ref('fct_power_hourly') }} as fct
    inner join {{ ref('dim_date') }} as dates on fct.date_key = dates.date_key
    where fct.is_complete and fct.weather_locations_reported > 0
),

by_season as (
    select
        season,
        season_order,
        count(*) as hours_observed,
        corr(price_eur_mwh, avg_wind_speed_100m_ms) as corr_price_wind,
        corr(price_eur_mwh, north_wind_speed_100m_ms) as corr_price_north_wind,
        corr(price_eur_mwh, avg_shortwave_radiation_w_m2) as corr_price_radiation,
        corr(price_eur_mwh, avg_temperature_c) as corr_price_temperature,
        corr(renewable_share, avg_wind_speed_100m_ms) as corr_share_wind,
        corr(renewable_share, avg_shortwave_radiation_w_m2) as corr_share_radiation,
        corr(price_eur_mwh, renewable_share) as corr_price_share,
        regr_slope(price_eur_mwh, avg_wind_speed_100m_ms) as price_change_per_wind_ms
    from hours
    group by season, season_order
),

whole_year as (
    select
        'all' as season,
        0 as season_order,
        count(*) as hours_observed,
        corr(price_eur_mwh, avg_wind_speed_100m_ms) as corr_price_wind,
        corr(price_eur_mwh, north_wind_speed_100m_ms) as corr_price_north_wind,
        corr(price_eur_mwh, avg_shortwave_radiation_w_m2) as corr_price_radiation,
        corr(price_eur_mwh, avg_temperature_c) as corr_price_temperature,
        corr(renewable_share, avg_wind_speed_100m_ms) as corr_share_wind,
        corr(renewable_share, avg_shortwave_radiation_w_m2) as corr_share_radiation,
        corr(price_eur_mwh, renewable_share) as corr_price_share,
        regr_slope(price_eur_mwh, avg_wind_speed_100m_ms) as price_change_per_wind_ms
    from hours
)

select * from whole_year
union all
select * from by_season
