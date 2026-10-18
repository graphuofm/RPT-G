// C interface of the RPT-G transfer phase (see rptg_c.h).
#include "rptg_c.h"
#include "rptg_api.h"
#include <algorithm>
#include <cstring>

struct rptg_graph { Graph g; };
struct rptg_reduction { Engine eng; Query q; explicit rptg_reduction(const Graph& g) : eng(g, Params{}) {} };

static void set_host_plan(Engine& eng, const rptg_pattern* p) {
    eng.host_plan.clear(); eng.host_root = -1;
    for (int i = 0; i < p->nplan; i++) {
        Engine::HostNode h;
        h.left = p->plan_left[i]; h.right = p->plan_right[i]; h.edge = p->plan_edge[i]; h.vertex = p->plan_vertex[i];
        h.param = p->plan_param ? p->plan_param[i] != 0 : false;
        eng.host_plan.push_back(h);
    }
    if (p->nplan > 0) eng.host_root = p->plan_root;
}

extern "C" rptg_graph* rptg_graph_build(uint64_t n, uint64_t m, const uint32_t* src, const uint32_t* dst) {
    rptg_graph* G = new rptg_graph;
    Graph& g = G->g;
    g.n = n; g.m = m; g.directed = true;
    g.out_off.assign(n + 1, 0); g.in_off.assign(n + 1, 0);
    for (uint64_t i = 0; i < m; i++) { g.out_off[src[i] + 1]++; g.in_off[dst[i] + 1]++; }
    for (uint64_t v = 0; v < n; v++) { g.out_off[v + 1] += g.out_off[v]; g.in_off[v + 1] += g.in_off[v]; }
    g.out_nbr.resize(m); g.in_nbr.resize(m);
    std::vector<uint64_t> po(g.out_off.begin(), g.out_off.end() - 1), pi(g.in_off.begin(), g.in_off.end() - 1);
    for (uint64_t i = 0; i < m; i++) { g.out_nbr[po[src[i]]++] = dst[i]; g.in_nbr[pi[dst[i]]++] = src[i]; }
    // sorted lists: the join of cyclic patterns intersects them by binary search
    for (uint64_t v = 0; v < n; v++) {
        std::sort(g.out_nbr.begin() + g.out_off[v], g.out_nbr.begin() + g.out_off[v + 1]);
        std::sort(g.in_nbr.begin() + g.in_off[v], g.in_nbr.begin() + g.in_off[v + 1]);
    }
    g.finalize();
    return G;
}

extern "C" void rptg_graph_free(rptg_graph* g) { delete g; }
extern "C" uint64_t rptg_graph_n(const rptg_graph* g) { return g->g.n; }

extern "C" rptg_reduction* rptg_reduce(const rptg_graph* G, const rptg_pattern* p, uint64_t** init,
                                        const rptg_options* opt, char* log, int logsz) {
    rptg_reduction* r = new rptg_reduction(G->g);
    Query& q = r->q;
    q.id = 0; q.k = p->k;
    for (int i = 0; i < p->nedges; i++) q.edges.push_back({p->ea[i], p->eb[i]});
    q.preds.assign(q.k, {});
    uint64_t words = (G->g.n + 63) / 64;
    std::vector<Bitmap> B(q.k);
    for (int x = 0; x < q.k; x++) {
        if (!init[x]) continue;
        q.preds[x].push_back(Pred{0, 0.0, 0});    // marks x as a predicate vertex (root choice, budget model)
        B[x].n = G->g.n; B[x].w.assign(init[x], init[x] + words);
    }
    std::vector<std::pair<int, int>> order;
    for (int i = 0; i < p->nsteps; i++) order.push_back({p->step_bound[i], p->step_edge[i]});
    r->eng.prm.beta = opt ? opt->beta : 1.0;
    r->eng.prm.filter_cost = opt ? opt->filter_cost : 0.0;
    set_host_plan(r->eng, p);
    RunStats st = r->eng.reduce(q, B, p->start, order);
    if (log && logsz > 0) { std::strncpy(log, st.ops.c_str(), logsz - 1); log[logsz - 1] = 0; }
    return r;
}

static void count_params(Engine& eng, const rptg_options* opt) {
    // the standalone configuration of record for counting: cascade scans, degree-weighted survival, counting
    // benefit at its own unit, beta 0.25 unless the host sets one, 20K-entry guard
    eng.prm.beta = opt && opt->beta > 0 ? opt->beta : 0.25;
    eng.prm.cascade = 1; eng.prm.deg_surv = 1; eng.prm.count_benefit = 1; eng.prm.beta_count = 1.0;
    eng.prm.word_cost = 0.3; eng.prm.count_unit = 3; eng.prm.min_work = 20000;
}

extern "C" int rptg_count_decide(const rptg_graph* G, const rptg_pattern* p, const double* est, const double* stats,
                                 const rptg_options* opt, double host_factor, double count_floor, double* est_enum, double* est_count) {
    Query q; q.id = 0; q.k = p->k;
    for (int i = 0; i < p->nedges; i++) q.edges.push_back({p->ea[i], p->eb[i]});
    q.preds.assign(q.k, {});
    std::vector<double> e(q.k, -1.0);
    for (int x = 0; x < q.k; x++) if (est[x] >= 0) { e[x] = est[x]; q.preds[x].push_back(Pred{0, 0.0, 0}); }
    std::vector<std::pair<int, int>> order;
    for (int i = 0; i < p->nsteps; i++) order.push_back({p->step_bound[i], p->step_edge[i]});
    Engine eng(G->g, Params{});
    count_params(eng, opt);
    std::vector<double> st;
    if (stats) st.assign(stats, stats + 5 * p->k);
    return eng.count_decide(q, e, p->start, order, stats ? &st : nullptr, host_factor, count_floor, est_enum, est_count) ? 1 : 0;
}

extern "C" int rptg_count(const rptg_graph* G, const rptg_pattern* p, uint64_t** init, const rptg_options* opt,
                          double host_factor, double count_floor, uint64_t* count, double* est_enum, double* est_count,
                          char* log, int logsz) {
    rptg_reduction r(G->g);
    Query& q = r.q;
    q.id = 0; q.k = p->k;
    for (int i = 0; i < p->nedges; i++) q.edges.push_back({p->ea[i], p->eb[i]});
    q.preds.assign(q.k, {});
    uint64_t words = (G->g.n + 63) / 64;
    std::vector<Bitmap> B(q.k);
    for (int x = 0; x < q.k; x++) {
        if (!init[x]) continue;
        q.preds[x].push_back(Pred{0, 0.0, 0});
        B[x].n = G->g.n; B[x].w.assign(init[x], init[x] + words);
    }
    std::vector<std::pair<int, int>> order;
    for (int i = 0; i < p->nsteps; i++) order.push_back({p->step_bound[i], p->step_edge[i]});
    Engine& eng = r.eng;
    count_params(eng, opt);
    int did = eng.count_host(q, B, p->start, order, host_factor, count_floor, count, est_enum, est_count);
    if (log && logsz > 0) { std::strncpy(log, eng.st.ops.c_str(), logsz - 1); log[logsz - 1] = 0; }
    return did;
}

extern "C" void rptg_bitmap_stats(const rptg_graph* G, const uint64_t* words, uint64_t* count, double* st) {
    const Graph& g = G->g;
    uint64_t c = 0; double D0 = 0, D1 = 0, M0 = 0, M1 = 0, M2 = 0;
    uint64_t W = (g.n + 63) / 64;
    for (uint64_t wi = 0; wi < W; wi++) {
        uint64_t w = words[wi];
        while (w) {
            uint64_t v = wi * 64 + __builtin_ctzll(w); w &= w - 1;
            if (v >= g.n) break;
            double o = g.dout[v], i = g.din[v];
            c++; D0 += o; D1 += i; M0 += o * o; M1 += i * i; M2 += o * i;
        }
    }
    if (count) *count = c;
    st[0] = D0; st[1] = D1; st[2] = M0; st[3] = M1; st[4] = M2;
}

extern "C" int rptg_prescreen(const rptg_graph* G, const rptg_pattern* p, const double* est, const double* stats,
                              const rptg_options* opt, uint32_t* needed, char* log, int logsz) {
    Query q; q.id = 0; q.k = p->k;
    for (int i = 0; i < p->nedges; i++) q.edges.push_back({p->ea[i], p->eb[i]});
    q.preds.assign(q.k, {});
    std::vector<double> e(q.k, -1.0);
    for (int x = 0; x < q.k; x++) if (est[x] >= 0) { e[x] = est[x]; q.preds[x].push_back(Pred{0, 0.0, 0}); }
    std::vector<std::pair<int, int>> order;
    for (int i = 0; i < p->nsteps; i++) order.push_back({p->step_bound[i], p->step_edge[i]});
    Engine eng(G->g, Params{});
    eng.prm.beta = opt ? opt->beta : 1.0;
    eng.prm.pred_cost = opt ? opt->pred_cost : 0.0;
    eng.prm.first_cost = opt ? opt->first_cost : 0.0;
    eng.prm.filter_cost = opt ? opt->filter_cost : 0.0;
    eng.prm.optimistic = opt ? opt->optimistic != 0 : false;
    set_host_plan(eng, p);
    std::vector<double> st;
    if (stats) st.assign(stats, stats + 5 * p->k);
    int n = eng.prescreen(q, e, p->start, order, stats ? &st : nullptr);
    if (needed) *needed = eng.dry_needed;
    if (log && logsz > 0) { std::strncpy(log, eng.st.ops.c_str(), logsz - 1); log[logsz - 1] = 0; }
    return n;
}

extern "C" const uint64_t* rptg_result(const rptg_reduction* r, int x, int* full, uint64_t* count) {
    const VarState& s = r->eng.S[x];
    if (full) *full = s.full ? 1 : 0;
    if (count) *count = s.cnt;
    return s.B.w.data();
}

extern "C" void rptg_reduction_free(rptg_reduction* r) { delete r; }

// ---- predicate column index -------------------------------------------------------------------------
struct rptg_colindex {
    std::vector<double> val;       // sorted values
    std::vector<uint32_t> id;      // vertex of each sorted position
    std::vector<double> pre;       // 5 prefix sums per position (dout, din, dout^2, din^2, dout*din), (n+1)*5
};

extern "C" rptg_colindex* rptg_colindex_build(const rptg_graph* G, uint64_t nrows, const uint32_t* ids, const double* vals) {
    const Graph& g = G->g;
    std::vector<uint64_t> ord(nrows);
    for (uint64_t i = 0; i < nrows; i++) ord[i] = i;
    std::sort(ord.begin(), ord.end(), [&](uint64_t a, uint64_t b) { return vals[a] < vals[b]; });
    rptg_colindex* c = new rptg_colindex();
    c->val.resize(nrows); c->id.resize(nrows); c->pre.assign((nrows + 1) * 5, 0.0);
    for (uint64_t i = 0; i < nrows; i++) {
        uint32_t v = ids[ord[i]];
        c->val[i] = vals[ord[i]]; c->id[i] = v;
        double o = v < g.n ? g.dout[v] : 0, in = v < g.n ? g.din[v] : 0;
        const double add[5] = {o, in, o * o, in * in, o * in};
        for (int j = 0; j < 5; j++) c->pre[(i + 1) * 5 + j] = c->pre[i * 5 + j] + add[j];
    }
    return c;
}

static void colindex_bounds(const rptg_colindex* c, double lo, int lo_incl, double hi, int hi_incl, uint64_t* b, uint64_t* e) {
    auto& v = c->val;
    *b = (lo_incl ? std::lower_bound(v.begin(), v.end(), lo) : std::upper_bound(v.begin(), v.end(), lo)) - v.begin();
    *e = (hi_incl ? std::upper_bound(v.begin(), v.end(), hi) : std::lower_bound(v.begin(), v.end(), hi)) - v.begin();
    if (*e < *b) *e = *b;
}

extern "C" uint64_t rptg_colindex_range(const rptg_colindex* c, double lo, int lo_incl, double hi, int hi_incl, double* st) {
    uint64_t b, e;
    colindex_bounds(c, lo, lo_incl, hi, hi_incl, &b, &e);
    if (st) for (int j = 0; j < 5; j++) st[j] = c->pre[e * 5 + j] - c->pre[b * 5 + j];
    return e - b;
}

extern "C" void rptg_colindex_bitmap(const rptg_colindex* c, double lo, int lo_incl, double hi, int hi_incl, uint64_t* w) {
    uint64_t b, e;
    colindex_bounds(c, lo, lo_incl, hi, hi_incl, &b, &e);
    for (uint64_t i = b; i < e; i++) w[c->id[i] >> 6] |= 1ull << (c->id[i] & 63);
}

extern "C" void rptg_colindex_free(rptg_colindex* c) { delete c; }

extern "C" void rptg_set_trace(int on) { rptg_trace_flag() = on; }

extern "C" uint32_t rptg_self_filters(const rptg_reduction* r) { return r->eng.self_filters; }
