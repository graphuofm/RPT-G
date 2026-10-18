/* C interface of the RPT-G transfer phase, for hosts written in C (PostgreSQL). Implemented in rptg_c.cpp
 * on top of rptg_api.h, i.e. the same Engine code as the prototype's M6.
 *
 *   rptg_graph *g = rptg_graph_build(n, m, src, dst);     forward + reverse CSR, sorted adjacency lists
 *   rptg_reduction *r = rptg_reduce(g, &pattern, init, &opts, log, sizeof log);
 *   rptg_result(r, x, &full, &count)                      reduced candidate bitmap of pattern vertex x
 *   rptg_reduction_free(r); rptg_graph_free(g);
 *
 * Bitmaps are arrays of (n + 63) / 64 uint64 words, bit v set iff vertex v is a candidate.
 * No function throws; allocation failures abort the process like any C++ bad_alloc would. */
#ifndef RPTG_C_H
#define RPTG_C_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct rptg_graph rptg_graph;
typedef struct rptg_reduction rptg_reduction;

typedef struct rptg_pattern {
    int k;                    /* pattern vertices 0..k-1 (k <= 32) */
    int nedges;               /* pattern edges: ea[i] -> eb[i] along the forward adjacency of ea[i] */
    const int *ea, *eb;
    int start;                /* host join order: start vertex ... */
    int nsteps;               /* ... then per step the bound vertex and the edge that binds the next one; */
    const int *step_bound;    /* edges that close a cycle are not steps (the engine checks them) */
    const int *step_edge;
    /* optional host join tree (nplan = 0: benefit from the left-deep order above). Node i: plan_left[i] /
     * plan_right[i] children (-1 = none); a leaf has plan_edge[i] >= 0 (a scan of that edge's table copy)
     * or plan_vertex[i] >= 0 (a scan of that vertex's table copy); plan_root = index of the root. */
    int nplan, plan_root;
    const int *plan_left, *plan_right, *plan_edge, *plan_vertex;
    const int *plan_param;    /* may be NULL: 1 = parameterized inner scan of a nested loop (no rows of its own) */
} rptg_pattern;

typedef struct rptg_options {
    double beta;              /* transfer budget factor (0 = no budget); host join work per engine unit */
    double pred_cost;         /* pre-screen: cost units per row of materializing a predicate (0 = sunk) */
    double first_cost;        /* pre-screen: fixed cost units of running a transfer phase at all */
    double filter_cost;       /* host plan mode: cost units per scanned row of a new candidate filter */
    int optimistic;           /* pre-screen: assume unknown predicate sets hold the highest-degree vertices */
} rptg_options;

rptg_graph *rptg_graph_build(uint64_t n, uint64_t m, const uint32_t *src, const uint32_t *dst);
void rptg_graph_free(rptg_graph *g);
uint64_t rptg_graph_n(const rptg_graph *g);

/* init[x] = candidate bitmap of x after its own predicates, or NULL if x has no predicate.
 * The words of init[x] are consumed (moved into the engine). log receives the decision log. */
rptg_reduction *rptg_reduce(const rptg_graph *g, const rptg_pattern *p, uint64_t **init,
                            const rptg_options *opt, char *log, int logsz);
/* pre-screen on estimated sizes (est[x] < 0 = no predicate): number of transfers that could pass the
 * budget. 0 = skip the transfer phase and the predicate scans that would feed it. */
int rptg_prescreen(const rptg_graph *g, const rptg_pattern *p, const double *est, const double *stats,
                   const rptg_options *opt, uint32_t *needed, char *log, int logsz);
/* stats (may be NULL): 5 doubles per vertex (out- and in-degree sum, sum dout^2, sum din^2, sum dout*din) of
 * predicate sets the host has materialized, Dout < 0 = unknown; see rptg_bitmap_stats */
void rptg_bitmap_stats(const rptg_graph *g, const uint64_t *words, uint64_t *count, double *stats5);
/* needed (out, may be NULL): bitmask of the predicate vertices whose information the admitted transfers
 * carry; the host evaluates only those predicates and passes the others as NULL (unconstrained) to
 * rptg_reduce, which keeps every bitmap a superset of the true candidates. */
/* Predicate column index: a sorted copy of a numeric vertex column with prefix sums of the vertices'
 * degrees and degree products. It answers the size, degree sums, and second moments of the candidate set
 * of any range or equality predicate on the column exactly, by two binary searches, and materializes the
 * set in time proportional to its size. ids[i] has value vals[i] (nrows non-null rows, any order). */
typedef struct rptg_colindex rptg_colindex;
rptg_colindex *rptg_colindex_build(const rptg_graph *g, uint64_t nrows, const uint32_t *ids, const double *vals);
/* the rows with lo < v < hi (lo_incl / hi_incl: <= instead of <; use +-INFINITY for an open side):
 * returns their number and, if stats5 != NULL, their 5 degree statistics as rptg_bitmap_stats does */
uint64_t rptg_colindex_range(const rptg_colindex *c, double lo, int lo_incl, double hi, int hi_incl, double *stats5);
/* sets the bits of those rows' vertex ids in words (which the caller has zeroed) */
void rptg_colindex_bitmap(const rptg_colindex *c, double lo, int lo_incl, double hi, int hi_incl, uint64_t *words);
void rptg_colindex_free(rptg_colindex *c);
/* trace the host-plan benefit model to stderr (also enabled by RPTG_TRACE in the environment) */
void rptg_set_trace(int on);
/* Counting join for a host (2026-10-06): a bare COUNT(*) over a tree pattern. init[x] = bitmap of x's predicate
 * set (NULL = no predicate), as for rptg_reduce. Counts when the estimated counting cost is at most host_factor
 * times the engine's own enumeration estimate; then returns 1 and the number of matches (homomorphisms, as the
 * SQL self-join counts them). Returns 0 when the host should run its own plan (call rptg_reduce as usual).
 * est_enum / est_count (may be NULL) receive the two estimates in engine work units. */
/* The counting decision from plan-time estimates, before any predicate is materialized: est[x] = estimated
 * size of x's predicate set (< 0 = none), stats as for rptg_prescreen (5 per vertex, Dout < 0 = unknown, may be
 * NULL). Returns 1 when rptg_count should run (estimated enumeration >= 20K entries and counting cost <=
 * host_factor x enumeration, or counting cost <= count_floor: the enumeration estimate can be far too low). */
int rptg_count_decide(const rptg_graph *g, const rptg_pattern *p, const double *est, const double *stats,
                      const rptg_options *opt, double host_factor, double count_floor, double *est_enum, double *est_count);
int rptg_count(const rptg_graph *g, const rptg_pattern *p, uint64_t **init, const rptg_options *opt,
               double host_factor, double count_floor, uint64_t *count, double *est_enum, double *est_count,
               char *log, int logsz);
/* words of the reduced bitmap of x; *full = 1 if x was never reduced (every vertex is a candidate) */
const uint64_t *rptg_result(const rptg_reduction *r, int x, int *full, uint64_t *count);
/* bitmask of the predicate vertices whose own candidate set the host should apply as a filter although no
 * transfer reduced it (self filters: the host applies the predicate only after scans that reach x) */
uint32_t rptg_self_filters(const rptg_reduction *r);
void rptg_reduction_free(rptg_reduction *r);

#ifdef __cplusplus
}
#endif
#endif
