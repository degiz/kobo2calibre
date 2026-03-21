.PHONY: build run debug test format lint dedup dedup-kobo

build:
	rm -f Kobo2Calibre.zip
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

lint:
	ruff check .
	rm -rf .mypy_cache && mypy . --explicit-package-bases --namespace-packages

format:
	ruff format .

dedup:
	python dedup_calibre.py /Volumes/Stuff/Calibre/metadata.db --apply

dedup-kobo:
	python dedup_kobo.py /Volumes/KOBOeReader/.kobo/KoboReader.sqlite --apply

