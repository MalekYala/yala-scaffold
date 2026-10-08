.PHONY: test test-full

test:
	python3 tests/check_ai_notes.py
	python3 tests/check_ci_yaml.py
	./tests/scaffold_matrix.sh --quick

test-full:
	python3 tests/check_ai_notes.py
	python3 tests/check_ci_yaml.py
	./tests/scaffold_matrix.sh --full
