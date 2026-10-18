// Checks that Engine::reduce (host API) makes the same decisions and produces the same candidate-set sizes
// as the prototype's own M6 run, on the DBLP smoke-test queries.
#include "../src/rptg_api.h"
#include <fstream>
#include <iostream>
#include <sstream>
#include <map>
static std::vector<std::string> split(const std::string& s, char c) { std::vector<std::string> o; std::string t; std::istringstream is(s); while (std::getline(is, t, c)) if (!t.empty()) o.push_back(t); return o; }
int main(int argc, char** argv) {
    Graph g; g.load(argv[1]);
    std::ifstream in(argv[2]); std::string line; int bad = 0, n = 0;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') continue;
        Query q; std::map<std::string, std::string> kv;
        for (auto& t : split(line, ' ')) { auto p = t.find('='); kv[t.substr(0, p)] = t.substr(p + 1); }
        q.id = std::stoi(kv["id"]); q.k = std::stoi(kv["k"]); q.preds.assign(q.k, {});
        for (auto& e : split(kv["edges"], ',')) { auto p = e.find('>'); q.edges.push_back({std::stoi(e.substr(0, p)), std::stoi(e.substr(p + 1))}); }
        if (kv.count("preds")) for (auto& pr : split(kv["preds"], ';')) {
            auto p = pr.find(':'); int x = std::stoi(pr.substr(0, p)); std::string b = pr.substr(p + 1); Pred pd{0, 0, 0};
            if (b.rfind("pu<", 0) == 0) { pd.type = 0; pd.val = std::stod(b.substr(3)); }
            else if (b.rfind("pd<", 0) == 0) { pd.type = 1; pd.val = std::stod(b.substr(3)); }
            else { pd.type = 2; pd.lab = std::stoi(b.substr(6)); }
            q.preds[x].push_back(pd);
        }
        Engine ref(g, Params{}); ref.run(q, "M6", 60);
        std::vector<uint64_t> want; for (auto& s : ref.S) want.push_back(s.cnt);
        // host side: evaluate predicates itself, take the same join order
        Engine eng(g, Params{});
        std::vector<Bitmap> init(q.k);
        for (int x = 0; x < q.k; x++) if (!q.preds[x].empty()) {
            init[x].init(g.n, false);
            for (uint64_t v = 0; v < g.n; v++) { bool ok = true; for (auto& p : q.preds[x]) { ok = p.type == 0 ? (double)g.pu[v] < p.val : p.type == 1 ? (double)g.pd[v] < p.val : g.label[v] == p.lab; if (!ok) break; } if (ok) init[x].set(v); }
        }
        std::vector<std::pair<int, int>> order; for (auto& s : ref.steps) order.push_back({s.bound, s.edge});
        eng.reduce(q, init, ref.join_start, order);
        n++;
        for (int x = 0; x < q.k; x++) if (eng.S[x].cnt != want[x]) { bad++; std::cout << "q" << q.id << " x" << x << " api " << eng.S[x].cnt << " ref " << want[x] << "\n"; }
    }
    std::cout << n << " queries, " << bad << " mismatching candidate sets\n";
    return bad != 0;
}
