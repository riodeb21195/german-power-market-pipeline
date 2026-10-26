select
    md5(series_slug) as energy_source_key,
    series_slug as energy_source_slug,
    smard_filter_id,
    initcap(replace(series_slug, '_', ' ')) as energy_source_name,
    category,
    is_renewable
from {{ ref('smard_series') }}
where kind = 'generation'
