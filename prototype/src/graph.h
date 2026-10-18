#pragma once
#include <algorithm>
#include <cstdint>
#include <functional>
#include <cstdio>
#include <string>
#include <vector>
#include <stdexcept>

struct Graph {
    uint64_t n = 0, m = 0;
    bool directed = true;
    std::vector<uint64_t> out_off, in_off;
    std::vector<uint32_t> out_nbr, in_nbr;
    std::vector<float> pu, pd;
    std::vector<int32_t> label;
    std::vector<uint32_t> dout, din;   // compact degree arrays (sequential-friendly for accumulator passes)
    double M[3] = {0, 0, 0};           // degree moments over all vertices: sum dout^2, sum din^2, sum dout*din
    // Upper bounds for sets of a given size: topD[dir][i] / topM[dir][i] = sum of the 2^i largest degrees /
    // squared degrees in direction dir (a set of size s <= 2^i can have no larger degree sum or moment).
    std::vector<double> topD[2], topM[2];
    // v19: degree histograms in log2 bins, per direction: count and degree sum of the vertices whose degree
    // lies in [2^b, 2^(b+1)); the degree-weighted survival of a transfer is computed from them
    double hist_cnt[2][32] = {}, hist_deg[2][32] = {};
    static inline int deg_bin(uint64_t d) { return d == 0 ? 0 : 63 - __builtin_clzll(d); }
    std::vector<uint32_t> sdeg[2];     // v24: degrees sorted descending per direction (top-k slices for pd sets)
    void moments() {
        for (int d = 0; d < 2; d++) { sdeg[d] = d == 0 ? dout : din; std::sort(sdeg[d].begin(), sdeg[d].end(), std::greater<uint32_t>()); }
        for (int d = 0; d < 2; d++) for (int b = 0; b < 32; b++) hist_cnt[d][b] = hist_deg[d][b] = 0;
        for (uint64_t v = 0; v < n; v++) {
            int bo = deg_bin(dout[v]), bi = deg_bin(din[v]);
            hist_cnt[0][bo] += 1; hist_deg[0][bo] += dout[v]; hist_cnt[1][bi] += 1; hist_deg[1][bi] += din[v];
        }
        M[0] = M[1] = M[2] = 0;
        for (uint64_t v = 0; v < n; v++) { double o = dout[v], i = din[v]; M[0] += o * o; M[1] += i * i; M[2] += o * i; }
        for (int d = 0; d < 2; d++) {
            std::vector<uint32_t> deg(d == 0 ? dout : din);
            std::sort(deg.begin(), deg.end(), std::greater<uint32_t>());
            topD[d].clear(); topM[d].clear();
            double sd = 0, sm = 0; uint64_t next = 1;
            for (uint64_t j = 0; j < n; j++) {
                sd += deg[j]; sm += double(deg[j]) * deg[j];
                if (j + 1 == next || j + 1 == n) { topD[d].push_back(sd); topM[d].push_back(sm); next <<= 1; }
            }
        }
    }
    // Predicate column indexes (v10): each property sorted by value, with the vertex of every position and
    // prefix sums of dout, din, dout^2, din^2, dout*din. A range or equality predicate is a contiguous run of
    // positions: its size and degree statistics are differences of prefix sums, and its bitmap costs one bit
    // per member instead of a scan of the column. Built once per graph, like the adjacency index.
    struct ColIdx { std::vector<double> val; std::vector<uint32_t> id; std::vector<double> pre; };   // pre: (n+1)*5
    ColIdx ix_pu, ix_pd, ix_label;
    template <class T> void build_colidx(const std::vector<T>& col, ColIdx& ix) {
        std::vector<uint32_t> ord(n);
        for (uint64_t v = 0; v < n; v++) ord[v] = (uint32_t)v;
        std::stable_sort(ord.begin(), ord.end(), [&](uint32_t a, uint32_t b) { return col[a] < col[b]; });
        ix.val.resize(n); ix.id = ord; ix.pre.assign((n + 1) * 5, 0.0);
        for (uint64_t i = 0; i < n; i++) {
            uint32_t v = ord[i]; ix.val[i] = (double)col[v];
            double o = dout[v], in = din[v];
            const double add[5] = {o, in, o * o, in * in, o * in};
            for (int j = 0; j < 5; j++) ix.pre[(i + 1) * 5 + j] = ix.pre[i * 5 + j] + add[j];
        }
    }
    void build_column_indexes() {
        if (!pu.empty()) build_colidx(pu, ix_pu);
        if (!pd.empty()) build_colidx(pd, ix_pd);
        if (!label.empty()) build_colidx(label, ix_label);
    }
    // largest possible degree sum / squared-degree sum of a set of s vertices (rounded up to a power of two)
    double top_deg(int d, double s) const { return top_at(topD[d], s); }
    double top_deg2(int d, double s) const { return top_at(topM[d], s); }
    static double top_at(const std::vector<double>& t, double s) {
        if (t.empty() || s <= 0) return 0.0;
        size_t i = 0; double p = 1;
        while (p < s && i + 1 < t.size()) { p *= 2; i++; }
        return t[i];
    }

    template <class T> static std::vector<T> read_bin(const std::string& path) {
        FILE* f = fopen(path.c_str(), "rb");
        if (!f) throw std::runtime_error("cannot open " + path);
        fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
        std::vector<T> v(sz / sizeof(T));
        if (fread(v.data(), 1, sz, f) != (size_t)sz) throw std::runtime_error("short read " + path);
        fclose(f);
        return v;
    }
    void load(const std::string& dir) {
        FILE* f = fopen((dir + "/meta.txt").c_str(), "r");
        if (!f) throw std::runtime_error("cannot open meta.txt in " + dir);
        int d; if (fscanf(f, "%lu %lu %d", &n, &m, &d) != 3) throw std::runtime_error("bad meta");
        fclose(f); directed = d != 0;
        out_off = read_bin<uint64_t>(dir + "/out_off.bin");
        out_nbr = read_bin<uint32_t>(dir + "/out_nbr.bin");
        in_off  = read_bin<uint64_t>(dir + "/in_off.bin");
        in_nbr  = read_bin<uint32_t>(dir + "/in_nbr.bin");
        pu = read_bin<float>(dir + "/pu.bin");
        pd = read_bin<float>(dir + "/pd.bin");
        label = read_bin<int32_t>(dir + "/label.bin");
        dout.resize(n); din.resize(n);
        for (uint64_t v = 0; v < n; v++) { dout[v] = out_off[v + 1] - out_off[v]; din[v] = in_off[v + 1] - in_off[v]; }
        moments();
    }
    // For hosts that fill n, m, out_off/out_nbr, in_off/in_nbr themselves (rptg_api.h): derive the degree arrays.
    void finalize() {
        dout.resize(n); din.resize(n);
        for (uint64_t v = 0; v < n; v++) { dout[v] = out_off[v + 1] - out_off[v]; din[v] = in_off[v + 1] - in_off[v]; }
        moments();
    }
    inline uint64_t outdeg(uint64_t v) const { return out_off[v + 1] - out_off[v]; }
    inline uint64_t indeg(uint64_t v) const { return in_off[v + 1] - in_off[v]; }
    // adjacency in direction dir: 0 = forward (out), 1 = reverse (in)
    inline const uint32_t* adj_begin(uint64_t v, int dir) const { return dir == 0 ? &out_nbr[out_off[v]] : &in_nbr[in_off[v]]; }
    inline const uint32_t* adj_end(uint64_t v, int dir) const { return dir == 0 ? &out_nbr[out_off[v + 1]] : &in_nbr[in_off[v + 1]]; }
    inline uint64_t deg(uint64_t v, int dir) const { return dir == 0 ? outdeg(v) : indeg(v); }
};
