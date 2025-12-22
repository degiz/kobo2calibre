.PHONY: build run debug test format

build:
	zip Kobo2Calibre.zip \
		converter.py \
		db.py \
		plugin.py \
		__init__.py \
		kobo2calibre.py \
		plugin-import-name-kobo2calibre.txt \
		images/icon.png

run:
	calibre-customize -b $(shell pwd); calibre

debug:
	calibre-customize -b $(shell pwd); calibre-debug -g

test:
	calibre-debug test/run_tests.py
	flake8 .
	rm -rf .mypy_cache && mypy . --explicit-package-bases --namespace-packages

format:
	black .
	

