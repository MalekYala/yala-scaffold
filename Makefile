.PHONY: test test-full

test:
	./tests/scaffold_matrix.sh --quick

test-full:
	./tests/scaffold_matrix.sh --full
