// Dense bitmap over a vertex id space [0, n). Roaring can replace this later; the
// interface (test/set/clear/count/for_each/random word order) is all the engine needs.
#pragma once
#include <cstdint>
#include <cstring>
#include <vector>
#include <random>

struct Bitmap {
    std::vector<uint64_t> w;
    uint64_t n = 0;

    Bitmap() = default;
    explicit Bitmap(uint64_t n_, bool ones = false) { init(n_, ones); }
    void init(uint64_t n_, bool ones) {
        n = n_;
        w.assign((n + 63) / 64, ones ? ~0ULL : 0ULL);
        if (ones && (n & 63)) w.back() = (1ULL << (n & 63)) - 1;
    }
    size_t words() const { return w.size(); }
    inline bool test(uint64_t i) const { return (w[i >> 6] >> (i & 63)) & 1ULL; }
    inline void set(uint64_t i) { w[i >> 6] |= 1ULL << (i & 63); }
    inline void clear(uint64_t i) { w[i >> 6] &= ~(1ULL << (i & 63)); }
    uint64_t count() const {
        uint64_t c = 0;
        for (uint64_t x : w) c += __builtin_popcountll(x);
        return c;
    }
    void and_with(const Bitmap& o) { for (size_t i = 0; i < w.size(); i++) w[i] &= o.w[i]; }

    // ---- coarse-to-fine summary (v16, "cascade" membership tests) -------------------------------------
    // s1 has one bit per word of w (set if the word may be non-zero), s2 one bit per word of s1; lo/hi are the
    // smallest and largest member. A scan of a sorted adjacency list against this bitmap clamps the list to
    // [lo, hi] and jumps over runs of neighbours that fall into empty words (see Engine::scan_in). The summary
    // is a superset: bits cleared after build_summary() leave stale 1s, which only cost a test. Rebuilt by the
    // engine before a bitmap is used as the target of membership tests.
    std::vector<uint64_t> s1, s2;
    uint64_t lo = 0, hi = 0, nz_words = 0;
    bool sum_ok = false, use_skip = false;
    void build_summary(double sparse_frac = 0.25) {
        s1.assign((w.size() + 63) / 64, 0); s2.assign((s1.size() + 63) / 64, 0);
        lo = n; hi = 0; nz_words = 0;
        for (size_t i = 0; i < w.size(); i++) {
            if (!w[i]) continue;
            s1[i >> 6] |= 1ULL << (i & 63); s2[i >> 12] |= 1ULL << ((i >> 6) & 63); nz_words++;
            if (lo == n) lo = i * 64 + __builtin_ctzll(w[i]);
            hi = i * 64 + 63 - __builtin_clzll(w[i]);
        }
        sum_ok = true;
        use_skip = nz_words * 1.0 < sparse_frac * (double)w.size() || (lo < hi && (double)(hi - lo) < 0.5 * (double)n);
    }
    void invalidate() { sum_ok = false; use_skip = false; }
    static const uint64_t NONE = ~0ULL;
    // first word index >= wi whose s1 bit is set
    inline uint64_t next_word(uint64_t wi) const {
        if (wi >= w.size()) return NONE;
        uint64_t i1 = wi >> 6;
        uint64_t m = s1[i1] & (~0ULL << (wi & 63));
        if (m) return (i1 << 6) + __builtin_ctzll(m);
        uint64_t j = i1 + 1;
        if (j >= s1.size()) return NONE;
        uint64_t i2 = j >> 6;
        uint64_t m2 = s2[i2] & (~0ULL << (j & 63));
        while (!m2) { if (++i2 >= s2.size()) return NONE; m2 = s2[i2]; }
        j = (i2 << 6) + __builtin_ctzll(m2);
        return (j << 6) + __builtin_ctzll(s1[j]);
    }
    // visit all set bits in a word
    template <class F> static inline void for_each_in_word(uint64_t x, uint64_t base, F&& f) {
        while (x) { uint64_t t = x & -x; f(base + __builtin_ctzll(x)); x ^= t; }
    }
    template <class F> void for_each(F&& f) const {
        for (size_t i = 0; i < w.size(); i++) if (w[i]) for_each_in_word(w[i], uint64_t(i) * 64, f);
    }
};

// Pseudo-random permutation of word indices [0, W): i -> (i*A + C) mod P restricted to < W,
// with P = next power of two >= W and A odd. Each word is visited exactly once.
struct WordPerm {
    uint64_t W, P, A, C;
    WordPerm(uint64_t W_, uint64_t seed) : W(W_) {
        P = 1; while (P < W) P <<= 1;
        std::mt19937_64 g(seed);
        A = (g() | 1ULL) & (P - 1); if (A == 0) A = 1;
        C = g() & (P - 1);
    }
    // iterate over all i in [0,P), yielding word idx < W
    template <class F> void for_each(F&& f) const {
        for (uint64_t i = 0; i < P; i++) { uint64_t idx = (i * A + C) & (P - 1); if (idx < W) if (!f(idx)) return; }
    }
};
