{% macro local_day_start(date_expression) -%}
    {#- timestamptz of local midnight for a date expression in the analysis timezone -#}
    (({{ date_expression }})::date::timestamp at time zone '{{ var("analysis_timezone") }}')
{%- endmacro %}


{% macro to_local(timestamptz_expression) -%}
    {#- wall-clock timestamp in the analysis timezone -#}
    (({{ timestamptz_expression }}) at time zone '{{ var("analysis_timezone") }}')
{%- endmacro %}


{% macro date_key(date_expression) -%}
    {#- integer yyyymmdd key -#}
    (to_char(({{ date_expression }})::date, 'YYYYMMDD')::integer)
{%- endmacro %}
