FROM ghcr.io/osgeo/gdal:ubuntu-full-3.11.0

WORKDIR /app

# needed for pipx
ENV PATH="/root/.local/bin:$PATH"
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Install pipx and use it to install Poetry
RUN apt-get update && apt-get install -y python3-pip pipx && \
    pipx install poetry

COPY . /app

# Install dependencies in a virtualenv managed by Poetry
RUN poetry config virtualenvs.in-project true \
    && poetry install --no-interaction --no-ansi --only main

CMD ["poetry", "run", "python", "/app/calc_yearly_acc/calc_yearly_acc.py", "latest"]
