# Tests

Pytest suite. The plugin's runtime DNF dependencies (`dnf`, `hawkey`) are
mocked, so tests run on any host with Python 3.9+.

## Run

```bash
pip install -e ".[test]"
pytest
```

## Layout

* `test_*.py` — one file per source module. Files ending in `_integration.py`
  exercise multiple modules together.
* `conftest.py` — shared pytest fixtures and DNF mocks.
* `helpers.py` — small helpers used across test files.
* `fixtures/` — sample `support_info.xml` documents (legacy and 1.0) plus
  the 1.0 XSD, used by the parsing and conversion tests.
