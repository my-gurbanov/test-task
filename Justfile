install:
    uv sync --locked

lint:
    uv run --locked ruff format --check .
    uv run --locked ruff check .
    uv run --locked ty check .
    uv run --locked flake8 payment_processing tests

test *args:
    #!/bin/sh
    set -eu
    export COMPOSE_PROJECT_NAME="payment-processing-test-$$" PAYMENT_HTTP_PORT=0
    trap 'docker compose down --volumes' EXIT
    if ! docker compose run --build --rm --use-aliases tests python -m pytest -n auto {{ args }}; then
        docker compose logs --no-color
        exit 1
    fi

agent-fix:
    uv run --locked ruff format .
    uv run --locked ruff check --fix .
    uv run --locked ty check .
