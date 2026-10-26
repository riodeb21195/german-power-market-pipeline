-- Generation per hour and energy source with its classification
select
    stg.hour_utc,
    series.series_slug as energy_source_slug,
    series.category,
    series.is_renewable,
    series.required_for_completeness,
    stg.value as generation_mwh
from {{ ref('stg_smard__timeseries') }} as stg
inner join {{ ref('smard_series') }} as series
    on
        stg.filter_id = series.smard_filter_id
        and stg.region = series.region
where series.kind = 'generation'
