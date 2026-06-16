# Contributing to Social Graph

Thank you for your interest in contributing to Social Graph! We welcome bug reports, feature suggestions, documentation improvements, and pull requests.

## Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-username/social-graph.git
   cd social-graph
   ```

2. **Set up a virtual environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**:
   Install the package in editable mode along with development tools:
   ```bash
   pip install -e ".[dev]"
   ```

4. **Install pre-commit hooks**:
   ```bash
   pre-commit install
   ```
   This automatically runs Ruff linter/formatter on your changes before committing.

## Code Style & Formatting

We use **Ruff** for Python code linting and formatting. You can run these manually using the project's Makefile:

```bash
# Run lint checks
make lint

# Auto-format and fix lint errors
make format
```

All Python files should have clean type annotations and follow standard PEP 8 naming conventions.

## Running Tests

We use **pytest** for testing. Please ensure all tests pass and your changes maintain high test coverage:

```bash
# Run all unit and E2E tests
make test

# Check test coverage report
pytest --cov=socialgraph tests/ -v
```

## Submitting Pull Requests

1. Create a descriptive branch for your changes: `git checkout -b feature/cool-new-feature`
2. Implement your changes, add tests, and run lint checks.
3. Commit your changes: `git commit -am "feat: add support for X"`
4. Push to your fork and submit a Pull Request to the `main` branch.
5. Ensure the GitHub Actions CI build passes successfully.
