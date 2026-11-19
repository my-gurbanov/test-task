install:
    uv sync --locked

lint:
    uv run --locked ruff format --check .
    uv run --locked ruff check .
    uv run --locked ty check .
    uv run --locked flake8 payment_processing tests

test *args:
    docker compose run --build --rm --use-aliases tests python -m pytest -n auto {{ args }}

agent-fix:
    uv run --locked ruff format .
    uv run --locked ruff check --fix .
    uv run --locked ty check .
