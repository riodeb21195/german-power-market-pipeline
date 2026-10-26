-- Day-ahead price and grid load side by side
with series as (
    select
        stg.hour_utc,
        stg.value,
        meta.kind
    from {{ ref('stg_smard__timeseries') }} as stg
    inner join {{ ref('smard_series') }} as meta
        on
            stg.filter_id = meta.smard_filter_id
            and stg.region = meta.region
    where meta.kind in ('price', 'load')
)

select
    hour_utc,
    max(value) filter (where kind = 'price') as price_eur_mwh,
    max(value) filter (where kind = 'load') as grid_load_mwh
from series
group by hour_utc
