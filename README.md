# json-rpc-Scan

[![CI](https://github.com/MysticRyuujin/json-rpc-scan/actions/workflows/ci.yml/badge.svg)](https://github.com/MysticRyuujin/json-rpc-scan/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/json-rpc-scan.svg)](https://badge.fury.io/py/json-rpc-scan)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)

Scans Ethereum (EVM) Blocks via JSON-RPC and looks for client diffs.

## Features

- 🔍 Compare JSON-RPC responses across multiple Ethereum clients
- 🚀 Asynchronous requests for high performance
- 📊 Visual diff reporting (human-readable and machine-readable)
- 🐳 Docker support for easy deployment
- ⚡ Built with modern Python (3.13+)

## Requirements

- Python 3.13 or higher
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Installation

### Using uv (Recommended)

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/MysticRyuujin/json-rpc-scan.git
cd json-rpc-scan

# Create virtual environment and install dependencies
uv sync
```

### Using pip

```bash
pip install json-rpc-scan
```

### Using Docker

```bash
docker pull ghcr.io/MysticRyuujin/json-rpc-scan:latest

# Run with Docker
docker run --rm ghcr.io/MysticRyuujin/json-rpc-scan:latest --help
```

## Development Setup

### Prerequisites

- [Python 3.13+](https://www.python.org/downloads/)
- [pyenv](https://github.com/pyenv/pyenv) (optional, for Python version management)
- [uv](https://github.com/astral-sh/uv) (modern Python package manager)
- [direnv](https://direnv.net/) (optional, for automatic environment activation)

### Quick Start

```bash
# Clone the repository
git clone https://github.com/MysticRyuujin/json-rpc-scan.git
cd json-rpc-scan

# If using pyenv + direnv (recommended)
direnv allow

# Or manually set up with uv
uv venv --python 3.13
source .venv/bin/activate
uv sync --all-extras

# Install pre-commit hooks
pre-commit install
pre-commit install --hook-type commit-msg

# Run tests
pytest

# Run linting
ruff check src/
ruff format --check src/
mypy src/
```

### Using pyenv

```bash
# Install Python 3.13
pyenv install 3.13

# Set local Python version (creates .python-version)
pyenv local 3.13
```

### Using direnv

The project includes a `.envrc` file that automatically:

- Activates the correct Python version via pyenv
- Creates and activates a virtual environment
- Watches for dependency changes

```bash
# Allow direnv to manage the environment
direnv allow
```

## Configuration

Create a `config.yaml` file (copy from `config.example.yaml`):

```yaml
endpoints:
  - name: Geth
    url: http://localhost:8545
  - name: Nethermind
    url: http://localhost:8546
```

## Usage

```bash
# Run the scanner
json-rpc-scan --help

# Or using Python module
python -m json_rpc_scan --help
```

## Project Structure

```text
json-rpc-scan/
├── .github/
│   ├── workflows/           # GitHub Actions workflows
│   │   ├── ci.yml          # Continuous Integration
│   │   ├── release.yml     # Release automation
│   │   └── release-please.yml
│   ├── dependabot.yml      # Dependency updates
│   └── release-please-*.json
├── src/
│   └── json_rpc_scan/      # Main package
│       ├── __init__.py
│       ├── __main__.py     # CLI entry point
│       ├── __version__.py  # Version info
│       └── py.typed        # PEP 561 marker
├── tests/                   # Test suite
├── .envrc                   # direnv configuration
├── .pre-commit-config.yaml  # Pre-commit hooks
├── .python-version          # pyenv Python version
├── Dockerfile               # Docker build
├── pyproject.toml           # Project configuration
└── README.md
```

## Code Quality

This project uses several tools to maintain code quality:

| Tool | Purpose |
| ------ | --------- |
| [black](https://github.com/psf/black) | Code formatting |
| [ruff](https://github.com/astral-sh/ruff) | Linting and import sorting |
| [mypy](https://mypy-lang.org/) | Static type checking |
| [pytest](https://pytest.org/) | Testing framework |
| [pre-commit](https://pre-commit.com/) | Git hooks |
| [bandit](https://bandit.readthedocs.io/) | Security scanning |

### Running Checks Locally

```bash
# Format code
ruff format src/ tests/

# Lint code
ruff check src/ tests/

# Type check
mypy src/

# Run tests
pytest

# Run all pre-commit hooks
pre-commit run --all-files
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/amazing-feature`)
3. Make your changes
4. Run the test suite (`pytest`)
5. Run linting (`pre-commit run --all-files`)
6. Commit your changes using [conventional commits](https://www.conventionalcommits.org/)
7. Push to your branch (`git push origin feat/amazing-feature`)
8. Open a Pull Request

### Commit Message Format

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`

## Release Process

This project uses [release-please](https://github.com/googleapis/release-please) for automated releases:

1. Commits to `main` are analyzed for conventional commit messages
2. Release PRs are automatically created/updated
3. Merging a release PR triggers:
   - PyPI package publication
   - Docker image build and push to GHCR
   - GitHub release creation

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Inspired by the need for better Ethereum client compatibility testing
- Built with modern Python tooling from the [Astral](https://astral.sh/) ecosystem
