.PHONY: help setup install clean test run lint venv

# Default Python interpreter
PYTHON := python3
VENV_DIR := venv
VENV_BIN := $(VENV_DIR)/bin

help:
	@echo "Agent GW - Available Commands"
	@echo "=============================="
	@echo ""
	@echo "Setup:"
	@echo "  make setup       - Create virtual environment and install dependencies"
	@echo "  make venv        - Create virtual environment only"
	@echo "  make install     - Install/update dependencies in existing venv"
	@echo ""
	@echo "Development:"
	@echo "  make run         - Start all services (ARF, ACF, MOQT Relay)"
	@echo "  make run-arf     - Start ARF server only (port 9001)"
	@echo "  make run-acf     - Start ACF server only (port 9002)"
	@echo "  make run-moqt    - Start MOQT Relay only (port 9003)"
	@echo ""
	@echo "Testing:"
	@echo "  make test        - Run all tests"
	@echo "  make test-unit   - Run unit tests only"
	@echo "  make test-int    - Run integration tests only"
	@echo "  make coverage    - Run tests with coverage report"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean       - Remove virtual environment and cache files"
	@echo "  make clean-pyc   - Remove Python cache files only"
	@echo "  make lint        - Run code linting (if available)"
	@echo ""

# Setup commands
setup:
	@echo "Setting up Agent GW environment..."
	@./setup.sh

venv:
	@echo "Creating virtual environment..."
	$(PYTHON) -m venv $(VENV_DIR)
	@echo "Virtual environment created at $(VENV_DIR)"
	@echo "Activate it with: source $(VENV_DIR)/bin/activate"

install: venv
	@echo "Installing dependencies..."
	@$(VENV_BIN)/pip install --upgrade pip
	@$(VENV_BIN)/pip install -r requirements.txt
	@echo "Dependencies installed"

# Run commands
run: venv
	@echo "Starting Agent GW services..."
	@$(VENV_BIN)/python main.py

run-arf: venv
	@echo "Starting ARF server on port 9001..."
	@$(VENV_BIN)/uvicorn arf_server:app --host 0.0.0.0 --port 9001

run-acf: venv
	@echo "Starting ACF server on port 9002..."
	@$(VENV_BIN)/python acf_server.py

run-moqt: venv
	@echo "Starting MOQT Relay on port 9003..."
	@$(VENV_BIN)/python moqt_relay.py

# Testing commands
test: venv
	@echo "Running all tests..."
	@$(VENV_BIN)/python run_tests.py -v

test-unit: venv
	@echo "Running unit tests..."
	@$(VENV_BIN)/python run_tests.py unit -v

test-int: venv
	@echo "Running integration tests..."
	@$(VENV_BIN)/python run_tests.py integration -v

coverage: venv
	@echo "Running tests with coverage..."
	@$(VENV_BIN)/python run_tests.py -c

# Maintenance commands
clean: clean-pyc
	@echo "Removing virtual environment..."
	@rm -rf $(VENV_DIR)
	@rm -rf htmlcov/
	@rm -rf .pytest_cache/
	@rm -rf .coverage
	@echo "Cleanup complete"

clean-pyc:
	@echo "Removing Python cache files..."
	@find . -type f -name "*.py[co]" -delete
	@find . -type d -name "__pycache__" -delete
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "Cache files removed"

lint: venv
	@echo "Running linters..."
	@if command -v $(VENV_BIN)/flake8 >/dev/null 2>&1; then \
		$(VENV_BIN)/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics; \
	else \
		echo "flake8 not installed, skipping linting"; \
	fi
