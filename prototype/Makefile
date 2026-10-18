# Standalone RPT-G prototype. `make` builds bin/rptg from src/ (single translation unit).
# The versioned binaries kept in bin/ (rptg_v1 ... rptg_v5d) are documented in VERSIONS.md;
# the current source corresponds to the latest one.
CXX ?= g++
CXXFLAGS ?= -O3 -march=native -std=c++17 -Wall -Wextra -Wno-unused-parameter
all: bin/rptg
bin/rptg: src/main.cpp src/engine.h src/graph.h src/bitmap.h
	@mkdir -p bin
	$(CXX) $(CXXFLAGS) -o $@ src/main.cpp
clean:
	rm -f bin/rptg
