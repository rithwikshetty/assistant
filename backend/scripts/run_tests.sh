#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"

# Test runner script
echo "Running assistant backend tests..."

echo "Running event cutover guard..."
python scripts/check_event_cutover.py

# Set test environment
export TESTING=true
export DATABASE_URL="postgresql://postgres:postgres@localhost/assist_test"

# Run pytest with coverage when plugin is available; otherwise run plain pytest.
if python -c "import pytest_cov" >/dev/null 2>&1; then
  python -m pytest tests/ -v --cov=app --cov-report=html --cov-report=term-missing
  echo "Tests completed. Coverage report available in htmlcov/index.html"
else
  echo "pytest-cov not installed; running tests without coverage."
  python -m pytest tests/ -v
  echo "Tests completed."
fi
