-- Mean renewable share per local hour of day and season (weighted over all weekdays)
select
    hour_of_day,
    season,
    round((sum(avg_renewable_share * hours_observed) / sum(hours_observed) * 100)::numeric, 1)
        as renewable_share_pct
from analytics_marts.mart_hourly_profile
group by hour_of_day, season, season_order
order by season_order, hour_of_day
