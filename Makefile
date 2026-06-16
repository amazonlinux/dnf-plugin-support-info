# Minimal Makefile for building the source tarball that
# dnf-plugin-support-info.spec consumes. Downstream packagers use this to
# produce a clean source archive without invoking setuptools directly.

PACKAGE = dnf-plugin-support-info
VERSION = $(shell awk -F'"' '/^version[[:space:]]*=/ { print $$2; exit }' pyproject.toml)
TARBALL = $(PACKAGE)-$(VERSION).tar.gz
STAGE   = $(PACKAGE)-$(VERSION)

.PHONY: sources clean

sources:
	@test -n "$(VERSION)" || (echo "ERROR: could not read version from pyproject.toml" && exit 1)
	rm -rf $(STAGE) $(TARBALL)
	mkdir -p $(STAGE)
	cp -r src test LICENSE NOTICE README.md pyproject.toml setup.py supportinfo.conf.example $(STAGE)/
	find $(STAGE) -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find $(STAGE) -name "*.pyc" -delete 2>/dev/null || true
	find $(STAGE) -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	tar -czf $(TARBALL) $(STAGE)/
	rm -rf $(STAGE)
	@echo "Created $(TARBALL)"

clean:
	rm -rf $(STAGE) $(TARBALL) build dist *.egg-info src/*.egg-info
