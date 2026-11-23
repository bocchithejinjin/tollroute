# trixie は GDAL 3.10。bookworm（3.6）だと Django の gis.W001（安全面の警告）が出る。
FROM python:3.12-trixie

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        binutils gdal-bin libgdal-dev libgeos-dev libproj-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash vscode

ENV VIRTUAL_ENV=/home/vscode/.venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

USER vscode
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir -r /tmp/requirements.txt
