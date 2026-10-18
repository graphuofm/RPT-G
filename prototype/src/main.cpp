// CLI: run a query file against a graph with the selected methods, write one CSV row per (query, method, rep).
// Query line format:
//   id=17 k=4 edges=0>1,1>2,1>3 preds=0:pu<0.001;2:label=15;3:pd<0.01
#include "engine.h"
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>

static std::vector<std::string> split(const std::string& s, char c) {
    std::vector<std::string> out; std::string cur; std::istringstream is(s);
    while (std::getline(is, cur, c)) if (!cur.empty()) out.push_back(cur);
    return out;
}

static bool parse_query(const std::string& line, Query& q) {
    std::map<std::string, std::string> kv;
    for (const std::string& tok : split(line, ' ')) {
        size_t p = tok.find('='); if (p == std::string::npos) return false;
        kv[tok.substr(0, p)] = tok.substr(p + 1);
    }
    if (!kv.count("id") || !kv.count("k") || !kv.count("edges")) return false;
    q.id = std::stoi(kv["id"]); q.k = std::stoi(kv["k"]); q.text = line;
    q.edges.clear(); q.preds.assign(q.k, {});
    for (const std::string& e : split(kv["edges"], ',')) {
        size_t p = e.find('>'); if (p == std::string::npos) return false;
        q.edges.push_back({std::stoi(e.substr(0, p)), std::stoi(e.substr(p + 1))});
    }
    if (kv.count("preds")) for (const std::string& pr : split(kv["preds"], ';')) {
        size_t p = pr.find(':'); if (p == std::string::npos) return false;
        int x = std::stoi(pr.substr(0, p)); std::string body = pr.substr(p + 1);
        Pred pd{0, 0.0, 0};
        if (body.rfind("pu<", 0) == 0) { pd.type = 0; pd.val = std::stod(body.substr(3)); }
        else if (body.rfind("pd<", 0) == 0) { pd.type = 1; pd.val = std::stod(body.substr(3)); }
        else if (body.rfind("label=", 0) == 0) { pd.type = 2; pd.lab = std::stoi(body.substr(6)); }
        else return false;
        q.preds[x].push_back(pd);
    }
    return (int)q.edges.size() >= q.k - 1 && (int)q.edges.size() <= q.k + 6;   // trees and cyclic patterns
}

int main(int argc, char** argv) {
    std::string graph_dir, query_file, out_file = "-", methods = "M0,M3,M4,M6";
    double timeout = 10; int reps = 3, warm = 1, order_mode = 0; uint64_t order_seed = 0; int n_orders = 1;
    Params prm; bool no_prune = false; bool warm_each = false;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto next = [&]() { return std::string(argv[++i]); };
        if (a == "--graph") graph_dir = next();
        else if (a == "--queries") query_file = next();
        else if (a == "--out") out_file = next();
        else if (a == "--methods") methods = next();
        else if (a == "--timeout") timeout = std::stod(next());
        else if (a == "--reps") reps = std::stoi(next());
        else if (a == "--warm") warm = std::stoi(next());
        else if (a == "--random-orders") { order_mode = 1; n_orders = std::stoi(next()); }
        else if (a == "--order-seed") order_seed = std::stoull(next());
        else if (a == "--order") { std::string o = next(); order_mode = o == "est" ? 2 : o == "exact" ? 0 : -1;
                                    if (order_mode < 0) { fprintf(stderr, "--order exact|est\n"); return 1; } }
        else if (a == "--est-sel") prm.est_sel = std::stod(next());
        else if (a == "--tau-dense") prm.tau_dense = std::stod(next());
        else if (a == "--tau-bound") prm.tau_bound = std::stod(next());
        else if (a == "--tau-sel") prm.tau_sel = std::stod(next());
        else if (a == "--tau-prog") prm.tau_prog = std::stod(next());
        else if (a == "--gamma") prm.gamma = std::stoull(next());
        else if (a == "--seed") prm.seed = std::stoull(next());
        else if (a == "--est-sample") prm.est_sample = std::stoull(next());
        else if (a == "--no-prune") no_prune = true;
        else if (a == "--beta") { std::string v = next(); prm.beta = v == "auto" ? -1.0 : std::stod(v); }
        else if (a == "--beta-count") prm.beta_count = std::stod(next());
        else if (a == "--beta-default") prm.beta_default = std::stod(next());
        else if (a == "--no-count-shortcut") prm.count_shortcut = false;
        else if (a == "--edge-scan") prm.edge_scan = std::stoi(next()) != 0;
        else if (a == "--scan-beta") prm.scan_beta = std::stod(next());
        else if (a == "--adaptive-scan") prm.adaptive_scan = std::stoi(next()) != 0;
        else if (a == "--col-index") prm.col_index = std::stoi(next()) != 0;
        else if (a == "--count-far") prm.count_far = std::stod(next());
        else if (a == "--count-patience") prm.count_patience = std::stod(next());
        else if (a == "--min-work") prm.min_work = std::stod(next());
        else if (a == "--word-cost") prm.word_cost = std::stod(next());
        else if (a == "--extrapolate") prm.extrapolate = std::stoi(next()) != 0;
        else if (a == "--count-unit") prm.count_unit = std::stod(next());
        else if (a == "--cascade") prm.cascade = std::stoi(next()) != 0;
        else if (a == "--warm-each") warm_each = std::stoi(next()) != 0;   // v18c: every measured run is preceded by a run of the same method
        else if (a == "--sparse-frac") prm.sparse_frac = std::stod(next());
        else if (a == "--skip-unit") prm.skip_unit = std::stod(next());
        else if (a == "--push-abort") prm.push_abort = std::stoi(next()) != 0;
        else if (a == "--reach-pilot") prm.reach_pilot = std::stoi(next()) != 0;
        else if (a == "--pilot-min") prm.pilot_min = std::stod(next());
        else if (a == "--sibling-order") prm.sibling_order = std::stoi(next());
        else if (a == "--deg-surv") prm.deg_surv = std::stoi(next()) != 0;
        else if (a == "--count-benefit") prm.count_benefit = std::stoi(next()) != 0;
        else if (a == "--est-mode") prm.est_mode = std::stoi(next());
        else if (a == "--surv-deg") prm.surv_deg = std::stoi(next()) != 0;
        else { fprintf(stderr, "unknown arg %s\n", a.c_str()); return 1; }
    }
    if (graph_dir.empty() || query_file.empty()) { fprintf(stderr, "usage: rptg --graph DIR --queries FILE [--out CSV] [--methods M0,M3,M4,M5,M6] [--order exact|est] [--timeout S] [--reps N] [--warm N] [--random-orders N --order-seed S]\n"); return 1; }

    Graph g; g.load(graph_dir);
    if (prm.col_index) g.build_column_indexes();   // once per graph, like the adjacency index (not in query times)
    fprintf(stderr, "graph: n=%lu m=%lu directed=%d\n", g.n, g.m, (int)g.directed);
    std::vector<Query> qs; std::ifstream in(query_file); std::string line;
    while (std::getline(in, line)) { if (line.empty() || line[0] == '#') continue; Query q; if (!parse_query(line, q)) { fprintf(stderr, "bad query: %s\n", line.c_str()); return 1; } qs.push_back(q); }
    fprintf(stderr, "queries: %zu\n", qs.size());

    FILE* out = out_file == "-" ? stdout : fopen(out_file.c_str(), "w");
    fprintf(out, "qid,method,order,rep,status,total_ms,transfer_ms,join_ms,count,n_push,n_pull,n_skip,n_abort,transfer_work,join_work,init_ms,ops,join_out\n");
    Engine eng(g, prm); eng.prune_useless = !no_prune;
    std::vector<std::string> ms = split(methods, ',');
    size_t done = 0;
    for (const Query& q : qs) {
        for (int oi = 0; oi < n_orders; oi++) {
            uint64_t oseed = order_seed * 1000003ULL + (uint64_t)q.id * 7919ULL + oi;
            // rep-major, method-minor: each measured rep runs all methods back to back so that
            // machine-load fluctuations hit every method alike
            std::vector<bool> dead(ms.size(), false);
            for (int r = -warm; r < reps; r++) {
                for (size_t mi = 0; mi < ms.size(); mi++) {
                    if (dead[mi]) continue;
                    RunStats s = eng.run(q, ms[mi], timeout, order_mode, oseed);
                    // v18b: a run below 1 ms is repeated and the second run kept, so that allocator and cache
                    // state left by the previous method (e.g. M4's large bitmaps) does not land on the next
                    // method's timing at the 10-us scale; the extra run is negligible in total time
                    if (!s.timeout && (warm_each || s.total_ms < 1.0)) s = eng.run(q, ms[mi], timeout, order_mode, oseed);
                    if (r < 0 && !s.timeout) continue;          // warm-up run, not recorded (unless it timed out)
                    fprintf(out, "%d,%s,%d,%d,%s,%.4f,%.4f,%.4f,%lu,%d,%d,%d,%d,%lu,%lu,%.4f,%s,%lu\n", q.id, ms[mi].c_str(), oi, r < 0 ? 0 : r,
                            s.timeout ? "timeout" : "ok", s.total_ms, s.transfer_ms, s.join_ms, s.count,
                            s.n_push, s.n_pull, s.n_skip, s.n_abort, s.transfer_work, s.join_work, s.init_ms, s.ops.c_str(), s.join_out);
                    if (s.timeout) dead[mi] = true;
                }
            }
        }
        if (++done % 50 == 0) { fprintf(stderr, "\r%zu/%zu", done, qs.size()); fflush(out); }
    }
    fprintf(stderr, "\r%zu/%zu done\n", done, qs.size());
    if (out != stdout) fclose(out);
    return 0;
}
