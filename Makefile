# Makefile for common development tasks

.PHONY: help install install-dev format lint type-check test clean run

help:  ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install production dependencies
	pip install -r requirements.txt

install-dev:  ## Install development dependencies
	pip install -r requirements.txt -r requirements-dev.txt
	pre-commit install

format:  ## Format code with black and isort
	@echo "Running isort..."
	isort .
	@echo "Running black..."
	black .

lint:  ## Run ruff linter
	@echo "Running ruff..."
	ruff check .

lint-fix:  ## Run ruff linter with auto-fix
	@echo "Running ruff with auto-fix..."
	ruff check --fix .

type-check:  ## Run mypy type checker
	@echo "Running mypy..."
	mypy .

test:  ## Run tests with pytest
	@echo "Running pytest..."
	pytest

test-cov:  ## Run tests with coverage report
	@echo "Running pytest with coverage..."
	pytest --cov=. --cov-report=html --cov-report=term

clean:  ## Clean build artifacts and caches
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true

pre-commit:  ## Run all pre-commit hooks on all files
	pre-commit run --all-files

run:  ## Run the main application
	python main.py

check-all:  ## Run all checks (format, lint, type-check)
	@echo "=== Running all checks ==="
	@$(MAKE) format
	@$(MAKE) lint
	@$(MAKE) type-check
	@echo "=== All checks completed ==="
