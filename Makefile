PYTHON ?= python
PIP ?= $(PYTHON) -m pip
UVICORN ?= uvicorn
APP_MODULE ?= backend.main:app
HOST ?= 0.0.0.0
PORT ?= 8001
CONDA ?= conda
CONDA_ENV ?= trustflow-banking-agent-langgraph

.PHONY: help venv install run run-prod db-load-sql db-load-csv clean

help:
	@echo "Available targets:"
	@echo "  make venv         Create a conda environment"
	@echo "  make install      Install Python dependencies from requirements.txt"
	@echo "  make run          Start the FastAPI server with auto-reload"
	@echo "  make run-prod     Start the FastAPI server without auto-reload"
	@echo "  make db-load-sql  Load data/sql/all_in_one.sql into DATABASE_URL"
	@echo "  make db-load-csv  Load CSV mock data into PostgreSQL"
	@echo "  make clean       Remove Python cache files"

venv:
	$(CONDA) create -n $(CONDA_ENV) python=3.11 -y
	@echo "Conda environment created: $(CONDA_ENV)"
	@echo "Activate it with: conda activate $(CONDA_ENV)"

install:
	$(PIP) install -r requirements.txt

run:
	$(PYTHON) -m $(UVICORN) $(APP_MODULE) --reload --host $(HOST) --port $(PORT)

run-prod:
	$(PYTHON) -m $(UVICORN) $(APP_MODULE) --host $(HOST) --port $(PORT)

db-load-sql:
	psql "$$DATABASE_URL" -f data/sql/all_in_one.sql

db-load-csv:
	$(PYTHON) data/scripts/load_csv_to_postgres.py

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
