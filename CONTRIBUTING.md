# Contributing to Inbox0

Thank you for your interest in contributing! This document covers how to get set up and submit changes.

## Getting started

1. Fork the repo and clone your fork
2. Follow the [Quick start](README.md#quick-start) in the README to set up your local environment
3. Create a branch for your change:

   ```bash
   git checkout -b your-branch-name
   ```

## Making changes

- Follow existing code style — the project uses `black` for formatting and `isort` for import ordering
- Run pre-commit hooks before pushing:

  ```bash
  pip install pre-commit
  pre-commit install
  pre-commit run --all-files
  ```

- Add or update tests for any changed behaviour under `tests/`
- Run the test suite locally before opening a PR:

  ```bash
  pytest
  ```

## Submitting a PR

- PR titles must follow the prefix convention: `[ENH]`, `[BUG]`, `[DOC]`, or `[MNT]`
- Fill out the PR template in full
- Keep PRs focused to one change per PR 

## Reporting bugs or requesting features

Open an issue at [github.com/ksharma6/inbox_zero/issues](https://github.com/ksharma6/inbox_zero/issues) and provide as much context as possible.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Please be respectful and constructive in all interactions.
