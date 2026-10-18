// Host-facing API of the RPT-G transfer phase (the prototype's M6), for relational hosts that keep an
// adjacency index (CSR) next to their edge table.
//
//   Graph g;                         // n, m, out_off/out_nbr (forward CSR), in_off/in_nbr (reverse CSR)
//   g.finalize();                    // degree arrays
//   Query q;                         // k pattern vertices, q.edges = pattern edges a -> b (a's out-adjacency);
//                                    // q.preds[x] non-empty for every vertex that has a predicate
//   std::vector<Bitmap> init(q.k);   // init[x] = candidates of x after its predicate (empty = unconstrained)
//   Engine eng(g, Params{});
//   RunStats st = eng.reduce(q, init, start, order);   // order: (bound vertex, edge index) per join step
//   eng.S[x].B, eng.S[x].cnt         // reduced candidate sets; eng.S[x].full = never reduced
//   st.ops                           // decision log (PUSH-A / PULL-B / SKIP-budget / ...)
//
// Guarantees (paper, Section 4.6): every true candidate stays in S[x].B whatever the decisions were, so a
// host may apply S[x].B as a row filter on every scan of x without changing the query result.
#pragma once
#include "engine.h"
