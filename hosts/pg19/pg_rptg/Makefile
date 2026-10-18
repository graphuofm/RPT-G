# pg_rptg: RPT-G for PostgreSQL 19.  make PG_CONFIG=/path/to/pg_config && make install
MODULE_big = pg_rptg
OBJS = pg_rptg.o rptg_c.o
EXTENSION = pg_rptg
DATA = pg_rptg--1.0.sql
PROTO = ../../../prototype/src
PG_CPPFLAGS = -I$(PROTO)
SHLIB_LINK = -lstdc++
PG_CONFIG ?= ../../../ext/pg19/install/bin/pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)

rptg_c.o: $(PROTO)/rptg_c.cpp $(PROTO)/rptg_c.h $(PROTO)/rptg_api.h $(PROTO)/engine.h $(PROTO)/graph.h $(PROTO)/bitmap.h
	g++ -O3 -march=native -std=c++17 -fPIC -c -o $@ $<
