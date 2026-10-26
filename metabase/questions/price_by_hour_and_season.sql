-- Mean price per local hour of day and season (weighted over all weekdays)
select
    hour_of_day,
    season,
    round((sum(avg_price_eur_mwh * hours_observed) / sum(hours_observed))::numeric, 1)
        as avg_price_eur_mwh
from analytics_marts.mart_hourly_profile
group by hour_of_day, season, season_order
order by season_order, hour_of_day
