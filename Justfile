install:
    uv sync --locked

run:
    docker compose up --build -d

lint:
    uv run --locked ruff check --fix .
    uv run --locked ruff format .
    uv run --locked ty check .
    uv run --locked flake8 payment_processing tests

test *args:
    #!/bin/sh
    export COMPOSE_PROJECT_NAME="payment-processing-test-$$" PAYMENT_HTTP_PORT=0
    trap 'docker compose down --volumes' EXIT
    docker compose run --build --rm --use-aliases tests python -m pytest -n auto {{ args }}
