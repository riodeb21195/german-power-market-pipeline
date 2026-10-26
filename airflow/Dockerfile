# Airflow with the power_market package, the dbt project and the DAG baked in.
# Build context is the repository root: docker build -f airflow/Dockerfile .
ARG AIRFLOW_VERSION=3.3.2
ARG PYTHON_VERSION=3.12
FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}

ARG AIRFLOW_VERSION
ARG PYTHON_VERSION
# keep in sync with the `dbt` dependency group in pyproject.toml
ARG DBT_CORE_VERSION=1.12.6
ARG DBT_POSTGRES_VERSION=1.11.0

# dbt lives in its own virtualenv: its dependency pins must not fight with Airflow's constraints
USER root
RUN python -m venv /opt/dbt-venv \
    && /opt/dbt-venv/bin/pip install --no-cache-dir \
        "dbt-core==${DBT_CORE_VERSION}" "dbt-postgres==${DBT_POSTGRES_VERSION}" \
    && chown -R airflow:root /opt/dbt-venv
USER airflow

# The pipeline package, installed next to Airflow and kept compatible via the official constraints
COPY --chown=airflow:root pyproject.toml README.md /opt/power_market/
COPY --chown=airflow:root src /opt/power_market/src
RUN pip install --no-cache-dir \
        "apache-airflow==${AIRFLOW_VERSION}" \
        /opt/power_market \
        --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

# dbt project with its packages resolved at build time (no network needed at runtime)
COPY --chown=airflow:root dbt /opt/dbt
WORKDIR /opt/dbt
RUN rm -rf target logs dbt_packages \
    && DBT_PROFILES_DIR=/opt/dbt WAREHOUSE_PASSWORD=unused /opt/dbt-venv/bin/dbt deps
WORKDIR /opt/airflow

COPY --chown=airflow:root airflow/dags /opt/airflow/dags
COPY --chown=airflow:root airflow/tests /opt/airflow/tests
# mount point for the generated simple-auth-manager passwords file (named volume)
RUN mkdir -p /opt/airflow/auth

ENV DBT_PROJECT_DIR=/opt/dbt \
    DBT_PROFILES_DIR=/opt/dbt \
    DBT_BIN=/opt/dbt-venv/bin/dbt
