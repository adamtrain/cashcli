# cashcli — common tasks. Requires uv (https://docs.astral.sh/uv/): `brew install uv`.

.PHONY: install uninstall reinstall sync test lint format check build clean

## Install the `cash` command onto PATH (uv's tool bin dir, usually ~/.local/bin).
install:
	uv tool install --force --reinstall .
	@uv tool update-shell >/dev/null 2>&1 || true
	@echo "installed: $$(command -v cash || echo 'cash not on PATH yet — open a new shell or add $$(uv tool dir --bin) to PATH')"

uninstall:
	uv tool uninstall cashcli

reinstall: install

## Dev environment (.venv with pytest + ruff).
sync:
	uv sync

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

check: lint test

build:
	uv build

clean:
	rm -rf dist build .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
