// RPT-G prototype engine: tree-pattern queries over a single edge table (CSR/CSC),
// candidate bitmaps per pattern vertex, and four execution methods sharing one join phase:
//   M0  NoTransfer        : join only, host-like default order
//   M3  Static-SemiMask   : one-hop static push from every predicate vertex (Kuzu-style semi-mask)
//   M4  Yannakakis-Bitmap : naive two-pass full reduction over a spanning tree, always PUSH
//   M5  Arc consistency   : PUSH along every pattern edge in both directions until no candidate set
//                           changes (the candidate filtering of subgraph-matching algorithms)
//   M6  RPT-G             : Algorithm 1' (plan) + Algorithm 2' (push/pull/skip/abort, exact costs)
// Cyclic patterns: the join binds one new vertex per step through a tree edge and checks every other
// (closing) edge to already bound vertices by intersecting sorted adjacency lists, iterating the shortest
// one (worst-case-optimal style). Transfers use a spanning tree plus the closing edges.
#pragma once
#include "bitmap.h"
#include "graph.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdlib>
#include <cstdio>
#include <cmath>
#include <functional>
#include <sstream>
// host-plan model trace to stderr (RPTG_TRACE in the environment, or rptg_set_trace from a host)
inline int& rptg_trace_flag() { static int f = std::getenv("RPTG_TRACE") != nullptr; return f; }
inline bool rptg_trace_on() { return rptg_trace_flag() != 0; }
#include <string>
#include <vector>

struct Pred { int type; double val; int lab; };  // val is double: compare like the hosts do (FLOAT column vs DOUBLE literal)          // 0: pu < val, 1: pd < val, 2: label == lab
struct PEdge { int a, b; };                              // pattern edge a -> b (out-adjacency of a)
struct Query {
    int id = 0, k = 0;
    std::vector<PEdge> edges;
    std::vector<std::vector<Pred>> preds;
    std::string text;
};

struct Params {
    double tau_dense = 0.8, tau_bound = 0.5, tau_sel = 0.35, tau_prog = 0.6;
    uint64_t gamma = 2000;
    uint64_t seed = 1;
    // Ablation M6-acc: estimate the degree sums from a sample instead of the exact accumulators.
    // est_sample = 0 -> exact; est_mode 0 = random word order, 1 = sequential (streaming-like, biased)
    uint64_t est_sample = 0; int est_mode = 0;
    // survival estimate from degree sums (sum deg(B_x)/|E|) instead of set sizes (|B_x|/|V|)
    bool surv_deg = true;
    // Transfer budget: a transfer is admitted only if its exact cost <= beta * estimated join work
    // it could eliminate (accumulator-based estimate along the host join order). 0 disables.
    double beta = 1.0;
    // Join-phase options: count_shortcut = O(1) count at a probe-free last level (a real engine
    // must still produce the tuples; disable for join-order experiments). edge_scan = materialize
    // filtered adjacency (BitmapEdgeScan) for steps whose source vertices are visited more than
    // scan_beta times on average (estimated); applies to methods with a transfer phase.
    bool count_shortcut = true; bool edge_scan = true; double scan_beta = 1.0;
    bool col_index = false;          // v10: predicates from sorted column indexes (all methods)
    double count_far = 8.0;          // v10 counting switch: estimated enumeration > count_far * C -> count at once,
                                     // < C / count_far -> enumerate with a budget of count_patience * C, else C
    double count_patience = 4.0;
    double min_work = 0.0;           // v10: skip the transfer phase when the estimated join work is below this
    double word_cost = 0.0;          // v11: budget cost per bitmap word of a transfer (allocation and scans)
    bool extrapolate = false;        // v13: online edge scans only when the extrapolated rest of the level pays
    double count_unit = 3.0;         // v15: cost of a counting entry (random rank lookup) in enumeration entries
    // v16 (RPT+ cascade filter, graph form): membership tests of a sorted adjacency list against a candidate
    // bitmap clamp the list to [lo, hi] and jump over runs that fall into empty 64-vertex words
    bool cascade = false; double sparse_frac = 0.25;
    double skip_unit = 24.0;         // cost of one jump (summary lookup + galloping search) in adjacency entries (~100 ns measured)
    // v17 (RPT+ dynamic pipeline, graph form): (a) a push visits its sources in random order and is abandoned
    // when, after gamma sources, the extrapolated survival of the target exceeds tau_sel before tau_prog of the
    // sources; (b) before an expensive transfer into a vertex that the join reaches from another edge, a pilot
    // measures the survival among the vertices the join actually reaches (gamma samples drawn through the
    // join's own edge from the frontier set), and the budget is rescaled from the modelled to the measured one
    bool push_abort = false, reach_pilot = false;
    double pilot_min = 16000.0;      // transfers cheaper than this run without a reach pilot
    int sibling_order = 0;           // v17: 0 = cheapest transfer first, 1 = most selective (smallest survival) first
    bool upfront_count = false;      // v17 (M8): decide between counting and enumerating before the transfer phase
    // v19: value a transfer by the share of the target's degree sum that it removes, not of its vertices: a vertex
    // of degree d survives a transfer from a set that covers a share rho of the edge endpoints with probability
    // 1 - (1 - rho)^d, so hubs survive and keep their edges, which the join reaches in proportion to degree
    bool deg_surv = false;
    // v20: for a query that may be counted (M7/M8 on a tree pattern), a transfer is also valued by the reduction
    // of the counting cost C that it brings (|B_y| and the degree sums enter C directly); the benefit is the
    // larger of the enumeration benefit and the counting benefit, because either path may be taken
    bool count_benefit = false;
    // v25: beta < 0 = online calibration: beta = (measured join ns per scanned entry) / (measured transfer ns per
    // entry) over the queries run so far in this process, clamped to [0.1, 2]; beta_count scales the counting benefit
    // (a counting entry costs about a transfer entry, so 1)
    double beta_count = 1.0; double beta_default = 0.5;
    // Online filtered adjacency (ski rental): a probing join step whose scanned adjacency entries reach the
    // cost of building its filtered adjacency (one push over the bound vertex's candidates) builds it on
    // the spot, whatever the plan-time estimate said. At most twice the better of the two choices.
    bool adaptive_scan = true;
    // selectivity per predicate assumed by the host-estimate join order (--order est)
    double est_sel = 0.1;
    // Hosts whose plans evaluate a predicate only on the vertices the join reaches (index lookups, e.g.
    // PostgreSQL) pay for materializing a predicate set; cost units per candidate row, charged in the
    // pre-screen when a transfer first reads that predicate. 0 = predicate scans are sunk costs.
    double pred_cost = 0.0;
    // fixed cost of running any transfer phase at all in the host (side queries, pipeline setup), charged
    // in the pre-screen to the first transfer that would be admitted
    double first_cost = 0.0;
    // host plan mode: cost units per row of evaluating a new candidate filter on a scan; charged to the
    // first transfer that reduces a vertex, for every scan of the plan that reads that vertex
    double filter_cost = 0.0;
    // pre-screen with the largest degree sums and moments a set of the estimated size can have (an upper
    // bound on every benefit): a query that fails even this needs no predicate evaluation at all
    bool optimistic = false;
};

struct Timeout {};

struct VarState {
    Bitmap B;
    uint64_t cnt = 0;
    uint64_t D[2] = {0, 0};   // degree accumulators: sum of out/in degrees over B
    double M[3] = {0, 0, 0};  // degree moments over B: sum dout^2, sum din^2, sum dout*din (host plan model)
    double H[2][32] = {};     // v19: degree sum of B per log2 degree bin and direction (degree-weighted survival)
    uint32_t sources = 0;     // bitset of pattern vertices whose predicate information reached here
    bool full = true;         // B is all-ones (no predicate, untouched)
    int reduced_via = -1;     // -1: untouched; >=0: only reduced through this pattern edge; -2: predicate/multiple sources
};

struct Chk { int z, dir, edge; };                        // closing edge: new vertex must lie in adj(bind[z], dir)
struct Step { int bound, nv, dir, edge; std::vector<Chk> checks; };

struct RunStats {
    double transfer_ms = 0, join_ms = 0, total_ms = 0, init_ms = 0;
    uint64_t count = 0, transfer_work = 0, join_work = 0;
    uint64_t join_out = 0;    // v18: entries counted by the last-level shortcut (output), not scanned
    int n_push = 0, n_pull = 0, n_skip = 0, n_abort = 0;
    bool timeout = false;
    std::string ops;
};

class Engine {
public:
    const Graph& g;
    Params prm;
    Engine(const Graph& g_, Params p) : g(g_), prm(p) {}

    // ---- join-phase switch (M7, C0): enumeration aborts once its work exceeds the cost of counting ------
    struct SwitchToCount {};
    bool tiny = false;               // v10: the query's estimated join is too small to decide about
    bool counting_query = false;     // v20: set by run() when the join may count instead of enumerating
    bool count_only = false;         // v26: set by run() when the join will count (M8 upfront): a transfer's benefit is
                                     // its reduction of the counting cost alone, never an enumeration it would have saved
    double cal_join_ms = 0, cal_join_work = 0, cal_tr_ms = 0, cal_tr_work = 0;   // v25: unit-cost calibration
    double beta_eff() const {
        if (prm.beta >= 0) return prm.beta;
        if (cal_tr_work < 1e6 || cal_join_work < 1e7) return prm.beta_default;
        double b = (cal_join_ms / cal_join_work) / (cal_tr_ms / cal_tr_work);
        return std::min(2.0, std::max(0.1, b));
    }
    uint64_t enum_cost = 0, enum_budget = UINT64_MAX;
    // ---- deadline handling -------------------------------------------------
    std::chrono::steady_clock::time_point deadline;
    uint64_t work_ctr = 0;
    inline void tick(uint64_t w = 1) {
        work_ctr += w;
        if ((work_ctr & 0xFFFF) < w) if (std::chrono::steady_clock::now() > deadline) throw Timeout{};
    }

    // ---- cascade scans (v16) ---------------------------------------------------------------------------
    // Visit the members of B among the sorted adjacency list [b, en); returns the entries visited (tests and
    // jumps), the unit of transfer_work / join_work. With a summary, the list is clamped to [lo, hi] and a
    // neighbour in an empty word jumps (galloping search) to the first neighbour of the next non-empty word.
    template <class F> inline uint64_t scan_in(const Bitmap& B, const uint32_t* b, const uint32_t* en, F&& f) const {
        if (!B.use_skip) { uint64_t w = en - b; for (; b < en; ++b) if (B.test(*b)) f(*b); return w; }
        b = std::lower_bound(b, en, (uint32_t)B.lo); en = std::upper_bound(b, en, (uint32_t)B.hi);
        uint64_t work = 0;
        while (b < en) {
            uint32_t u = *b; uint64_t wi = u >> 6, word = B.w[wi];
            if (word) { work++; if ((word >> (u & 63)) & 1ULL) f(u); ++b; continue; }
            uint64_t nw = B.next_word(wi + 1);
            if (nw == Bitmap::NONE) break;
            uint32_t target = (uint32_t)(nw << 6);
            const uint32_t* p = b + 1; size_t step = 1;                       // gallop, then binary search
            while (p < en && *p < target) { b = p; p += step; step <<= 1; }
            b = std::lower_bound(b, p < en ? p : en, target);
            work += (uint64_t)prm.skip_unit;
        }
        return work;
    }
    // does the sorted list [b, en) contain a member of B? (early exit)
    inline bool any_in(const Bitmap& B, const uint32_t* b, const uint32_t* en, uint64_t& work) const {
        if (!B.use_skip) { for (; b < en; ++b) { work++; if (B.test(*b)) return true; } return false; }
        bool hit = false;
        b = std::lower_bound(b, en, (uint32_t)B.lo); en = std::upper_bound(b, en, (uint32_t)B.hi);
        while (b < en && !hit) {
            uint32_t u = *b; uint64_t wi = u >> 6, word = B.w[wi];
            if (word) { work++; if ((word >> (u & 63)) & 1ULL) hit = true; ++b; continue; }
            uint64_t nw = B.next_word(wi + 1);
            if (nw == Bitmap::NONE) break;
            uint32_t target = (uint32_t)(nw << 6);
            const uint32_t* p = b + 1; size_t step = 1;
            while (p < en && *p < target) { b = p; p += step; step <<= 1; }
            b = std::lower_bound(b, p < en ? p : en, target);
            work += (uint64_t)prm.skip_unit;
        }
        return hit;
    }
    // prepare B as the target of membership tests (summary + range) if the expected scan work pays for the
    // pass over the words (ski rental); a full bitmap, or a set that is not sparse, never skips
    inline void prep_target(VarState& s, double expected_work) {
        if (!prm.cascade || s.full || s.B.sum_ok) return;
        if (expected_work < (double)s.B.words()) return;
        if ((double)s.cnt >= prm.sparse_frac * (double)s.B.words()) return;   // cannot be sparse enough to skip
        s.B.build_summary(prm.sparse_frac); tick(s.B.words() + 1);
    }
    // effective cost of scanning D adjacency entries of |src| vertices against target t with cascade skipping
    // (without a summary, |t| bounds the number of non-empty words)
    inline double eff_cost(uint64_t D, uint64_t src_cnt, const VarState& t) const {
        if (!prm.cascade || t.full) return (double)D;
        double nz = t.B.sum_ok ? (double)t.B.nz_words : std::min((double)t.cnt, (double)t.B.words());
        if (t.B.sum_ok && !t.B.use_skip) return (double)D;
        if (!t.B.sum_ok && nz >= prm.sparse_frac * (double)t.B.words()) return (double)D;
        return std::min((double)D, (double)src_cnt * (prm.skip_unit * nz + 1.0) + (double)t.B.words());
    }

    // ---- per-query state ----------------------------------------------------
    const Query* q = nullptr;
    std::vector<VarState> S;
    RunStats st;

    static int dir_from(const PEdge& e, int x) { return x == e.a ? 0 : 1; }
    static int other(const PEdge& e, int x) { return x == e.a ? e.b : e.a; }

    void init_states() {
        S.assign(q->k, VarState());
        for (int x = 0; x < q->k; x++) {
            VarState& s = S[x];
            if (q->preds[x].empty()) {
                s.B.init(g.n, true); s.cnt = g.n; s.D[0] = s.D[1] = g.m; s.full = true; s.sources = 0;
                for (int j = 0; j < 3; j++) s.M[j] = g.M[j];
                for (int d = 0; d < 2; d++) for (int b = 0; b < 32; b++) s.H[d][b] = g.hist_deg[d][b];
                continue;
            }
            s.B.init(g.n, false); s.full = false; s.sources = 1u << x; s.reduced_via = -2;
            if (prm.col_index && q->preds[x].size() == 1) {      // v10: a run of the sorted column, no scan
                const Pred& p = q->preds[x][0];
                const Graph::ColIdx& ix = p.type == 0 ? g.ix_pu : p.type == 1 ? g.ix_pd : g.ix_label;
                if (!ix.id.empty()) {
                    uint64_t b = 0, e;
                    if (p.type == 2) {
                        b = std::lower_bound(ix.val.begin(), ix.val.end(), (double)p.lab) - ix.val.begin();
                        e = std::upper_bound(ix.val.begin(), ix.val.end(), (double)p.lab) - ix.val.begin();
                    } else {
                        e = std::lower_bound(ix.val.begin(), ix.val.end(), p.val) - ix.val.begin();   // val < s
                    }
                    for (uint64_t i = b; i < e; i++) s.B.set(ix.id[i]);
                    s.cnt = e - b;
                    // v24: degree histogram without touching the degree arrays in value order (random access):
                    // a uniform or label predicate is independent of degree, so the global histogram scaled by
                    // |B|/n; a pd predicate selects the top-|B| vertices by degree, whose degrees are a prefix of
                    // the sorted degree arrays (read sequentially)
                    if (p.type == 1) {
                        for (int d = 0; d < 2; d++) {
                            for (int j = 0; j < 32; j++) s.H[d][j] = 0;
                            for (uint64_t i = 0; i < s.cnt && i < g.n; i++) { uint32_t dg = g.sdeg[d][i]; s.H[d][Graph::deg_bin(dg)] += dg; }
                        }
                    } else {
                        double f = g.n ? (double)s.cnt / (double)g.n : 0.0;
                        for (int d = 0; d < 2; d++) for (int j = 0; j < 32; j++) s.H[d][j] = g.hist_deg[d][j] * f;
                    }
                    s.D[0] = (uint64_t)(ix.pre[e * 5] - ix.pre[b * 5]); s.D[1] = (uint64_t)(ix.pre[e * 5 + 1] - ix.pre[b * 5 + 1]);
                    for (int j = 0; j < 3; j++) s.M[j] = ix.pre[e * 5 + 2 + j] - ix.pre[b * 5 + 2 + j];
                    continue;
                }
            }
            for (uint64_t v = 0; v < g.n; v++) {
                bool ok = true;
                for (const Pred& p : q->preds[x]) {
                    if (p.type == 0) ok = (double)g.pu[v] < p.val;
                    else if (p.type == 1) ok = (double)g.pd[v] < p.val;
                    else ok = g.label[v] == p.lab;
                    if (!ok) break;
                }
                if (ok) { s.B.set(v); s.cnt++; s.D[0] += g.dout[v]; s.D[1] += g.din[v];
                          double o = g.dout[v], i = g.din[v]; s.M[0] += o * o; s.M[1] += i * i; s.M[2] += o * i;
                          s.H[0][Graph::deg_bin(g.dout[v])] += o; s.H[1][Graph::deg_bin(g.din[v])] += i; }
            }
        }
    }

    // A pattern edge is a bridge if removing it disconnects the pattern. The provenance rule (Lemma P5)
    // is sound only for transfers along bridges: across a cycle, the same sources can reach a vertex by
    // two paths that constrain it differently.
    std::vector<bool> is_bridge;
    void compute_bridges() {
        int E = (int)q->edges.size();
        is_bridge.assign(E, false);
        for (int skip = 0; skip < E; skip++) {
            std::vector<int> comp(q->k, -1); std::vector<int> st{0}; comp[0] = 0; int seen = 1;
            while (!st.empty()) {
                int x = st.back(); st.pop_back();
                for (int ei = 0; ei < E; ei++) {
                    if (ei == skip) continue;
                    const PEdge& e = q->edges[ei];
                    int y = e.a == x ? e.b : e.b == x ? e.a : -1;
                    if (y >= 0 && comp[y] < 0) { comp[y] = 0; seen++; st.push_back(y); }
                }
            }
            is_bridge[skip] = seen < q->k;
        }
    }

    // ---- transfer primitives ------------------------------------------------
    // PUSH x -> y over edge e: B_y <- B_y ∩ N(B_x). Cost = D[x][dir].
    int edge_index(const PEdge& e) const { return int(&e - &q->edges[0]); }
    // Exact degree accumulators by one in-order pass over the bitmap (monotone access into dout/din).
    void recompute_D(VarState& s) {
        uint64_t D0 = 0, D1 = 0; double M0 = 0, M1 = 0, M2 = 0;
        for (int d = 0; d < 2; d++) for (int b_ = 0; b_ < 32; b_++) s.H[d][b_] = 0;
        s.B.for_each([&](uint64_t v) { uint32_t o = g.dout[v], i = g.din[v]; D0 += o; D1 += i;
                                       M0 += double(o) * o; M1 += double(i) * i; M2 += double(o) * i;
                                       s.H[0][Graph::deg_bin(o)] += o; s.H[1][Graph::deg_bin(i)] += i; });
        s.D[0] = D0; s.D[1] = D1; s.M[0] = M0; s.M[1] = M1; s.M[2] = M2;
        tick(s.B.words());
    }
    void mark_reduced(VarState& sy, const PEdge& e) {
        int ei = edge_index(e);
        sy.reduced_via = sy.full ? ei : (sy.reduced_via == ei ? ei : -2);
        sy.full = false;
    }
    // returns false if the push was abandoned (v17): B_y is then unchanged
    bool push(int x, int y, const PEdge& e, bool abort_check = false) {
        int dir = dir_from(e, x);
        VarState& sx = S[x]; VarState& sy = S[y];
        auto tp0 = std::chrono::steady_clock::now();
        Bitmap Bn(g.n, false);
        uint64_t work = 0, cnt = 0;
        prep_target(sy, (double)sx.D[dir]);
        auto tp1 = std::chrono::steady_clock::now();
        uint64_t seen = 0, total = sx.cnt; bool aborted = false;
        // v21: only the bit is set here; the size and degree statistics are taken afterwards by one ordered
        // pass over the new bitmap (recompute_D). Reading dout/din per newly marked vertex, in the random order
        // in which the adjacency lists produce them, cost ~70 ns per entry on LiveJournal (cache misses in the
        // 19 MB degree arrays) against ~4 ns for the ordered pass.
        auto visit = [&](uint64_t v) {
            const uint32_t* b = g.adj_begin(v, dir); const uint32_t* en = g.adj_end(v, dir);
            work += scan_in(sy.B, b, en, [&](uint32_t u) { if (!Bn.test(u)) { Bn.set(u); cnt++; } });
            tick(en - b + 1);
        };
        if (abort_check && prm.push_abort && total > prm.gamma) {
            WordPerm perm(sx.B.words(), prm.seed + (uint64_t)q->id * 137 + x * 11 + y * 3);
            perm.for_each([&](uint64_t wi) {
                uint64_t word = sx.B.w[wi];
                if (!word) return true;
                Bitmap::for_each_in_word(word, wi * 64, [&](uint64_t v) { seen++; visit(v); });
                double p = (double)seen / (double)total;
                if (seen >= prm.gamma && p < prm.tau_prog) {
                    double est_final = std::min((double)sy.cnt, (double)cnt / p);   // sources mark disjoint sets at most
                    if (est_final > prm.tau_sel * (double)sy.cnt) { aborted = true; return false; }
                }
                return true;
            });
        } else {
            sx.B.for_each(visit);
        }
        st.transfer_work += work;
        if (aborted) { st.n_abort++; return false; }
        auto tp2 = std::chrono::steady_clock::now();
        mark_reduced(sy, e);
        sy.B.w.swap(Bn.w); sy.B.invalidate(); sy.cnt = cnt;
        recompute_D(sy);
        auto tp3 = std::chrono::steady_clock::now();
        if (rptg_trace_on()) {
            auto us = [](std::chrono::steady_clock::time_point a, std::chrono::steady_clock::time_point b) { return std::chrono::duration<double, std::micro>(b - a).count(); };
            fprintf(stderr, "[push-trace] %d>%d |Bx|=%lu D=%lu -> %lu : alloc+prep %.0f us, scan %.0f us (%lu entries), stats %.0f us\n",
                    x, y, (unsigned long)sx.cnt, (unsigned long)sx.D[dir], (unsigned long)cnt, us(tp0, tp1), us(tp1, tp2), (unsigned long)work, us(tp2, tp3));
        }
        sy.sources |= sx.sources;
        st.n_push++;
        return true;
    }

    // v17: survival of B_y under the transfer x -> y (edge e) among the vertices that the join reaches: samples
    // drawn from the frontier set of the step that enters y, through that step's edge; -1 if not applicable
    std::vector<int> enter_idx;      // step index that enters each vertex (-1: start / unknown)
    double reach_pilot(int x, int y, const PEdge& e) {
        if (host_root >= 0 || enter_idx.empty() || enter_idx[y] < 0) return -1.0;
        const Step& s_ = steps[enter_idx[y]];
        if (s_.edge == edge_index(e)) return -1.0;                 // the join performs this transfer itself
        const VarState& sf = S[s_.bound]; const VarState& sy = S[y]; const VarState& sx = S[x];
        int rdir = dir_from(e, y);
        uint64_t seen = 0, alive_n = 0, work = 0, srcs = 0;
        prep_target(const_cast<VarState&>(sx), (double)sy.D[rdir]);
        WordPerm perm(sf.B.words(), prm.seed + (uint64_t)q->id * 139 + x * 13 + y * 5);
        perm.for_each([&](uint64_t wi) {
            uint64_t word = sf.B.w[wi];
            if (!word) return true;
            Bitmap::for_each_in_word(word, wi * 64, [&](uint64_t v) {
                srcs++;
                const uint32_t* b = g.adj_begin(v, s_.dir); const uint32_t* en = g.adj_end(v, s_.dir);
                int taken = 0;
                for (const uint32_t* p = b; p < en && taken < 32; ++p) {
                    work++;
                    if (!sy.B.test(*p)) continue;
                    taken++; seen++;
                    uint64_t dr;
                    if (alive(*p, rdir, sx.B, work, dr)) alive_n++;
                }
            });
            tick(64);
            return seen < prm.gamma && srcs < 4 * prm.gamma;
        });
        st.transfer_work += work;
        return seen ? (double)alive_n / (double)seen : -1.0;
    }

    // Alive test for PULL: does v (on side y) have a neighbour in B_x via edge e?
    inline bool alive(uint64_t v, int rdir, const Bitmap& Bx, uint64_t& work, uint64_t& deg_r) {
        const uint32_t* b = g.adj_begin(v, rdir); const uint32_t* en = g.adj_end(v, rdir);
        deg_r = en - b;
        return any_in(Bx, b, en, work);
    }

    // PULL x -> y over edge e: for v in B_y (random word order) keep v iff it has a neighbour in B_x.
    // Clears are final (Lemma P6). With abort_check, applies the Algorithm 2' abort rule and
    // returns false if aborted. max_seen > 0 limits the scan (pilot mode).
    // Returns true if the whole of B_y was examined.
    bool pull(int x, int y, const PEdge& e, bool abort_check, uint64_t max_seen, double* lambda_out) {
        int rdir = dir_from(e, y);
        VarState& sx = S[x]; VarState& sy = S[y];
        mark_reduced(sy, e);
        uint64_t seen = 0, alive_n = 0, work = 0, total = sy.cnt;
        bool aborted = false, complete = true;
        prep_target(sx, (double)sy.D[rdir]); sy.B.invalidate();
        WordPerm perm(sy.B.words(), prm.seed + (uint64_t)q->id * 131 + x * 7 + y);
        perm.for_each([&](uint64_t wi) {
            uint64_t word = sy.B.w[wi];
            if (!word) return true;
            Bitmap::for_each_in_word(word, wi * 64, [&](uint64_t v) {
                seen++;
                uint64_t deg_r;
                if (alive(v, rdir, sx.B, work, deg_r)) alive_n++;
                else { sy.B.clear(v); sy.cnt--; sy.D[rdir] -= deg_r; sy.D[1 - rdir] -= (rdir == 0 ? g.din[v] : g.dout[v]);
                       double o = g.dout[v], i = g.din[v]; sy.M[0] -= o * o; sy.M[1] -= i * i; sy.M[2] -= o * i;
                       sy.H[0][Graph::deg_bin(g.dout[v])] -= o; sy.H[1][Graph::deg_bin(g.din[v])] -= i; }
            });
            tick(64);
            if (abort_check && seen >= prm.gamma && (double)alive_n / seen > prm.tau_sel &&
                (double)seen / total < prm.tau_prog) { aborted = true; complete = false; return false; }
            if (max_seen && seen >= max_seen && seen < total) { complete = false; return false; }
            return true;
        });
        st.transfer_work += work;
        if (lambda_out) *lambda_out = seen ? (double)alive_n / seen : 0.0;
        if (complete) { sy.sources |= sx.sources; st.n_pull++; }
        if (aborted) st.n_abort++;
        return complete;
    }

    std::chrono::steady_clock::time_point op_t0;
    void op_begin() { op_t0 = std::chrono::steady_clock::now(); }
    void log_op(const char* op, int x, int y, uint64_t before, uint64_t after, const char* extra = "") {
        double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - op_t0).count();
        std::ostringstream o; o << x << ">" << y << ":" << op << "(" << before << "->" << after << ")" << extra << "@" << (long)us << "us|";
        st.ops += o.str();
    }

    // Sampled estimate of D[x][dir] (ablation): |B_x| * mean degree over est_sample sampled members.
    uint64_t estimate_D(const VarState& sx, int dir, uint64_t salt) {
        if (sx.cnt == 0) return 0;
        uint64_t seen = 0, sum = 0;
        auto visit_word = [&](uint64_t wi) {
            uint64_t word = sx.B.w[wi];
            if (word) Bitmap::for_each_in_word(word, wi * 64, [&](uint64_t v) { seen++; sum += g.deg(v, dir); });
            tick(64);
            return seen < prm.est_sample;
        };
        if (prm.est_mode == 0) { WordPerm perm(sx.B.words(), prm.seed + salt); perm.for_each(visit_word); }
        else for (uint64_t wi = 0; wi < sx.B.words(); wi++) if (!visit_word(wi)) break;
        if (seen >= sx.cnt) return sum;                  // whole set visited: exact
        return (uint64_t)((double)sum / seen * sx.cnt);
    }

    // Algorithm 2': dynamic decision for transfer(x -> y)
    void transfer_dynamic(int x, int y, const PEdge& e, double budget = -1.0) {
        VarState& sx = S[x]; VarState& sy = S[y];
        uint64_t before = sy.cnt; op_begin();
        if (x == y) {   // host plan: x's own candidate set as a filter on the scans below x's vertex join
            double extra = (dry_run && n_admitted == 0 ? prm.first_cost : 0.0) +
                           prm.filter_cost * (cur_scan_rows >= 0 ? cur_scan_rows : host_scan_rows(y));
            if (dry_run && prm.pred_cost > 0 && !((dry_materialized >> x) & 1)) extra += prm.pred_cost * dry_pred_size[x];
            if (budget >= 0 && extra > budget) {
                st.n_skip++; std::ostringstream ex; ex << "[c=" << (long)extra << ";b=" << (long)budget << "]";
                log_op("SKIP-budget", x, y, before, before, ex.str().c_str()); return;
            }
            filtered_mask |= 1u << x; self_filters |= 1u << x;
            if (dry_run) { n_admitted++; dry_needed |= 1u << x; dry_materialized |= 1u << x; }
            log_op("FILTER", x, y, before, before); return;
        }
        if (is_bridge[edge_index(e)] && (sx.sources & ~sy.sources) == 0) { st.n_skip++; log_op("SKIP-src", x, y, before, before); return; }   // Lemma P5 (bridges only)
        if ((double)sx.cnt / g.n > prm.tau_dense) { st.n_skip++; log_op("SKIP-dense", x, y, before, before); return; }
        uint64_t cost_push = prm.est_sample ? estimate_D(sx, dir_from(e, x), 17 + x) : sx.D[dir_from(e, x)];
        uint64_t cost_pull = prm.est_sample ? estimate_D(sy, dir_from(e, y), 29 + y) : sy.D[dir_from(e, y)];
        if (prm.cascade && !dry_run) {                   // v16: cascade scans make a scan against a sparse set cheaper
            cost_push = (uint64_t)eff_cost(cost_push, sx.cnt, sy);
            cost_pull = (uint64_t)eff_cost(cost_pull, sy.cnt, sx);
        }
        if (dry_run && prm.optimistic) {                 // upper bound on admission: unknown sets cost nothing
            if (x < (int)dry_unknown.size() && dry_unknown[x]) cost_push = 0;
            if (y < (int)dry_unknown.size() && dry_unknown[y]) cost_pull = 0;
        }
        double extra = dry_run && n_admitted == 0 ? prm.first_cost : 0.0;
        if (host_root >= 0 && prm.filter_cost > 0 && !((filtered_mask >> y) & 1))
            extra += prm.filter_cost * (cur_scan_rows >= 0 ? cur_scan_rows : host_scan_rows(y));
        if (dry_run && prm.pred_cost > 0)                // materializing the source's predicates
            for (int z = 0; z < q->k; z++)
                if (((sx.sources >> z) & 1) && !((dry_materialized >> z) & 1)) extra += prm.pred_cost * dry_pred_size[z];
        if (host_root < 0) extra += prm.word_cost * (double)sy.B.words();   // v11: passes over the bitmap words
        if (budget >= 0 && (double)std::min(cost_push, cost_pull) + extra > budget) {
            st.n_skip++; std::ostringstream ex; ex << "[c=" << std::min(cost_push, cost_pull) << ";b=" << (long)budget << "]";
            log_op("SKIP-budget", x, y, before, before, ex.str().c_str()); return;
        }
        if (!dry_run && prm.reach_pilot && budget >= 0 && (double)std::min(cost_push, cost_pull) > prm.pilot_min) {
            double lam = reach_pilot(x, y, e);
            if (lam >= 0) {
                double model = 1.0 - std::min(dry_surv, 0.999);
                double b2 = budget * (1.0 - lam) / model;
                if ((double)std::min(cost_push, cost_pull) + extra > b2) {
                    st.n_skip++; std::ostringstream ex; ex << "[lam=" << lam << ";b=" << (long)b2 << "]";
                    log_op("SKIP-pilot", x, y, before, before, ex.str().c_str()); return;
                }
            }
        }
        filtered_mask |= 1u << y;                        // from here on, y's scans carry a filter
        if (dry_run) {                                   // pre-screen: admitted; shrink the estimate
            n_admitted++; dry_needed |= sx.sources; dry_materialized |= sx.sources;
            sy.cnt = (uint64_t)std::max(1.0, (double)sy.cnt * dry_surv);
            sy.D[0] = (uint64_t)((double)sy.D[0] * dry_surv); sy.D[1] = (uint64_t)((double)sy.D[1] * dry_surv);
            sy.sources |= sx.sources; sy.full = false;
            std::ostringstream ex; ex << "[c=" << (long)((double)std::min(cost_push, cost_pull) + extra) << ";b=" << (long)budget << "]";
            log_op("ADMIT", x, y, before, sy.cnt, ex.str().c_str()); return;
        }
        std::ostringstream bx; bx << "[c=" << std::min(cost_push, cost_pull) << ";b=" << (long)budget << "]";
        std::string bs = bx.str();
        if ((double)cost_push <= prm.tau_bound * sy.cnt) {                     // case A: bound decisive
            push(x, y, e); log_op("PUSH-A", x, y, before, sy.cnt, bs.c_str()); return;
        }
        if (cost_pull <= cost_push) {                                           // case B: pull with abort
            bool done = pull(x, y, e, true, 0, nullptr);
            log_op(done ? "PULL-B" : "ABORT-B", x, y, before, sy.cnt, bs.c_str()); return;
        }
        // case C: push cheaper, bound not decisive -> random pilot on B_y unless the pilot itself
        // would cost more than the push
        double pilot_cost = (double)cost_pull * std::min(1.0, (double)prm.gamma / std::max<uint64_t>(sy.cnt, 1));
        if (pilot_cost >= (double)cost_push) { bool ok = push(x, y, e, true); log_op(ok ? "PUSH-C0" : "ABORT-P", x, y, before, sy.cnt, bs.c_str()); return; }
        double lam = 0;
        bool complete = pull(x, y, e, false, prm.gamma, &lam);
        if (complete) { log_op("PULL-Cfull", x, y, before, sy.cnt); return; }
        if (lam > prm.tau_sel) { st.n_abort++; log_op("ABORT-C", x, y, before, sy.cnt); return; }
        bool ok = push(x, y, e, true); log_op(ok ? "PUSH-C" : "ABORT-P", x, y, before, sy.cnt, bs.c_str());
    }

    // ---- planning ---------------------------------------------------------------
    // Root rule (LargestRoot-G, single label): no-predicate first, then larger degree sum, then lower index.
    int choose_root() const {
        int best = 0;
        auto key = [&](int x) { return std::make_tuple(q->preds[x].empty() ? 1 : 0, S[x].D[0] + S[x].D[1], -x); };
        for (int x = 1; x < q->k; x++) if (key(x) > key(best)) best = x;
        return best;
    }
    struct Tree { int root; std::vector<int> parent, pedge; std::vector<std::vector<int>> children; std::vector<int> pre, post; };
    Tree root_tree(int r, bool sort_children) const {
        Tree t; t.root = r; t.parent.assign(q->k, -1); t.pedge.assign(q->k, -1); t.children.assign(q->k, {});
        std::vector<int> order{r}; std::vector<bool> seen(q->k, false); seen[r] = true;
        for (size_t i = 0; i < order.size(); i++) {
            int x = order[i];
            for (int ei = 0; ei < (int)q->edges.size(); ei++) {
                const PEdge& e = q->edges[ei];
                if (e.a != x && e.b != x) continue;
                int y = other(e, x);
                if (seen[y]) continue;
                seen[y] = true; t.parent[y] = x; t.pedge[y] = ei; t.children[x].push_back(y); order.push_back(y);
            }
        }
        if (sort_children)
            for (int x = 0; x < q->k; x++) {
                // v17: most selective child first (ATP's chaining idea: shrink the parent before the next
                // transfer reads it); default: cheapest transfer first
                auto surv = [&](int c) {
                    const PEdge& e = q->edges[t.pedge[c]];
                    double rho = std::min(1.0, (double)S[c].D[dir_from(e, c)] / std::max(1.0, (double)g.m));
                    double avg = S[x].cnt ? (double)S[x].D[dir_from(e, x)] / (double)S[x].cnt : 0.0;
                    return 1.0 - std::pow(1.0 - rho, avg);
                };
                std::stable_sort(t.children[x].begin(), t.children[x].end(), [&](int a, int b) {
                    if (prm.sibling_order == 1) { double sa = surv(a), sb = surv(b); if (sa != sb) return sa < sb; }
                    return S[a].D[dir_from(q->edges[t.pedge[a]], a)] < S[b].D[dir_from(q->edges[t.pedge[b]], b)];
                });
            }
        std::function<void(int)> rec = [&](int x) { t.pre.push_back(x); for (int c : t.children[x]) rec(c); t.post.push_back(x); };
        rec(r);
        return t;
    }

    // Host-like default join order: start at the smallest candidate set, greedily extend to the
    // frontier variable with the smallest candidate set (exact predicate cardinalities, no degree info).
    std::vector<Step> default_order(int& start) const {
        start = 0;
        for (int x = 1; x < q->k; x++) if (S[x].cnt < S[start].cnt) start = x;
        return greedy_order(start);
    }
    // Host-estimate order: the same greedy rule, but on the sizes a host optimizer estimates without
    // statistics on the predicate columns -- a constant selectivity per predicate (Kuzu: 10%), no
    // degree information. Ties keep the lower pattern-vertex index.
    std::vector<Step> estimate_order(int& start) const {
        std::vector<double> est(q->k);
        for (int x = 0; x < q->k; x++) est[x] = (double)g.n * std::pow(prm.est_sel, (double)q->preds[x].size());
        start = 0;
        for (int x = 1; x < q->k; x++) if (est[x] < est[start]) start = x;
        return greedy_order(start, &est);
    }
    std::vector<Step> greedy_order(int start, const std::vector<double>* est = nullptr) const {
        auto size = [&](int y) { return est ? (*est)[y] : (double)S[y].cnt; };
        std::vector<Step> steps; std::vector<bool> bound(q->k, false); bound[start] = true;
        std::vector<bool> used(q->edges.size(), false);
        for (int it = 0; it + 1 < q->k; it++) {
            int be = -1, bx = -1, by = -1;
            for (int ei = 0; ei < (int)q->edges.size(); ei++) {
                if (used[ei]) continue;
                const PEdge& e = q->edges[ei];
                int x, y;
                if (bound[e.a] && !bound[e.b]) { x = e.a; y = e.b; }
                else if (bound[e.b] && !bound[e.a]) { x = e.b; y = e.a; }
                else continue;
                if (be < 0 || size(y) < size(by) || (size(y) == size(by) && y < by)) { be = ei; bx = x; by = y; }
            }
            used[be] = true; bound[by] = true;
            steps.push_back({bx, by, dir_from(q->edges[be], bx), be, {}});
            add_checks(steps.back(), bound, used);
        }
        return steps;
    }
    // closing edges between the newly bound vertex and earlier bound ones become checks of this step
    void add_checks(Step& s, const std::vector<bool>& bound, std::vector<bool>& used) const {
        for (int ei = 0; ei < (int)q->edges.size(); ei++) {
            if (used[ei]) continue;
            const PEdge& e = q->edges[ei];
            int z = e.a == s.nv ? e.b : e.b == s.nv ? e.a : -1;
            if (z < 0 || z == s.nv || !bound[z]) continue;
            s.checks.push_back({z, dir_from(e, z), ei}); used[ei] = true;
        }
    }
    // Random connected left-deep order (for the robustness experiment).
    std::vector<Step> random_order(int& start, uint64_t seed) const {
        std::mt19937_64 rng(seed);
        start = rng() % q->k;
        std::vector<Step> steps; std::vector<bool> bound(q->k, false); bound[start] = true;
        std::vector<bool> used(q->edges.size(), false);
        for (int it = 0; it + 1 < q->k; it++) {
            std::vector<std::tuple<int, int, int>> cand;
            for (int ei = 0; ei < (int)q->edges.size(); ei++) {
                if (used[ei]) continue;
                const PEdge& e = q->edges[ei];
                if (bound[e.a] && !bound[e.b]) cand.emplace_back(ei, e.a, e.b);
                else if (bound[e.b] && !bound[e.a]) cand.emplace_back(ei, e.b, e.a);
            }
            auto [ei, x, y] = cand[rng() % cand.size()];
            used[ei] = true; bound[y] = true;
            steps.push_back({x, y, dir_from(q->edges[ei], x), ei, {}});
            add_checks(steps.back(), bound, used);
        }
        return steps;
    }

    // ---- BitmapEdgeScan: filtered adjacency for a join step ---------------------------
    struct FAdj {
        bool built = false;
        std::vector<uint32_t> rank;      // prefix popcount per word of the source bitmap
        std::vector<uint64_t> off;       // offsets indexed by rank(v)
        std::vector<uint32_t> nbr;       // surviving neighbours only
    };
    std::vector<FAdj> fadj;
    uint64_t edge_scan_work = 0; int n_edge_scans = 0;
    static inline uint32_t rank_of(const FAdj& f, const Bitmap& B, uint64_t v) {
        uint64_t w = v >> 6; uint64_t mask = (v & 63) ? ((1ULL << (v & 63)) - 1) : 0ULL;
        return f.rank[w] + __builtin_popcountll(B.w[w] & mask);
    }
    void build_edge_scans() {
        fadj.assign(steps.size(), FAdj());
        if (!prm.edge_scan) return;
        // expected prefixes (partial matches) before each step, running product along the order
        double prefixes = (double)S[join_start].cnt;
        for (size_t i = 0; i < steps.size(); i++) {
            const Step& st_ = steps[i];
            const VarState& sx = S[st_.bound]; const VarState& sy = S[st_.nv];
            bool probe = !(sy.full || sy.reduced_via == st_.edge);
            double avgdeg = sx.cnt ? (double)sx.D[st_.dir] / (double)sx.cnt : 0.0;
            double visits = prefixes;
            double scans = prefixes * avgdeg;
            // survival of a probe: if B_y already carries x's information (B_y ⊆ N(B_x) along this
            // edge) its density among x's neighbours is |B_y| / |N(B_x)|, bounded by the push cost,
            // not |B_y| / n
            double denom = (sx.sources && (sx.sources & ~sy.sources) == 0) ? std::min((double)g.n, (double)sx.D[st_.dir]) : (double)g.n;
            double surv_per_prefix = avgdeg * std::min(1.0, (double)sy.cnt / std::max(denom, 1.0));
            // if x already carries y's information, every x-vertex has a surviving neighbour (semi-join)
            if (sy.sources && (sy.sources & ~sx.sources) == 0) surv_per_prefix = std::max(surv_per_prefix, 1.0);
            prefixes = probe ? visits * surv_per_prefix : scans;
            for (const Chk& c : st_.checks)                       // independence estimate of a closing edge
                prefixes *= std::min(1.0, (S[c.z].cnt ? (double)S[c.z].D[c.dir] / (double)S[c.z].cnt : 0.0) / (double)g.n);
            if (!probe || sx.cnt == 0) continue;
            if (prm.word_cost > 0) {                          // v12: build only if the scans it saves pay for it
                double saved = scans - visits * surv_per_prefix;
                double cost = (double)sx.D[st_.dir] + (double)sx.cnt + prm.word_cost * (double)sx.B.words();
                if (saved < prm.scan_beta * cost) continue;
            } else if (visits < prm.scan_beta * (double)sx.cnt) continue;   // each source vertex visited < scan_beta times
            build_fadj(i);
        }
    }
    void build_fadj(size_t i) {
        const Step& st_ = steps[i];
        const VarState& sx = S[st_.bound]; const VarState& sy = S[st_.nv];
        FAdj& f = fadj[i]; f.built = true;
        f.rank.resize(sx.B.words()); uint32_t acc = 0;
        for (size_t w = 0; w < sx.B.words(); w++) { f.rank[w] = acc; acc += __builtin_popcountll(sx.B.w[w]); }
        f.off.reserve(sx.cnt + 1); f.off.push_back(0);
        uint64_t work = 0;
        if (prm.cascade) const_cast<Engine*>(this)->prep_target(const_cast<VarState&>(sy), (double)sx.D[st_.dir]);
        sx.B.for_each([&](uint64_t v) {
            const uint32_t* b = g.adj_begin(v, st_.dir); const uint32_t* en = g.adj_end(v, st_.dir);
            work += scan_in(sy.B, b, en, [&](uint32_t u) { f.nbr.push_back(u); });
            f.off.push_back(f.nbr.size());
            tick(en - b + 1);
        });
        edge_scan_work += work; n_edge_scans++;
    }
    bool online_scans = false;    // set per method: the join may build filtered adjacency on demand
    int n_online_scans = 0;

    // ---- join phase (shared) ----------------------------------------------------
    std::vector<Step> steps;
    int join_start = 0;
    std::vector<uint64_t> bind;
    uint64_t sink = 0;
    std::vector<uint64_t> level_work, level_visits, level_hits;
    uint64_t enumerate(size_t level) {
        const Step& s = steps[level];
        uint64_t v = bind[s.bound];
        const VarState& sy = S[s.nv];
        const uint32_t* b; const uint32_t* en;
        bool probe = !(sy.full || sy.reduced_via == s.edge);   // join-phase counterpart of Lemma P5
        if (online_scans && probe && !fadj[level].built &&
            (double)level_work[level] >= (double)(S[s.bound].D[s.dir] + S[s.bound].cnt) +
                                         prm.word_cost * (double)S[s.bound].B.words() &&   // rent reached the price of buying
            worth_building(level)) {
            build_fadj(level); n_online_scans++;
        }
        const FAdj& f = fadj[level];
        if (f.built) {                                          // BitmapEdgeScan: surviving neighbours only
            uint32_t r = rank_of(f, S[s.bound].B, v);
            b = f.nbr.data() + f.off[r]; en = f.nbr.data() + f.off[r + 1]; probe = false;
        } else { b = g.adj_begin(v, s.dir); en = g.adj_end(v, s.dir); }
        bool last = level + 1 == steps.size();
        if (!s.checks.empty()) {                                // cyclic step: intersect sorted lists
            const uint32_t* lb[8]; const uint32_t* le[8]; int nl = 1;
            lb[0] = b; le[0] = en;
            for (const Chk& c : s.checks) { uint64_t zv = bind[c.z]; lb[nl] = g.adj_begin(zv, c.dir); le[nl] = g.adj_end(zv, c.dir); nl++; }
            int best = 0;
            for (int i = 1; i < nl; i++) if (le[i] - lb[i] < le[best] - lb[best]) best = i;
            uint64_t w = le[best] - lb[best];
            st.join_work += w; level_work[level] += w; level_visits[level]++;
            enum_cost += w + 1; if (enum_cost > enum_budget) throw SwitchToCount{};
            tick(w + 1);
            uint64_t c = 0;
            for (const uint32_t* p = lb[best]; p < le[best]; ++p) {
                uint32_t u = *p; bool ok = true;
                for (int i = 0; i < nl && ok; i++) if (i != best) ok = std::binary_search(lb[i], le[i], u);
                if (!ok || (probe && !sy.B.test(u))) continue;
                if (last) { c++; continue; }
                bind[s.nv] = u;
                c += enumerate(level + 1);
            }
            return c;
        }
        if (prm.cascade && probe && !sy.B.sum_ok && level_work[level] >= sy.B.words())
            prep_target(const_cast<VarState&>(sy), (double)level_work[level]);   // v16: lazy, ski rental
        if (probe && sy.B.use_skip) {                           // v16: cascade probe of a sparse target
            uint64_t c = 0;
            uint64_t w = scan_in(sy.B, b, en, [&](uint32_t u) {
                level_hits[level]++;
                if (last) { c++; return; }
                bind[s.nv] = u;
                c += enumerate(level + 1);
            });
            st.join_work += w; level_work[level] += w; level_visits[level]++;
            tick(w + 1);
            enum_cost += 1 + w;
            if (enum_cost > enum_budget) throw SwitchToCount{};
            return c;
        }
        bool shortcut = last && !probe && prm.count_shortcut;
        if (shortcut) st.join_out += en - b; else st.join_work += en - b;   // v18: scanned vs counted
        level_work[level] += en - b; level_visits[level]++;
        tick(en - b + 1);
        enum_cost += 1 + (shortcut ? 0 : (uint64_t)(en - b));
        if (enum_cost > enum_budget) throw SwitchToCount{};
        uint64_t c = 0;
        if (last) {
            if (!probe) {
                if (prm.count_shortcut) return en - b;
                for (; b < en; ++b) { sink += *b; c++; }       // pay for producing every tuple
                return c;
            }
            for (; b < en; ++b) c += sy.B.test(*b);
            level_hits[level] += c;
            return c;
        }
        for (; b < en; ++b) {
            if (probe && !sy.B.test(*b)) continue;
            level_hits[level]++;
            bind[s.nv] = *b;
            c += enumerate(level + 1);
        }
        return c;
    }
    // ---- counting join (tree patterns, count(*)) ------------------------------------------------
    // The forward pass of the transfer plan over the counting semiring: cnt_x(v) = prod over the children c
    // of x of sum_{u in N_e(v) ∩ B_c} cnt_c(u), bottom-up over a tree rooted at r; the result is the sum of
    // cnt_r over B_r. Each edge is evaluated in the cheaper direction (push from the child or pull into the
    // parent), as a transfer is. Arithmetic is mod 2^64, exact whenever the count fits in 64 bits. Arrays
    // are calloc'ed (untouched pages stay unmapped), so a small set costs little.
    bool is_tree_pattern() const { return (int)q->edges.size() == q->k - 1; }
    uint64_t count_cost(int r) const {
        Tree t = const_cast<Engine*>(this)->root_tree(r, false);
        uint64_t c = 0;
        // v14: every counted vertex costs passes over its bitmap words and a count array (allocation, initialization,
        // products), every pushed edge a sum array
        double words = prm.word_cost * (double)((g.n + 63) / 64);       // v15: rank table + bitmap passes per vertex
        double cu = prm.count_unit;                                    // entries of counting vs. of enumeration
        double cc = 0;
        for (int x = 0; x < q->k; x++) {
            if (t.parent[x] < 0) { cc += (double)S[x].cnt + 2 * words; continue; }
            const PEdge& e = q->edges[t.pedge[x]];
            if (t.children[x].empty() && S[x].full) { cc += (double)S[t.parent[x]].cnt; continue; }   // degree lookup
            cc += 2.0 * (double)S[x].cnt + 2 * words +
                  cu * (double)std::min(S[x].D[dir_from(e, x)], S[t.parent[x]].D[dir_from(e, t.parent[x])]);
        }
        c = (uint64_t)cc;
        return c;
    }
    uint64_t count_tree(int r) {
        // v15: count arrays indexed by the rank of a vertex in its candidate set (O(|B|) memory, no page faults on
        // an n-sized array); rank(v) = popcount of the bitmap before v, from a per-word prefix table
        Tree t = root_tree(r, false);
        struct Rank {
            std::vector<uint32_t> pre;
            void build(const Bitmap& B) { pre.resize(B.words()); uint32_t a = 0; for (size_t w = 0; w < B.words(); w++) { pre[w] = a; a += __builtin_popcountll(B.w[w]); } }
            inline uint32_t of(const Bitmap& B, uint64_t v) const { return pre[v >> 6] + __builtin_popcountll(B.w[v >> 6] & ((1ULL << (v & 63)) - 1)); }
        };
        std::vector<std::vector<uint64_t>> cnt(q->k);
        std::vector<Rank> rk(q->k);
        auto skip = [&](int x) { return x != r && t.children[x].empty() && S[x].full; };   // unconstrained leaf: degrees
        if (prm.cascade) for (int x = 0; x < q->k; x++) if (!skip(x)) prep_target(S[x], (double)(S[x].D[0] + S[x].D[1]));
        for (int x : t.post) {
            if (skip(x)) continue;
            rk[x].build(S[x].B); tick(S[x].B.words());
            std::vector<uint64_t>& acc = cnt[x];
            acc.assign(S[x].cnt, 1);
            for (int c : t.children[x]) {
                const PEdge& e = q->edges[t.pedge[c]];
                int dc = dir_from(e, c), dx = dir_from(e, x);
                if (skip(c)) {                                       // sum over all neighbours of 1 = the degree
                    uint64_t i = 0;
                    S[x].B.for_each([&](uint64_t v) { acc[i++] *= (uint64_t)g.deg(v, dx); });
                    tick(S[x].cnt + 1);
                    continue;
                }
                const std::vector<uint64_t>& cc = cnt[c];
                std::vector<uint64_t> sm(S[x].cnt, 0);
                if (S[c].D[dc] <= S[x].D[dx]) {                      // push the child's counts to its neighbours
                    uint64_t j = 0;
                    S[c].B.for_each([&](uint64_t u) {
                        uint64_t w = cc[j++];
                        if (!w) return;
                        const uint32_t* b = g.adj_begin(u, dc); const uint32_t* en = g.adj_end(u, dc);
                        uint64_t wk = scan_in(S[x].B, b, en, [&](uint32_t p) { sm[rk[x].of(S[x].B, p)] += w; });
                        st.join_work += wk; tick(wk + 1);
                    });
                } else {                                             // pull them into the parent's candidates
                    uint64_t i = 0;
                    S[x].B.for_each([&](uint64_t v) {
                        uint64_t me = i++;
                        if (!acc[me]) return;
                        const uint32_t* b = g.adj_begin(v, dx); const uint32_t* en = g.adj_end(v, dx);
                        uint64_t a = 0;
                        uint64_t wk = scan_in(S[c].B, b, en, [&](uint32_t p) { a += cc[rk[c].of(S[c].B, p)]; });
                        sm[me] = a;
                        st.join_work += wk; tick(wk + 1);
                    });
                }
                for (uint64_t i = 0; i < S[x].cnt; i++) acc[i] *= sm[i];
                std::vector<uint64_t>().swap(cnt[c]);
            }
        }
        uint64_t total = 0;
        for (uint64_t v : cnt[r]) total += v;
        return total;
    }

    // v13: buy only if the rest of this level is expected to scan at least the price again; the rest is
    // extrapolated from the progress of the outermost loop (the share of start vertices done so far)
    uint64_t start_done = 0, start_total = 1;
    bool worth_building(size_t level) const {
        if (!prm.extrapolate) return true;
        double p = (double)(start_done + 1) / (double)std::max<uint64_t>(start_total, 1);
        if (p >= 1.0) return false;
        double rest = (double)level_work[level] * (1.0 - p) / p;
        // the list is built for every source vertex: the level must visit each of them at least once on average
        if ((double)level_visits[level] / p < (double)S[steps[level].bound].cnt) return false;
        // a filtered list saves only the entries that the probe rejects, and writing it costs the kept ones
        double hit = level_work[level] ? std::min(1.0, (double)level_hits[level] / (double)level_work[level]) : 0.0;
        double D = (double)S[steps[level].bound].D[steps[level].dir];
        double price = D * (1.0 + hit) + (double)S[steps[level].bound].cnt + prm.word_cost * (double)S[steps[level].bound].B.words();
        return rest * (1.0 - hit) >= price;
    }
    uint64_t join(int start) {
        bind.assign(q->k, 0);
        uint64_t total = 0;
        start_done = 0; start_total = S[start].cnt;

        if (fadj.size() != steps.size()) fadj.assign(steps.size(), FAdj());
        level_work.assign(steps.size(), 0); level_visits.assign(steps.size(), 0); level_hits.assign(steps.size(), 0);
        if (steps.empty()) return S[start].cnt;
        S[start].B.for_each([&](uint64_t v) { bind[start] = v; total += enumerate(0); start_done++; });
        std::ostringstream o; o << "LEVELS(";
        for (size_t i = 0; i < steps.size(); i++) o << (i ? ";" : "") << steps[i].bound << ">" << steps[i].nv << (fadj[i].built ? "*" : "") << ":" << level_visits[i] << "/" << level_work[i];
        o << ")|"; st.ops += o.str();
        return total;
    }

    // ---- methods ------------------------------------------------------------------
    void transfer_M3() {
        std::vector<Bitmap> snap(q->k);
        for (int x = 0; x < q->k; x++) if (!q->preds[x].empty()) snap[x] = S[x].B;
        for (int x = 0; x < q->k; x++) {
            if (q->preds[x].empty()) continue;
            for (const PEdge& e : q->edges) {
                if (e.a != x && e.b != x) continue;
                int y = other(e, x);
                // push from the original predicate bitmap (static one-hop mask)
                Bitmap saved; saved.w.swap(S[x].B.w); S[x].B.w = snap[x].w;
                uint64_t before = S[y].cnt; op_begin();
                push(x, y, e);
                S[x].B.w.swap(saved.w);
                log_op("PUSH", x, y, before, S[y].cnt);
            }
        }
    }
    void transfer_M4() {
        int r = choose_root();
        Tree t = root_tree(r, false);
        for (int c : t.post) if (c != r) { uint64_t b = S[t.parent[c]].cnt; op_begin(); push(c, t.parent[c], q->edges[t.pedge[c]]); log_op("PUSH", c, t.parent[c], b, S[t.parent[c]].cnt); }
        for (int x : t.pre) for (int c : t.children[x]) { uint64_t b = S[c].cnt; op_begin(); push(x, c, q->edges[t.pedge[c]]); log_op("PUSH", x, c, b, S[c].cnt); }
    }
    // A transfer x->y (edge e) is useful iff its information is consumed: the join probes B_y when
    // entering y through an edge other than e (or y is the join's start variable), or a later useful
    // transfer uses y as its source. Computed by backward induction over the transfer sequence.
    struct TOp { int x, y, ei; };
    std::vector<bool> useful_ops(const std::vector<TOp>& seq, int start) const {
        std::vector<int> enter(q->k, -1);
        for (const Step& s : steps) enter[s.nv] = s.edge;
        (void)start;   // start has enter == -1, i.e. its bitmap is consumed directly
        // forward simulation of the source-skip rule (Lemma P5): an op carries new information only
        // if sources(x) is not already contained in sources(y), assuming earlier ops complete
        std::vector<uint32_t> src(q->k);
        for (int x = 0; x < q->k; x++) src[x] = S[x].sources;
        std::vector<bool> eff(seq.size(), false);
        for (size_t i = 0; i < seq.size(); i++) {
            if (seq[i].ei < 0) { eff[i] = true; continue; }   // self filter
            eff[i] = !is_bridge[seq[i].ei] || (src[seq[i].x] & ~src[seq[i].y]) != 0;
            if (eff[i]) src[seq[i].y] |= src[seq[i].x];
        }
        std::vector<bool> useful(seq.size(), false);
        for (int i = (int)seq.size() - 1; i >= 0; i--) {
            if (!eff[i]) continue;
            // host plan: every scan of y takes B_y; counting: every count array is sized by B_y, also along the entering edge
            bool u = host_root >= 0 || count_only || (seq[i].ei >= 0 && enter[seq[i].y] != seq[i].ei);
            for (size_t j = i + 1; j < seq.size() && !u; j++) if (seq[j].x == seq[i].y && useful[j]) u = true;
            useful[i] = u;
        }
        return useful;
    }
    bool prune_useless = true;
    // ---- host plan model -------------------------------------------------------------
    // A relational host joins copies of the edge table with hash, merge or index nested-loop joins in a
    // join tree of its own choosing. With a host plan, the benefit of a transfer is the reduction of the
    // work of that tree: the sum over its nodes of the rows they produce, each estimated as the number of
    // matches of the sub-pattern below the node restricted to the current candidate sets (configuration
    // model: edges between B_a and B_b ~ min(D_a, D_b, D_a * D_b / |E|) with exact degree sums).
    // leaf: edge >= 0 or vertex >= 0; param: the inner side of a nested loop that looks up rows per outer row
    // (an index scan): it produces no rows of its own, its work is the join's output
    struct HostNode { int left = -1, right = -1, edge = -1, vertex = -1; bool param = false; };
    uint32_t filtered_mask = 0;   // vertices whose scans already carry a transfer filter
    uint32_t self_filters = 0;    // predicate vertices whose own candidate set filters the host's scans
    // rows read by the scans of the host plan that have a column of vertex y (an edge-table copy reads |E|
    // rows, a vertex-table copy |V|)
    double host_scan_rows(int y) const {
        double r = 0.0;
        for (const HostNode& h : host_plan) {
            if (h.left >= 0) continue;
            if (h.edge >= 0 && (q->edges[h.edge].a == y || q->edges[h.edge].b == y)) r += (double)g.m;
            if (h.vertex == y) r += (double)g.n;
        }
        return r;
    }
    std::vector<HostNode> host_plan; int host_root = -1;
    // vmask: vertices of the node's sub-pattern; rmask: vertices whose predicate the node applies (their
    // vertex-table copy lies below it). A vertex restricts a node only if it is in rmask or carries a
    // transfer filter (filt); otherwise the node sees all of its vertices and edges.
    struct HostEval { double rows; uint32_t vmask; uint64_t emask; uint32_t rmask; };
    // hM[x] = degree moments of B_x (scaled with its estimated size); a vertex that the sub-pattern joins
    // through several edges contributes sum_v prod_e deg_e(v), not |B| * prod_e avgdeg_e: the ratio
    // |B| * M / (D * D) of its second moment (the l2 norm of its degree sequence, as in LpBound) corrects it
    std::vector<std::array<double, 3>> hM;
    // hundo[x][e] = factor by which transfers along pattern edge e shrank B_x: such a transfer removes only
    // vertices without an e-neighbour on the other side, so the e-edges between the two candidate sets stay;
    // the configuration model must see x's degree sum from before those transfers (without this, a set of
    // hub neighbours built by a transfer from the hubs looked independent of them: 54 edges instead of 4,200)
    std::vector<std::vector<double>> hundo;
    double undo(int x, int e) const { return hundo.empty() ? 1.0 : hundo[x][e]; }
    void host_eval(int node, const std::vector<double>& sz, const std::vector<double>& Dout, const std::vector<double>& Din,
                   uint32_t filt, std::vector<HostEval>& out) const {
        const HostNode& h = host_plan[node];
        HostEval ev{1.0, 0, 0, 0};
        if (h.left < 0) {
            ev.vmask = h.edge >= 0 ? (1u << q->edges[h.edge].a) | (1u << q->edges[h.edge].b) : (1u << h.vertex);
            ev.emask = h.edge >= 0 ? (1ull << h.edge) : 0;
            ev.rmask = h.vertex >= 0 ? (1u << h.vertex) : 0;
        } else {
            host_eval(h.left, sz, Dout, Din, filt, out);
            ev.vmask = out[h.left].vmask; ev.emask = out[h.left].emask; ev.rmask = out[h.left].rmask;
            if (h.right >= 0) {
                host_eval(h.right, sz, Dout, Din, filt, out);
                ev.vmask |= out[h.right].vmask; ev.emask |= out[h.right].emask; ev.rmask |= out[h.right].rmask;
            }
        }
        // effective candidate statistics of each vertex in this node
        auto rs = [&](int x) { return ((ev.rmask | filt) >> x) & 1; };
        auto S_ = [&](int x) { return rs(x) ? std::max(sz[x], 1e-9) : (double)g.n; };
        auto Do = [&](int x) { return rs(x) ? Dout[x] : (double)g.m; };
        auto Di = [&](int x) { return rs(x) ? Din[x] : (double)g.m; };
        for (int x = 0; x < q->k; x++) if ((ev.vmask >> x) & 1) ev.rows *= S_(x);
        for (int e = 0; e < (int)q->edges.size(); e++) {
            if (!((ev.emask >> e) & 1)) continue;
            int a = q->edges[e].a, b = q->edges[e].b;
            double ua = rs(a) ? undo(a, e) : 1.0, ub = rs(b) ? undo(b, e) : 1.0;
            double me = std::min(std::min(Do(a), Di(b)), Do(a) * ua * Di(b) * ub / std::max(1.0, (double)g.m));
            ev.rows *= me / (std::max(S_(a), 1.0) * std::max(S_(b), 1.0));
        }
        for (int x = 0; x < q->k; x++) {
            if (!((ev.vmask >> x) & 1)) continue;
            int first = -1;
            for (int e = 0; e < (int)q->edges.size(); e++) {
                if (!((ev.emask >> e) & 1) || (q->edges[e].a != x && q->edges[e].b != x)) continue;
                int d = q->edges[e].a == x ? 0 : 1;           // 0: out-degree at x, 1: in-degree
                if (first < 0) { first = d; continue; }
                double Da = first == 0 ? Do(x) : Di(x), Db = d == 0 ? Do(x) : Di(x);
                double m2 = rs(x) && !hM.empty() ? (first == d ? hM[x][d] : hM[x][2]) : (first == d ? g.M[d] : g.M[2]);
                if (Da > 0 && Db > 0) ev.rows *= std::min(1e6, std::max(0.1, S_(x) * m2 / (Da * Db)));
            }
        }
        out[node] = ev;
    }
    // work removed from the host plan by a transfer x -> y along edge e that shrinks y (and its degree sums)
    // by the factor f: a node whose sub-pattern already contains x and e (so y through e) produces the same
    // rows either way, and the root's rows (the query result) never change
    // filt = vertices that carry a transfer filter before this transfer; afterwards y does too
    double host_gain(int x, int ei, int y, double f, const std::vector<double>& sz, const std::vector<double>& Dout,
                     const std::vector<double>& Din, uint32_t filt) {
        std::vector<HostEval> before(host_plan.size()), after(host_plan.size());
        host_eval(host_root, sz, Dout, Din, filt, before);
        std::vector<double> s2 = sz, o2 = Dout, i2 = Din;
        s2[y] *= f; o2[y] *= f; i2[y] *= f;
        auto saved = hM[y];
        for (double& v : hM[y]) v *= f;
        double su = ei >= 0 ? hundo[y][ei] : 1.0;
        if (ei >= 0 && f > 0) hundo[y][ei] /= f;
        host_eval(host_root, s2, o2, i2, filt | (1u << y), after);
        hM[y] = saved;
        if (ei >= 0) hundo[y][ei] = su;
        // rows that y's filter would test: a full scan reads its table, the inner index scan of a nested
        // loop only the rows its join looks up (about the join's output before the filter)
        last_scan_rows = 0.0;
        for (size_t n = 0; n < host_plan.size(); n++) {
            const HostNode& h = host_plan[n];
            if (h.left >= 0) continue;
            bool has = h.edge >= 0 ? (q->edges[h.edge].a == y || q->edges[h.edge].b == y) : h.vertex == y;
            if (!has) continue;
            if (h.param && host_parent[n] >= 0) last_scan_rows += before[host_parent[n]].rows;
            // a vertex scan with its own predicate tests only the rows the predicate keeps
            else last_scan_rows += h.edge >= 0 ? (double)g.m : !q->preds[y].empty() ? sz[y] : (double)g.n;
        }
        double gain = 0.0;
        if (rptg_trace_on()) {
            fprintf(stderr, "[rptg-trace] %d>%d f=%.4g filt=%x:", x, y, f, filt);
            for (size_t n = 0; n < host_plan.size(); n++) {
                const HostNode& h = host_plan[n];
                fprintf(stderr, " n%zu(%s%s%d)=%.3g->%.3g", n, h.left >= 0 ? "J" : h.edge >= 0 ? "E" : "V", h.param ? "p" : "",
                        h.left >= 0 ? h.left : h.edge >= 0 ? h.edge : h.vertex, before[n].rows, after[n].rows);
            }
            fprintf(stderr, "\n");
        }
        for (size_t n = 0; n < host_plan.size(); n++) {
            if ((int)n == host_root || host_plan[n].param || !((before[n].vmask >> y) & 1)) continue;
            // the node already joins y with a restricted x through the transfer's edge: no change
            if (ei >= 0 && (((before[n].rmask | filt) >> x) & 1) && ((before[n].emask >> ei) & 1)) continue;
            gain += std::max(0.0, before[n].rows - after[n].rows);
        }
        return gain;
    }
    // pre-screen (dry run): decide on estimated candidate-set sizes without touching bitmaps
    bool dry_run = false; int n_admitted = 0; double dry_surv = 1.0;
    double last_scan_rows = 0.0, cur_scan_rows = -1.0; std::vector<double> op_scan_rows;
    std::vector<int> host_parent;
    uint32_t dry_needed = 0;   // predicate vertices whose information an admitted transfer carries
    uint32_t dry_materialized = 0; std::vector<double> dry_pred_size; std::vector<bool> dry_unknown;
    std::vector<double> last_surv;
    // Estimated join work along the host order (independence assumption, exact aggregates):
    //   scans[y] = matches[x] * avgdeg(B_x, dir), matches[y] = scans[y] * |B_y| / n.
    // cap[v] = all estimated scans from the level that enters v onward (an upper bound on the work
    // that pruning B_v could remove); cap[start] = total.
    std::vector<double> join_cap;
    void estimate_join_caps() {
        // prefixes = number of partial matches after each step of the left-deep order (running
        // product); every step visits its bound variable once per prefix.
        std::vector<double> scans(steps.size(), 0.0);
        double prefixes = (double)S[join_start].cnt;
        for (size_t i = 0; i < steps.size(); i++) {
            const Step& st_ = steps[i];
            const VarState& sx = S[st_.bound]; const VarState& sy = S[st_.nv];
            double avgdeg = sx.cnt ? (double)sx.D[st_.dir] / (double)sx.cnt : 0.0;
            double iter = avgdeg;                             // a cyclic step iterates its shortest list
            for (const Chk& c : st_.checks) iter = std::min(iter, S[c.z].cnt ? (double)S[c.z].D[c.dir] / (double)S[c.z].cnt : 0.0);
            scans[i] = prefixes * iter;
            bool probe = !q->preds[st_.nv].empty();          // plan-time: only predicates prune here
            prefixes = probe ? scans[i] * ((double)sy.cnt / (double)g.n) : scans[i];
            for (const Chk& c : st_.checks)
                prefixes *= std::min(1.0, (S[c.z].cnt ? (double)S[c.z].D[c.dir] / (double)S[c.z].cnt : 0.0) / (double)g.n);
            // last level into a probe-free variable is a count (O(1) per prefix), not a scan
            if (i + 1 == steps.size() && q->preds[st_.nv].empty() && st_.checks.empty()) scans[i] = scans[i] / std::max(avgdeg, 1.0);
        }
        join_cap.assign(q->k, 0.0);
        // v22: shrinking B_y saves the scans of the levels after the one that enters y; the entering level scans
        // the adjacency of the previous vertex whatever B_y is (its probe only decides who continues)
        double suffix = 0.0;
        for (int i = (int)steps.size() - 1; i >= 0; i--) { join_cap[steps[i].nv] = suffix; suffix += scans[i]; }
        join_cap[join_start] = suffix + (double)S[join_start].cnt;
    }
    // edges of the pattern that are not in the spanning tree t
    std::vector<int> closing_edges(const Tree& t) const {
        std::vector<bool> in_tree(q->edges.size(), false);
        for (int x = 0; x < q->k; x++) if (t.pedge[x] >= 0) in_tree[t.pedge[x]] = true;
        std::vector<int> out;
        for (int ei = 0; ei < (int)q->edges.size(); ei++) if (!in_tree[ei]) out.push_back(ei);
        return out;
    }
    void transfer_M5() {                                     // arc consistency: push until fixpoint
        for (int round = 0; round < 32; round++) {
            bool changed = false;
            for (const PEdge& e : q->edges) {
                for (int d = 0; d < 2; d++) {
                    int x = d ? e.b : e.a, y = d ? e.a : e.b;
                    uint64_t b0 = S[y].cnt; op_begin(); push(x, y, e); log_op("PUSH", x, y, b0, S[y].cnt);
                    changed |= S[y].cnt != b0;
                }
            }
            if (!changed) break;
        }
    }
    void transfer_M6() {
        filtered_mask = 0;
        // v10: a query whose whole join is estimated below min_work adjacency entries is not worth deciding
        // about (the decision itself costs tens of microseconds); the online scans still protect its join
        // (not when the join will count: a transfer out of a small predicate set is what keeps the count arrays
        // of its unconstrained neighbours small, so the decision pays even for a tiny estimate)
        if (prm.min_work > 0 && host_root < 0 && !dry_run && !count_only) {
            estimate_join_caps();
            if (join_cap[join_start] < prm.min_work) { st.ops += "TINY|"; tiny = true; return; }
        }
        int r = choose_root();
        Tree t = root_tree(r, true);
        std::vector<TOp> seq;
        self_filters = 0;
        enter_idx.assign(q->k, -1);
        for (size_t i = 0; i < steps.size(); i++) enter_idx[steps[i].nv] = (int)i;
        // host plans: a predicate vertex's own candidate set can filter the scans that reach x before the
        // host applies x's predicate (the semi-join of an edge-table copy with the filtered vertex table)
        if (host_root >= 0) for (int x = 0; x < q->k; x++) if (!S[x].full) seq.push_back({x, x, -1});
        for (int c : t.post) if (c != r) seq.push_back({c, t.parent[c], t.pedge[c]});
        // closing edges of a cyclic pattern, both directions, between the two passes
        for (int ei : closing_edges(t)) { const PEdge& e = q->edges[ei]; seq.push_back({e.a, e.b, ei}); seq.push_back({e.b, e.a, ei}); }
        for (int x : t.pre) for (int c : t.children[x]) seq.push_back({x, c, t.pedge[c]});
        std::vector<bool> useful = prune_useless ? useful_ops(seq, join_start) : std::vector<bool>(seq.size(), true);
        // Estimated benefit per op (plan time, accumulator-based, no sampling):
        //   surv(x->y) = 1 - (1 - est|B_x|/n)^{avgdeg(B_y toward x)}   (independence)
        //   benefit    = (1 - surv) * cap[y] if the join probes B_y through another edge,
        //                else the best benefit of a later useful op that uses y as source.
        // Estimated sizes are propagated along the sequence so round trips (x->y->x) are valued correctly.
        std::vector<double> cap(seq.size(), 0.0);
        if (prm.beta != 0) {
            estimate_join_caps();
            std::vector<int> enter(q->k, -1);
            for (const Step& s_ : steps) enter[s_.nv] = s_.edge;
            std::vector<double> est(q->k), &surv = last_surv;
            surv.assign(seq.size(), 1.0);
            std::vector<double> survD(seq.size(), 1.0);
            for (int x = 0; x < q->k; x++) est[x] = (double)S[x].cnt;
            std::vector<double> hgain(seq.size(), 0.0), hDo(q->k), hDi(q->k);
            for (int x = 0; x < q->k; x++) { hDo[x] = (double)S[x].D[0]; hDi[x] = (double)S[x].D[1]; }
            hM.assign(q->k, {0, 0, 0});
            hundo.assign(q->k, std::vector<double>(q->edges.size(), 1.0));
            op_scan_rows.assign(seq.size(), -1.0);
            host_parent.assign(host_plan.size(), -1);
            for (size_t n = 0; n < host_plan.size(); n++) {
                if (host_plan[n].left >= 0) host_parent[host_plan[n].left] = (int)n;
                if (host_plan[n].right >= 0) host_parent[host_plan[n].right] = (int)n;
            }
            uint32_t hfilt = 0;
            for (int x = 0; x < q->k; x++) for (int j = 0; j < 3; j++) hM[x][j] = S[x].M[j];
            for (size_t i = 0; i < seq.size(); i++) {
                if (!useful[i]) continue;
                if (seq[i].ei < 0) {   // self filter: no reduction, the host's scans of x see B_x
                    int y = seq[i].y;
                    surv[i] = 1.0;
                    hgain[i] = host_gain(y, -1, y, 1.0, est, hDo, hDi, hfilt);
                    op_scan_rows[i] = last_scan_rows;
                    hfilt |= 1u << y;
                    continue;
                }
                const VarState& sy = S[seq[i].y];
                double avgdeg = sy.cnt ? (double)sy.D[dir_from(q->edges[seq[i].ei], seq[i].y)] / (double)sy.cnt : 0.0;
                // information does not compound over the same edge: for a round trip x->y->x the
                // reduction of y by the earlier x->y op carries nothing new back to x, so undo it
                double src = est[seq[i].x];
                for (int j = (int)i - 1; j >= 0; j--)
                    if (useful[j] && seq[j].ei == seq[i].ei && seq[j].y == seq[i].x) { if (surv[j] > 0) src /= surv[j]; break; }
                double rho;
                if (prm.surv_deg) {
                    // share of the edge endpoints on the x side that belong to B_x: sum deg(B_x) / |E|,
                    // with the (exact or sampled) degree accumulator of x scaled to its estimated size
                    const VarState& sx = S[seq[i].x];
                    int dx = dir_from(q->edges[seq[i].ei], seq[i].x);
                    double Dx = prm.est_sample ? (double)estimate_D(sx, dx, 41 + seq[i].x) : (double)sx.D[dx];
                    double avgdeg_x = sx.cnt ? Dx / (double)sx.cnt : 0.0;
                    rho = std::min(1.0, src * avgdeg_x / (double)g.m);
                } else {
                    rho = std::min(1.0, src / (double)g.n);
                }
                surv[i] = 1.0 - std::pow(1.0 - rho, avgdeg);
                // v19: share of y's degree sum (toward x, where the join's scans come from) that survives
                if (prm.deg_surv) {
                    int ry = dir_from(q->edges[seq[i].ei], seq[i].y);
                    double tot = 0, keep = 0;
                    for (int b_ = 0; b_ < 32; b_++) {
                        double h = sy.H[ry][b_]; if (h <= 0) continue;
                        double dgr = (double)(1ull << b_) * 1.5;           // representative degree of the bin
                        tot += h; keep += h * (1.0 - std::pow(1.0 - rho, dgr));
                    }
                    survD[i] = tot > 0 ? keep / tot : surv[i];
                }
                if (host_root >= 0) {
                    int y = seq[i].y;
                    hgain[i] = host_gain(seq[i].x, seq[i].ei, y, surv[i], est, hDo, hDi, hfilt);
                    op_scan_rows[i] = last_scan_rows;
                    hfilt |= 1u << y;
                    est[y] *= surv[i]; hDo[y] *= surv[i]; hDi[y] *= surv[i];
                    for (double& v : hM[y]) v *= surv[i];
                    if (surv[i] > 0) hundo[y][seq[i].ei] /= surv[i];
                } else {
                    est[seq[i].y] *= surv[i];
                }
            }
            for (int i = (int)seq.size() - 1; i >= 0; i--) {
                if (!useful[i]) continue;
                double c = host_root >= 0 ? hgain[i] : count_only ? 0.0 :
                           enter[seq[i].y] != seq[i].ei ? (1.0 - (prm.deg_surv ? survD[i] : surv[i])) * join_cap[seq[i].y] : 0.0;
                if (host_root < 0 && prm.count_benefit && counting_query && seq[i].ei >= 0) {   // v20: counting benefit
                    int y = seq[i].y; VarState& sy_ = S[y];
                    uint64_t c0 = sy_.cnt, d0 = sy_.D[0], d1 = sy_.D[1];
                    double C_before = (double)count_cost(join_start);
                    sy_.cnt = (uint64_t)((double)c0 * surv[i]);
                    double f = prm.deg_surv ? survD[i] : surv[i];
                    sy_.D[0] = (uint64_t)((double)d0 * f); sy_.D[1] = (uint64_t)((double)d1 * f);
                    double C_after = (double)count_cost(join_start);
                    sy_.cnt = c0; sy_.D[0] = d0; sy_.D[1] = d1;
                    // v25: the counting benefit carries its own unit (beta_count), expressed in enumeration units
                    // here so that one budget beta * cap applies: cap = max(ben_enum, ben_count * beta_count / beta)
                    double be = beta_eff();
                    c = std::max(c, (C_before - C_after) * prm.beta_count / std::max(be, 1e-9));
                }
                if (seq[i].ei >= 0)
                    for (size_t j = i + 1; j < seq.size(); j++) if (seq[j].x == seq[i].y && useful[j]) c = std::max(c, cap[j]);
                cap[i] = c;
            }
        }
        if (prm.beta < 0) { std::ostringstream o; o << "BETA(" << beta_eff() << ";jn=" << (cal_join_work > 0 ? 1e6 * cal_join_ms / cal_join_work : 0) << ";tn=" << (cal_tr_work > 0 ? 1e6 * cal_tr_ms / cal_tr_work : 0) << ")|"; st.ops += o.str(); }
        for (size_t i = 0; i < seq.size(); i++) {
            if (!useful[i]) { st.n_skip++; op_begin(); log_op("SKIP-useless", seq[i].x, seq[i].y, S[seq[i].y].cnt, S[seq[i].y].cnt); continue; }
            dry_surv = i < last_surv.size() ? last_surv[i] : 1.0;
            cur_scan_rows = host_root >= 0 && i < op_scan_rows.size() ? op_scan_rows[i] : -1.0;
            transfer_dynamic(seq[i].x, seq[i].y, q->edges[seq[i].ei >= 0 ? seq[i].ei : 0], prm.beta != 0 ? beta_eff() * cap[i] : -1.0);
        }
    }

    // ---- host entry point (see rptg_api.h) -------------------------------------------
    // Runs the RPT-G transfer phase (M6) for a pattern whose candidate sets the host has already computed
    // (init[x] empty = no predicate on x) under the host's join order (start vertex, then per step the bound
    // vertex and the pattern edge that binds the next one). Returns the reduced candidate sets in S.
    RunStats reduce(const Query& query, std::vector<Bitmap>& init, int start, const std::vector<std::pair<int, int>>& order) {
        q = &query; st = RunStats();
        deadline = std::chrono::steady_clock::now() + std::chrono::hours(24);
        work_ctr = 0;
        auto t0 = std::chrono::steady_clock::now();
        S.assign(q->k, VarState());
        for (int x = 0; x < q->k; x++) {
            VarState& s = S[x];
            if (x >= (int)init.size() || init[x].w.empty()) {
                s.B.init(g.n, true); s.cnt = g.n; s.D[0] = s.D[1] = g.m; s.full = true; s.sources = 0;
                for (int j = 0; j < 3; j++) s.M[j] = g.M[j];
            } else {
                s.B.w.swap(init[x].w); s.B.n = g.n; s.cnt = s.B.count(); recompute_D(s);
                s.full = false; s.sources = 1u << x; s.reduced_via = -2;
            }
        }
        compute_bridges();
        steps.clear(); join_start = start;
        std::vector<bool> bound(q->k, false), used(q->edges.size(), false); bound[start] = true;
        for (auto [x, ei] : order) {
            const PEdge& e = q->edges[ei];
            int y = other(e, x);
            used[ei] = true; bound[y] = true;
            steps.push_back({x, y, dir_from(e, x), ei, {}});
            add_checks(steps.back(), bound, used);
        }
        transfer_M6();
        st.transfer_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
        st.total_ms = st.transfer_ms;
        return st;
    }

    // Host counting path (2026-10-06): the host hands over the initial bitmaps of a COUNT(*) query over a tree
    // pattern. Count when the counting cost is at most host_factor times the engine's own enumeration estimate
    // (a host enumerates at several times the engine's unit cost); the transfers then run under the counting
    // benefit alone, and the forward pass over the counting semiring gives the count. Returns 1 with the count,
    // or 0 when the host should keep its join (it then calls reduce() as before).
    int count_host(const Query& query, std::vector<Bitmap>& init, int start, const std::vector<std::pair<int, int>>& order,
                   double host_factor, double count_floor, uint64_t* count, double* E_out, double* C_out) {
        q = &query; st = RunStats();
        deadline = std::chrono::steady_clock::now() + std::chrono::hours(24);
        work_ctr = 0;
        if (!is_tree_pattern()) return 0;
        S.assign(q->k, VarState());
        for (int x = 0; x < q->k; x++) {
            VarState& s = S[x];
            if (x >= (int)init.size() || init[x].w.empty()) {
                s.B.init(g.n, true); s.cnt = g.n; s.D[0] = s.D[1] = g.m; s.full = true; s.sources = 0;
                for (int j = 0; j < 3; j++) s.M[j] = g.M[j];
                for (int d = 0; d < 2; d++) for (int b = 0; b < 32; b++) s.H[d][b] = g.hist_deg[d][b];
            } else {
                s.B.w.swap(init[x].w); s.B.n = g.n; s.cnt = s.B.count(); recompute_D(s);
                s.full = false; s.sources = 1u << x; s.reduced_via = -2;
            }
        }
        compute_bridges();
        steps.clear(); join_start = start;
        {
            std::vector<bool> bound(q->k, false), used(q->edges.size(), false); bound[start] = true;
            for (auto [x, ei] : order) {
                const PEdge& e = q->edges[ei];
                int y = other(e, x);
                used[ei] = true; bound[y] = true;
                steps.push_back({x, y, dir_from(e, x), ei, {}});
                add_checks(steps.back(), bound, used);
            }
        }
        host_plan.clear(); host_root = -1;
        fadj.assign(steps.size(), FAdj()); edge_scan_work = 0; n_edge_scans = 0; tiny = false;
        estimate_join_caps();
        double E = join_cap[join_start], C = (double)count_cost(start);
        if (E_out) *E_out = E;
        if (C_out) *C_out = C;
        if (!(C <= count_floor || (E >= prm.min_work && C <= host_factor * E))) return 0;
        counting_query = true; count_only = prm.count_benefit;
        transfer_M6();
        count_only = false; counting_query = false;
        enum_cost = 0; enum_budget = UINT64_MAX;
        *count = count_tree(start);
        enum_budget = UINT64_MAX;
        return 1;
    }

    // Pre-screen for hosts (plan-time information only): est[x] = estimated size of x's candidate set
    // after its predicate (< 0 = no predicate). Degree sums are estimated with the average degree.
    // Returns the number of transfers that would pass the budget; 0 means the host can skip the whole
    // transfer phase, including the predicate scans that feed it.
    // stats (optional, 5 per vertex: Dout, Din, M[0..2]; Dout < 0 = unknown): exact degree sums and moments of
    // predicate sets the host materialized cheaply (small sets), so that hub sets are recognized at plan time
    // candidate-set states from plan-time estimates (sizes, optional exact degree sums and moments), as the
    // pre-screen and the counting decision see them before any predicate is materialized
    void init_from_estimates(const std::vector<double>& est, const std::vector<double>* stats) {
        S.assign(q->k, VarState());
        dry_unknown.assign(q->k, false);
        double avg = g.n ? (double)g.m / (double)g.n : 0.0;
        for (int x = 0; x < q->k; x++) {
            VarState& s = S[x];
            if (x >= (int)est.size() || est[x] < 0) {
                s.cnt = g.n; s.D[0] = s.D[1] = g.m; s.full = true; s.sources = 0;
                for (int j = 0; j < 3; j++) s.M[j] = g.M[j];   // as in reduce(): the moments of the whole graph
            } else {
                s.cnt = (uint64_t)std::max(0.0, std::min((double)g.n, est[x]));
                if (stats && (int)stats->size() >= 5 * (x + 1) && (*stats)[5 * x] >= 0) {
                    s.D[0] = (uint64_t)(*stats)[5 * x]; s.D[1] = (uint64_t)(*stats)[5 * x + 1];
                    for (int j = 0; j < 3; j++) s.M[j] = (*stats)[5 * x + 2 + j];
                } else if (prm.optimistic) {
                    dry_unknown[x] = true;
                    s.D[0] = (uint64_t)g.top_deg(0, (double)s.cnt); s.D[1] = (uint64_t)g.top_deg(1, (double)s.cnt);
                    s.M[0] = g.top_deg2(0, (double)s.cnt); s.M[1] = g.top_deg2(1, (double)s.cnt);
                    s.M[2] = std::sqrt(s.M[0] * s.M[1]);
                } else {
                    s.D[0] = s.D[1] = (uint64_t)((double)s.cnt * avg);
                    for (int j = 0; j < 3; j++) s.M[j] = (double)s.cnt * g.M[j] / std::max<double>(1.0, (double)g.n);
                }
                s.full = false; s.sources = 1u << x; s.reduced_via = -2;
            }
        }
        compute_bridges();
    }
    void set_steps(int start, const std::vector<std::pair<int, int>>& order) {
        steps.clear(); join_start = start;
        std::vector<bool> bound(q->k, false), used(q->edges.size(), false); bound[start] = true;
        for (auto [x, ei] : order) {
            const PEdge& e = q->edges[ei];
            int y = other(e, x);
            used[ei] = true; bound[y] = true;
            steps.push_back({x, y, dir_from(e, x), ei, {}});
            add_checks(steps.back(), bound, used);
        }
    }
    // Counting decision for a host before any predicate is materialized: count when the estimated enumeration
    // is at least min_work and the counting cost is at most host_factor times it (both from the estimates)
    // (count_floor: count whenever the counting cost is below this many entries regardless of E, because E, built
    // from degree sums under independence, can fall two orders of magnitude short on hub neighbourhoods and a host
    // has no ski rental to catch that; a count below the floor costs a few milliseconds)
    bool count_decide(const Query& query, const std::vector<double>& est, int start, const std::vector<std::pair<int, int>>& order,
                      const std::vector<double>* stats, double host_factor, double count_floor, double* E_out, double* C_out) {
        q = &query; st = RunStats();
        deadline = std::chrono::steady_clock::now() + std::chrono::hours(24);
        if (!is_tree_pattern()) return false;
        init_from_estimates(est, stats);
        set_steps(start, order);
        host_plan.clear(); host_root = -1;
        estimate_join_caps();
        double E = join_cap[join_start], C = (double)count_cost(start);
        if (E_out) *E_out = E;
        if (C_out) *C_out = C;
        return C <= count_floor || (E >= prm.min_work && C <= host_factor * E);
    }
    int prescreen(const Query& query, const std::vector<double>& est, int start, const std::vector<std::pair<int, int>>& order,
                  const std::vector<double>* stats = nullptr) {
        q = &query; st = RunStats();
        deadline = std::chrono::steady_clock::now() + std::chrono::hours(24);
        init_from_estimates(est, stats);
        set_steps(start, order);
        dry_run = true; n_admitted = 0; dry_needed = 0; dry_materialized = 0;
        dry_pred_size.assign(q->k, 0.0);
        for (int x = 0; x < q->k; x++) if (!S[x].full) dry_pred_size[x] = (double)S[x].cnt;
        transfer_M6();
        dry_run = false;
        return n_admitted;
    }

    // order_mode: 0 = default (exact sizes), 1 = random with seed, 2 = host estimates (constant selectivity)
    RunStats run(const Query& query, const std::string& method, double timeout_s, int order_mode = 0, uint64_t order_seed = 0) {
        q = &query; st = RunStats();
        deadline = std::chrono::steady_clock::now() + std::chrono::microseconds((long long)(timeout_s * 1e6));
        work_ctr = 0;
        auto t0 = std::chrono::steady_clock::now();
        try {
            init_states();
            compute_bridges();
            int start;
            steps = order_mode == 0 ? default_order(start) : order_mode == 2 ? estimate_order(start) : random_order(start, order_seed);
            join_start = start;
            { std::ostringstream o; o << "ORDER(" << start; for (const Step& s_ : steps) o << ";" << s_.bound << ">" << s_.nv << std::string(s_.checks.size(), '+'); o << ")|"; st.ops += o.str(); }
            auto t1 = std::chrono::steady_clock::now();
            st.init_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
            fadj.assign(steps.size(), FAdj()); edge_scan_work = 0; n_edge_scans = 0; tiny = false;
            if (method == "M3") transfer_M3();
            else if (method == "M4") transfer_M4();
            else if (method == "M5") transfer_M5();
            // v17 (M8): decide between counting and enumerating before any transfer; counting then runs on
            // the predicate sets directly (the forward pass over the counting semiring is the transfer)
            bool upfront = (method == "M8") && is_tree_pattern() && prm.count_far > 0;
            bool count_first = false; double C_up = 0, E_up = 0;
            // v23: the counting benefit of a transfer counts only when counting is plausible, i.e. the estimated
            // enumeration is not below the counting cost (otherwise the transfer is paid for a path never taken)
            counting_query = false;
            if ((method == "M7" || method == "M8") && is_tree_pattern()) {
                estimate_join_caps(); E_up = join_cap[join_start];
                if (E_up >= prm.min_work) { C_up = (double)count_cost(start); counting_query = E_up >= C_up; }
                if (upfront) count_first = E_up >= prm.min_work && E_up > prm.count_far * C_up;
            }
            if (count_first) { std::ostringstream o; o << "UPFRONT(" << (long)E_up << ">" << (long)C_up << ")|"; st.ops += o.str(); }
            // v26: an upfront counting decision no longer skips the transfer phase; the transfers run under the
            // counting benefit alone (a transfer is worth its reduction of the counting cost, at beta_count), so
            // that the counting pass and the edge scans see reduced sets (v25 lost 20x on queries whose unreduced
            // counting cost exceeded the transfers the ski rental ran first)
            count_only = count_first && prm.count_benefit;
            if (method == "M6" || method == "M7" || method == "M8") { if (!count_first || count_only) transfer_M6(); }
            count_only = false;
            bool rptg = method == "M6" || method == "M7" || method == "M8";
            online_scans = prm.adaptive_scan && (method == "M4" || method == "M5" || rptg);
            n_online_scans = 0;
            if ((method == "M4" || method == "M5" || rptg) && !tiny) build_edge_scans();
            st.transfer_work += edge_scan_work;
            if (n_edge_scans) { std::ostringstream o; o << "EDGESCAN(" << n_edge_scans << ";" << edge_scan_work << ")|"; st.ops += o.str(); }
            auto t2 = std::chrono::steady_clock::now();
            enum_cost = 0; enum_budget = UINT64_MAX;
            bool may_count = (method == "M7" || method == "M8" || method == "C0") && is_tree_pattern();
            bool count_now = count_first;
            if (may_count && !count_now) {                            // ski rental: enumerate until it costs as much as counting
                uint64_t C = count_cost(start);
                enum_budget = C;
                // M7 and M8: pure ski rental from here (a wrong enumeration estimate must not buy patience)
            }
            try {
                if (count_now) throw SwitchToCount{};
                st.count = join(start);
            } catch (SwitchToCount&) {
                std::ostringstream o; o << "COUNT(" << enum_budget << ")|"; st.ops += o.str();
                st.count = count_tree(start);
            }
            enum_budget = UINT64_MAX;
            auto t3 = std::chrono::steady_clock::now();
            if (n_online_scans) { std::ostringstream o; o << "ONLINESCAN(" << n_online_scans << ")|"; st.ops += o.str(); }
            st.transfer_ms = std::chrono::duration<double, std::milli>(t2 - t1).count();
            st.join_ms = std::chrono::duration<double, std::milli>(t3 - t2).count();
            st.total_ms = std::chrono::duration<double, std::milli>(t3 - t0).count();
            // v25: unit-cost calibration from every completed run (any method): join ns per scanned entry and
            // transfer ns per entry; the count shortcut's entries (join_out) are not scanned and not counted here
            if (st.join_work > 0 && st.join_ms > 0.05) { cal_join_ms += st.join_ms; cal_join_work += (double)st.join_work; }
            if (st.transfer_work > 0 && st.transfer_ms > 0.05) { cal_tr_ms += st.transfer_ms; cal_tr_work += (double)st.transfer_work; }
        } catch (Timeout&) {
            st.timeout = true;
            st.total_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
        }
        return st;
    }
};
