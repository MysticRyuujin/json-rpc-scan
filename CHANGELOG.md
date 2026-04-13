# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0](https://github.com/MysticRyuujin/json-rpc-scan/compare/v0.1.1...v0.2.0) (2026-04-13)


### Features

* add exponential-backoff retry to RPCClient.call ([9a0e6b6](https://github.com/MysticRyuujin/json-rpc-scan/commit/9a0e6b65af8fb93edced86231ef522cef8b187ea))
* add ResponseComparator with spec-safe + opt-in normalizers ([9a0e6b6](https://github.com/MysticRyuujin/json-rpc-scan/commit/9a0e6b65af8fb93edced86231ef522cef8b187ea))
* response comparator, runner extraction, retry, QA fixes ([9a0e6b6](https://github.com/MysticRyuujin/json-rpc-scan/commit/9a0e6b65af8fb93edced86231ef522cef8b187ea))


### Bug Fixes

* --methods unknown_foo silently exited 0 ([9a0e6b6](https://github.com/MysticRyuujin/json-rpc-scan/commit/9a0e6b65af8fb93edced86231ef522cef8b187ea))
* 'No differences found.' printed when diffs were present ([9a0e6b6](https://github.com/MysticRyuujin/json-rpc-scan/commit/9a0e6b65af8fb93edced86231ef522cef8b187ea))
* both-endpoints-dead reported '0 diffs, exit 0' ([9a0e6b6](https://github.com/MysticRyuujin/json-rpc-scan/commit/9a0e6b65af8fb93edced86231ef522cef8b187ea))
* trace_* methods silently ran against Geth (compat matrix) ([9a0e6b6](https://github.com/MysticRyuujin/json-rpc-scan/commit/9a0e6b65af8fb93edced86231ef522cef8b187ea))

## [0.0.2](https://github.com/MysticRyuujin/json-rpc-scan/compare/v0.0.1...v0.0.2) (2026-03-09)


### Bug Fixes

* correct image source label URL in Dockerfile ([2361968](https://github.com/MysticRyuujin/json-rpc-scan/commit/2361968632ad2bc35e8c66c7e5be1120bb1ee7be))

## [Unreleased]

### Added

- Initial project setup with modern Python tooling
- GitHub Actions CI/CD workflows
- Docker support with multi-stage builds
- Pre-commit hooks for code quality
- Dependabot for automated dependency updates
- Release-please for automated releases
