/*
 * pg_rptg: RPT-G robust predicate transfer for graph pattern queries in PostgreSQL 19.
 *
 * The host keeps its plan: join order, join methods and scans are those of standard_planner. pg_rptg
 *   1. (planner_hook) recognizes a pattern query -- an inner self-join over copies of an edge table
 *      E(src, dst) and a vertex table V(id, ...) whose WHERE clause is a conjunction of column
 *      equalities between E.src / E.dst / V.id and predicates on single V copies -- and appends a filter
 *      rptg_member(execid, vertex, column) to every scan of an E or V copy of the final plan; the
 *      host's join order is read off the plan (leaf order of the E scans);
 *   2. (ExecutorStart_hook) builds the adjacency index of E once per backend, evaluates the predicates
 *      of every pattern vertex with SPI, runs the RPT-G transfer phase (the prototype's Engine through
 *      rptg_c.h) under the host's join order, and keeps only the filters of vertices whose candidate set
 *      was reduced; a query in which nothing is reduced runs the unmodified plan;
 *   3. rptg_member tests a candidate bitmap. Parallel workers read the bitmaps from a file in /dev/shm
 *      written by the leader before any worker starts.
 * Correctness does not depend on any decision: every bitmap is a superset of the vertices that occur
 * in a match (paper, Lemma "safe skipping and aborting").
 *
 * GUCs: rptg.enabled (off), rptg.beta (10), rptg.pred_cost (160), rptg.edge_table (e), rptg.vertex_table (v), rptg.debug (off).
 */
#include "postgres.h"

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include "access/parallel.h"
#include "catalog/namespace.h"
#include "catalog/pg_class.h"
#include "catalog/pg_type.h"
#include "executor/executor.h"
#include "executor/spi.h"
#include "fmgr.h"
#include "miscadmin.h"
#include "nodes/makefuncs.h"
#include "nodes/nodeFuncs.h"
#include "nodes/plannodes.h"
#include "nodes/value.h"
#include "optimizer/optimizer.h"
#include "optimizer/planner.h"
#include "parser/parse_func.h"
#include "port/pg_bitutils.h"
#include "portability/instr_time.h"
#include "rewrite/rewriteManip.h"
#include "storage/procnumber.h"
#include "utils/builtins.h"
#include "utils/guc.h"
#include "utils/lsyscache.h"
#include "utils/memutils.h"
#include "utils/ruleutils.h"
#include "utils/numeric.h"
#include "utils/fmgroids.h"
#include <math.h>

#include "rptg_c.h"

PG_MODULE_MAGIC;

#define RPTG_MAXV 32
#define RPTG_MAXE 64
#define RPTG_MAXRT 128

static bool rptg_enabled = false;
static double rptg_beta = 10.0;
static double rptg_pred_cost = 160.0;
static double rptg_filter_cost = 3.0;
static int	rptg_exact_rows = 20000;
static bool rptg_column_index = true;
static bool rptg_trace = false;
static double rptg_index_pred_cost = 2.0;
static double rptg_first_cost = 150000.0;
static char *rptg_edge_table = NULL;
static char *rptg_vertex_table = NULL;
static bool rptg_debug = false;
static bool rptg_count_on = true;	/* answer a bare count(*) over a tree pattern by the counting join */
static double rptg_count_host = 8.0;	/* ... when its cost <= this factor x the engine's enumeration estimate */
static double rptg_count_floor = 2e6;	/* ... or when its cost is below this many entries (E can be far too low) */

static planner_hook_type prev_planner = NULL;
static create_upper_paths_hook_type prev_upper_paths = NULL;
static Query *capture_parse = NULL;	/* the pattern query being planned */
static double captured_rows[RPTG_MAXRT];	/* its base relations' estimated rows after restrictions */
static ExecutorStart_hook_type prev_ExecutorStart = NULL;
static bool in_rptg = false;			/* our own SPI queries must not be rewritten */

/* ------------------------------------------------------------------ recognized patterns */
typedef struct RptgPattern
{
	int			id;
	Oid			erel, vrel;
	int			k, ne;
	int			ea[RPTG_MAXE], eb[RPTG_MAXE];
	char	   *pred_sql[RPTG_MAXV];	/* WHERE clause over V for vertex x, NULL = no predicate */
	/* the same predicate as a range lo < col < hi on one numeric column of V (pred_att = 0: not of that form) */
	AttrNumber	pred_att[RPTG_MAXV];
	double		pred_lo[RPTG_MAXV], pred_hi[RPTG_MAXV];
	bool		pred_lo_incl[RPTG_MAXV], pred_hi_incl[RPTG_MAXV];
	int			start, nsteps;
	int			step_bound[RPTG_MAXE], step_edge[RPTG_MAXE];
	int			rt_mask[RPTG_MAXRT];	/* classes of the columns of each range-table entry */
	double		est_rows[RPTG_MAXV];	/* host estimate of each predicate's rows (-1: none) */
	uint32		needed;			/* predicates whose information the admitted transfers carry */
	int			admitted;		/* transfers the plan-time pre-screen admitted */
	/* the host's join tree (joins, E and V scans) for the benefit model */
	int			nplan, plan_root;
	int			plan_left[2 * RPTG_MAXRT], plan_right[2 * RPTG_MAXRT], plan_edge[2 * RPTG_MAXRT], plan_vertex[2 * RPTG_MAXRT];
	int			plan_param[2 * RPTG_MAXRT];
} RptgPattern;

#define RPTG_KEEP 64
static RptgPattern *patterns[RPTG_KEEP];	/* ring buffer of recent plans, in TopMemoryContext */
static int	next_pattern_id = 1;

/* ------------------------------------------------------------------ the adjacency index */
static rptg_graph *graph = NULL;
static Oid	graph_rel = InvalidOid;
static double graph_build_ms = 0;

/* ------------------------------------------------------------------ published bitmaps */
typedef struct RptgExec
{
	int			execid;
	int			k;
	uint64		words;
	const uint64 *bits[RPTG_MAXV];	/* NULL = no filter for this vertex */
	rptg_reduction *red;		/* leader: owns the words */
	uint64	   *zero;			/* leader: the empty set, when a candidate set came out empty */
	void	   *map;			/* worker: mmap of the leader's file */
	size_t		maplen;
	char		path[MAXPGPATH];
} RptgExec;

static RptgExec *cur_exec = NULL;	/* the execution rptg_member reads (leader or worker) */
static int	next_exec_id = 1;
static Oid	member_oid = InvalidOid;

PG_FUNCTION_INFO_V1(rptg_member);

static void
exec_path(char *buf, ProcNumber leader, int execid)
{
	snprintf(buf, MAXPGPATH, "/dev/shm/pg_rptg.%d.%d.%d", (int) PostmasterPid, (int) leader, execid);
}

static void
exec_release(void *arg)
{
	RptgExec   *e = (RptgExec *) arg;

	if (cur_exec == e)
		cur_exec = NULL;
	if (e->red)
		rptg_reduction_free(e->red);
	if (e->zero)
		free(e->zero);
	if (e->map)
		munmap(e->map, e->maplen);
	if (e->path[0] && !IsParallelWorker())
		unlink(e->path);
	free(e);
}

/* worker side: map the leader's file for this execution */
static RptgExec *
exec_attach(int execid)
{
	RptgExec   *e = (RptgExec *) calloc(1, sizeof(RptgExec));
	int			fd;
	struct stat st;
	uint64	   *hdr;

	e->execid = execid;
	exec_path(e->path, ParallelLeaderProcNumber, execid);
	fd = open(e->path, O_RDONLY);
	if (fd < 0)
	{
		/* nothing published for this id (e.g. the plan outlived its pattern record): no filtering */
		e->path[0] = 0;
		return e;
	}
	if (fstat(fd, &st) < 0)
		elog(ERROR, "pg_rptg: cannot stat %s: %m", e->path);
	e->maplen = st.st_size;
	e->map = mmap(NULL, e->maplen, PROT_READ, MAP_SHARED, fd, 0);
	close(fd);
	if (e->map == MAP_FAILED)
		elog(ERROR, "pg_rptg: cannot map %s: %m", e->path);
	hdr = (uint64 *) e->map;	/* k, words, then k offsets (in words, 0 = no filter), then the words */
	e->k = (int) hdr[0];
	e->words = hdr[1];
	for (int x = 0; x < e->k; x++)
		e->bits[x] = hdr[2 + x] ? hdr + hdr[2 + x] : NULL;
	return e;
}

Datum
rptg_member(PG_FUNCTION_ARGS)
{
	int32		execid = PG_GETARG_INT32(0);
	int32		x = PG_GETARG_INT32(1);
	uint32		v = (uint32) PG_GETARG_INT32(2);
	const uint64 *w;

	if (cur_exec == NULL || cur_exec->execid != execid)
	{
		if (!IsParallelWorker())
			PG_RETURN_BOOL(true);	/* not published (e.g. EXPLAIN): no filtering */
		if (cur_exec)
			exec_release(cur_exec);
		cur_exec = exec_attach(execid);
	}
	if (x < 0 || x >= cur_exec->k || (w = cur_exec->bits[x]) == NULL)
		PG_RETURN_BOOL(true);
	if ((uint64) v >= cur_exec->words * 64)
		PG_RETURN_BOOL(false);
	PG_RETURN_BOOL((w[v >> 6] >> (v & 63)) & 1);
}

/* ------------------------------------------------------------------ recognition (plan time) */
typedef struct UF
{
	int			p[3 * RPTG_MAXRT];
} UF;

static int
uf_find(UF *u, int a)
{
	while (u->p[a] != a)
		a = u->p[a] = u->p[u->p[a]];
	return a;
}

static void
flatten_and(Node *n, List **out)
{
	if (n == NULL)
		return;
	if (IsA(n, BoolExpr) && ((BoolExpr *) n)->boolop == AND_EXPR)
	{
		ListCell   *lc;

		foreach(lc, ((BoolExpr *) n)->args)
			flatten_and(lfirst(lc), out);
	}
	else if (IsA(n, List))
	{
		ListCell   *lc;

		foreach(lc, (List *) n)
			flatten_and(lfirst(lc), out);
	}
	else
		*out = lappend(*out, n);
}

static bool
collect_from(Node *n, List **conj)
{
	if (IsA(n, RangeTblRef))
		return true;
	if (IsA(n, JoinExpr))
	{
		JoinExpr   *j = (JoinExpr *) n;

		if (j->jointype != JOIN_INNER || j->usingClause != NIL || j->isNatural)
			return false;
		flatten_and(j->quals, conj);
		return collect_from(j->larg, conj) && collect_from(j->rarg, conj);
	}
	return false;
}

typedef struct VarnoCtx
{
	Bitmapset  *varnos;
	bool		bad;
} VarnoCtx;

static bool
varno_walker(Node *n, VarnoCtx *c)
{
	if (n == NULL)
		return false;
	if (IsA(n, Var))
	{
		Var		   *v = (Var *) n;

		if (v->varlevelsup != 0)
			c->bad = true;
		else
			c->varnos = bms_add_member(c->varnos, v->varno);
		return false;
	}
	if (IsA(n, SubLink) || IsA(n, Param) || IsA(n, Aggref) || IsA(n, WindowFunc))
	{
		c->bad = true;
		return false;
	}
	return expression_tree_walker(n, varno_walker, c);
}

/* column node ids: E copy rti -> 3*rti (src), 3*rti+1 (dst); V copy rti -> 3*rti+2 (id) */
/* A predicate qual "col op const" (or "const op col") on vertex copy rti, with op one of < <= = >= > and a
 * numeric constant, narrows the range of vertex x's predicate; any other qual, or quals on two columns,
 * make the predicate unstructured (pred_att = -1). */
static bool
qual_range(Node *q, int rti, Oid vrel, RptgPattern *pat, int x)
{
	OpExpr	   *op;
	Node	   *l, *r;
	Var		   *v;
	Const	   *c;
	char	   *name;
	bool		flip = false;
	double		val;

	if (pat->pred_att[x] < 0 || !IsA(q, OpExpr) || list_length(((OpExpr *) q)->args) != 2)
		return false;
	/* fold the parser's casts of literals (numeric -> float8) into constants */
	q = eval_const_expressions(NULL, (Node *) copyObject(q));
	if (!IsA(q, OpExpr) || list_length(((OpExpr *) q)->args) != 2)
		return false;
	op = (OpExpr *) q;
	l = linitial(op->args);
	r = lsecond(op->args);
	while (IsA(l, RelabelType))
		l = (Node *) ((RelabelType *) l)->arg;
	while (IsA(r, RelabelType))
		r = (Node *) ((RelabelType *) r)->arg;
	if (IsA(r, Var) && IsA(l, Const))
	{
		Node	   *t = l;

		l = r;
		r = t;
		flip = true;
	}
	if (!IsA(l, Var) || !IsA(r, Const) || ((Var *) l)->varno != rti || ((Const *) r)->constisnull)
		return false;
	v = (Var *) l;
	c = (Const *) r;
	switch (c->consttype)
	{
		case INT2OID: val = DatumGetInt16(c->constvalue); break;
		case INT4OID: val = DatumGetInt32(c->constvalue); break;
		case INT8OID: val = (double) DatumGetInt64(c->constvalue); break;
		case FLOAT4OID: val = DatumGetFloat4(c->constvalue); break;
		case FLOAT8OID: val = DatumGetFloat8(c->constvalue); break;
		case NUMERICOID: val = DatumGetFloat8(DirectFunctionCall1(numeric_float8, c->constvalue)); break;
		default: return false;
	}
	switch (get_atttype(vrel, v->varattno))
	{
		case INT2OID: case INT4OID: case INT8OID: case FLOAT4OID: case FLOAT8OID: break;
		default: return false;
	}
	if (pat->pred_att[x] != InvalidAttrNumber && pat->pred_att[x] != v->varattno)
		return false;
	name = get_opname(op->opno);
	if (name == NULL)
		return false;
	if (flip)
	{
		if (strcmp(name, "<") == 0) name = ">";
		else if (strcmp(name, "<=") == 0) name = ">=";
		else if (strcmp(name, ">") == 0) name = "<";
		else if (strcmp(name, ">=") == 0) name = "<=";
	}
	pat->pred_att[x] = v->varattno;
	if (strcmp(name, "<") == 0 || strcmp(name, "<=") == 0)
	{
		if (val < pat->pred_hi[x] || (val == pat->pred_hi[x] && name[1] == '\0'))
			pat->pred_hi[x] = val, pat->pred_hi_incl[x] = name[1] == '=';
	}
	else if (strcmp(name, ">") == 0 || strcmp(name, ">=") == 0)
	{
		if (val > pat->pred_lo[x] || (val == pat->pred_lo[x] && name[1] == '\0'))
			pat->pred_lo[x] = val, pat->pred_lo_incl[x] = name[1] == '=';
	}
	else if (strcmp(name, "=") == 0)
	{
		if (val > pat->pred_lo[x] || (val == pat->pred_lo[x] && !pat->pred_lo_incl[x]))
			pat->pred_lo[x] = val, pat->pred_lo_incl[x] = true;
		if (val < pat->pred_hi[x] || (val == pat->pred_hi[x] && !pat->pred_hi_incl[x]))
			pat->pred_hi[x] = val, pat->pred_hi_incl[x] = true;
	}
	else
		return false;
	return true;
}

static RptgPattern *
recognize(Query *parse, int *rt_kind, int *rt_node)
{
	Oid			erel, vrel;
	AttrNumber	a_src, a_dst, a_id;
	List	   *conj = NIL;
	ListCell   *lc;
	UF			uf;
	int			nrt = list_length(parse->rtable);
	List	   *preds[RPTG_MAXRT];
	int			cls_of_node[3 * RPTG_MAXRT];
	int			k = 0, ne = 0;
	RptgPattern pat;
	int			rti;

	if (parse->commandType != CMD_SELECT || parse->setOperations || parse->cteList ||
		parse->hasSubLinks || parse->hasWindowFuncs || parse->hasTargetSRFs ||
		nrt < 2 || nrt >= RPTG_MAXRT || parse->jointree == NULL)
		return NULL;
	erel = RelnameGetRelid(rptg_edge_table);
	vrel = RelnameGetRelid(rptg_vertex_table);
	if (!OidIsValid(erel))
		return NULL;
	a_src = get_attnum(erel, "src");
	a_dst = get_attnum(erel, "dst");
	a_id = OidIsValid(vrel) ? get_attnum(vrel, "id") : InvalidAttrNumber;

	memset(rt_kind, 0, sizeof(int) * RPTG_MAXRT);
	rti = 0;
	foreach(lc, parse->rtable)
	{
		RangeTblEntry *rte = lfirst(lc);

		rti++;
		preds[rti] = NIL;
		if (rte->rtekind == RTE_GROUP || rte->rtekind == RTE_JOIN)
			continue;
		if (rte->rtekind != RTE_RELATION || rte->relkind != RELKIND_RELATION)
			return NULL;
		if (rte->relid == erel)
			rt_kind[rti] = 1;
		else if (OidIsValid(vrel) && rte->relid == vrel)
			rt_kind[rti] = 2;
		else
			return NULL;
		preds[rti] = NIL;
	}
	/* comma joins and explicit inner JOINs; the ON conditions join the WHERE conjuncts */
	foreach(lc, parse->jointree->fromlist)
		if (!collect_from(lfirst(lc), &conj))
			return NULL;

	for (int i = 0; i < 3 * RPTG_MAXRT; i++)
		uf.p[i] = i;
	flatten_and(parse->jointree->quals, &conj);
	foreach(lc, conj)
	{
		Node	   *q = lfirst(lc);
		VarnoCtx	c = {NULL, false};

		if (IsA(q, OpExpr) && list_length(((OpExpr *) q)->args) == 2 &&
			IsA(linitial(((OpExpr *) q)->args), Var) && IsA(lsecond(((OpExpr *) q)->args), Var))
		{
			Var		   *l = linitial(((OpExpr *) q)->args), *r = lsecond(((OpExpr *) q)->args);
			char	   *op = get_opname(((OpExpr *) q)->opno);
			int			nl = -1, nr = -1;

			if (op && strcmp(op, "=") == 0 && l->varlevelsup == 0 && r->varlevelsup == 0 && l->varno != r->varno)
			{
				Var		   *vs[2] = {l, r};
				int		   *ns[2] = {&nl, &nr};

				for (int s = 0; s < 2; s++)
				{
					int			t = vs[s]->varno;

					if (t < 1 || t > nrt)
						return NULL;
					if (rt_kind[t] == 1 && vs[s]->varattno == a_src)
						*ns[s] = 3 * t;
					else if (rt_kind[t] == 1 && vs[s]->varattno == a_dst)
						*ns[s] = 3 * t + 1;
					else if (rt_kind[t] == 2 && vs[s]->varattno == a_id)
						*ns[s] = 3 * t + 2;
				}
				if (nl >= 0 && nr >= 0)
				{
					uf.p[uf_find(&uf, nl)] = uf_find(&uf, nr);
					continue;
				}
				return NULL;
			}
		}
		varno_walker(q, &c);
		if (c.bad || bms_num_members(c.varnos) != 1)
			return NULL;
		rti = bms_singleton_member(c.varnos);
		if (rt_kind[rti] != 2)
			return NULL;		/* a filter on an edge copy: not a pattern predicate */
		preds[rti] = lappend(preds[rti], q);
	}

	/* pattern vertices = classes of the columns of E copies; V copies must hang on one of them */
	for (int i = 0; i < 3 * RPTG_MAXRT; i++)
		cls_of_node[i] = -1;
	memset(&pat, 0, sizeof(pat));
	for (rti = 1; rti <= nrt; rti++)
	{
		if (rt_kind[rti] != 1)
			continue;
		for (int s = 0; s < 2; s++)
		{
			int			root = uf_find(&uf, 3 * rti + s);

			if (cls_of_node[root] < 0)
			{
				if (k == RPTG_MAXV)
					return NULL;
				cls_of_node[root] = k++;
			}
		}
		if (ne == RPTG_MAXE)
			return NULL;
		pat.ea[ne] = cls_of_node[uf_find(&uf, 3 * rti)];
		pat.eb[ne] = cls_of_node[uf_find(&uf, 3 * rti + 1)];
		if (pat.ea[ne] == pat.eb[ne])
			return NULL;		/* self loop */
		pat.rt_mask[rti] = (1 << pat.ea[ne]) | (1 << pat.eb[ne]);
		rt_node[rti] = ne++;
	}
	if (ne == 0)
		return NULL;
	for (rti = 1; rti <= nrt; rti++)
	{
		int			x;

		if (rt_kind[rti] != 2)
			continue;
		x = cls_of_node[uf_find(&uf, 3 * rti + 2)];
		if (x < 0)
			return NULL;
		rt_node[rti] = x;
		pat.rt_mask[rti] = 1 << x;
		if (preds[rti] != NIL)
		{
			List	   *ctx = deparse_context_for(get_rel_name(vrel), vrel);
			StringInfoData buf;

			initStringInfo(&buf);
			if (pat.pred_sql[x])
				appendStringInfo(&buf, "%s AND ", pat.pred_sql[x]);
			else
			{
				pat.pred_att[x] = InvalidAttrNumber;
				pat.pred_lo[x] = -INFINITY;
				pat.pred_hi[x] = INFINITY;
				pat.pred_lo_incl[x] = pat.pred_hi_incl[x] = false;
			}
			foreach(lc, preds[rti])
			{
				Node	   *e = copyObject((Node *) lfirst(lc));

				if (!qual_range((Node *) lfirst(lc), rti, vrel, &pat, x))
					pat.pred_att[x] = -1;	/* not a single-column range: evaluated through SPI */

				ChangeVarNodes(e, rti, 1, 0);
				appendStringInfo(&buf, "%s%s", lc == list_head(preds[rti]) ? "" : " AND ",
								 deparse_expression(e, ctx, false, false));
			}
			pat.pred_sql[x] = buf.data;
		}
	}
	/* the pattern must be connected */
	{
		int			comp[RPTG_MAXV], changed = 1;

		for (int x = 0; x < k; x++)
			comp[x] = x;
		while (changed)
		{
			changed = 0;
			for (int i = 0; i < ne; i++)
			{
				int			m = Min(comp[pat.ea[i]], comp[pat.eb[i]]);

				if (comp[pat.ea[i]] != m || comp[pat.eb[i]] != m)
					comp[pat.ea[i]] = comp[pat.eb[i]] = m, changed = 1;
			}
		}
		for (int x = 0; x < k; x++)
			if (comp[x] != 0)
				return NULL;
	}
	pat.erel = erel;
	pat.vrel = vrel;
	pat.k = k;
	pat.ne = ne;
	{
		RptgPattern *p = MemoryContextAlloc(TopMemoryContext, sizeof(RptgPattern));

		*p = pat;
		for (int x = 0; x < k; x++)
			if (pat.pred_sql[x])
				p->pred_sql[x] = MemoryContextStrdup(TopMemoryContext, pat.pred_sql[x]);
		return p;
	}
}

/* ------------------------------------------------------------------ plan decoration */
typedef struct PlanCtx
{
	int		   *rt_kind, *rt_node;
	RptgPattern *pat;
	int			leaf_edges[RPTG_MAXE], nleaf;
	int			first_vertex;
	AttrNumber	a_src, a_dst, a_id;
	int			nquals;
	bool		add;			/* false: only record the leaf order */
} PlanCtx;

static Var *
scan_var(Plan *plan, int scanrelid, AttrNumber attno)
{
	if (IsA(plan, IndexOnlyScan))
	{
		ListCell   *lc;

		foreach(lc, ((IndexOnlyScan *) plan)->indextlist)
		{
			TargetEntry *te = lfirst(lc);

			if (IsA(te->expr, Var) && ((Var *) te->expr)->varattno == attno)
				return makeVar(INDEX_VAR, te->resno, INT4OID, -1, InvalidOid, 0);
		}
		return NULL;
	}
	return makeVar(scanrelid, attno, INT4OID, -1, InvalidOid, 0);
}

static void
add_member_qual(Plan *plan, int scanrelid, AttrNumber attno, int x, int planid, PlanCtx *c)
{
	Var		   *v = scan_var(plan, scanrelid, attno);
	FuncExpr   *f;

	if (v == NULL)
		return;
	f = makeFuncExpr(member_oid, BOOLOID,
					 list_make3(makeConst(INT4OID, -1, InvalidOid, 4, Int32GetDatum(planid), false, true),
								makeConst(INT4OID, -1, InvalidOid, 4, Int32GetDatum(x), false, true),
								v),
					 InvalidOid, InvalidOid, COERCE_EXPLICIT_CALL);
	plan->qual = lappend(plan->qual, f);
	c->nquals++;
}

static void
decorate(Plan *plan, PlanCtx *c)
{
	if (plan == NULL)
		return;
	switch (nodeTag(plan))
	{
		case T_SeqScan:
		case T_IndexScan:
		case T_IndexOnlyScan:
		case T_BitmapHeapScan:
			{
				int			rti = ((Scan *) plan)->scanrelid;

				if (rti <= 0 || rti >= RPTG_MAXRT || c->rt_kind[rti] == 0)
					break;
				if (c->rt_kind[rti] == 1)
				{
					int			ei = c->rt_node[rti];

					if (!c->add)
						c->leaf_edges[c->nleaf++] = ei;
					else
					{
						add_member_qual(plan, rti, c->a_src, c->pat->ea[ei], c->pat->id, c);
						add_member_qual(plan, rti, c->a_dst, c->pat->eb[ei], c->pat->id, c);
					}
				}
				else if (!c->add)
				{
					if (c->first_vertex < 0 && c->nleaf == 0)
						c->first_vertex = c->rt_node[rti];
				}
				else
					add_member_qual(plan, rti, c->a_id, c->rt_node[rti], c->pat->id, c);
				break;
			}
		default:
			break;
	}
	/* execution order: a hash join builds its inner (Hash) side before the outer side streams through it */
	if (IsA(plan, HashJoin))
	{
		decorate(innerPlan(plan), c);
		decorate(outerPlan(plan), c);
	}
	else
	{
		decorate(outerPlan(plan), c);
		decorate(innerPlan(plan), c);
	}
}

static bool is_join(Plan *p);
static bool is_scan(Plan *p);

/* the host's join tree: joins keep their outer and inner inputs, scans of E and V copies are leaves,
 * single-input nodes (Hash, Sort, Gather, Memoize, ...) are transparent; returns the node or -1 */
static int
host_tree(Plan *p, PlanCtx *c)
{
	RptgPattern *pat = c->pat;
	int			l, r, n;

	if (p == NULL || pat->nplan >= 2 * RPTG_MAXRT)
		return -1;
	if (is_scan(p))
	{
		int			rti = ((Scan *) p)->scanrelid;

		if (rti <= 0 || rti >= RPTG_MAXRT || c->rt_kind[rti] == 0)
			return -1;
		n = pat->nplan++;
		pat->plan_left[n] = pat->plan_right[n] = -1;
		pat->plan_edge[n] = c->rt_kind[rti] == 1 ? c->rt_node[rti] : -1;
		pat->plan_vertex[n] = c->rt_kind[rti] == 2 ? c->rt_node[rti] : -1;
		pat->plan_param[n] = 0;
		return n;
	}
	l = host_tree(outerPlan(p), c);
	r = host_tree(innerPlan(p), c);
	if (l < 0 || r < 0 || !is_join(p))
		return l >= 0 ? l : r;
	/* the inner index scan of a nested loop looks its rows up per outer row: no rows of its own */
	if (IsA(p, NestLoop) && r >= 0 && pat->plan_left[r] < 0)
	{
		Plan	   *inner = innerPlan(p);

		while (inner && !is_scan(inner) && innerPlan(inner) == NULL && outerPlan(inner))
			inner = outerPlan(inner);
		if (inner && (IsA(inner, IndexScan) || IsA(inner, IndexOnlyScan) || IsA(inner, BitmapHeapScan)))
			pat->plan_param[r] = 1;
	}
	n = pat->nplan++;
	pat->plan_left[n] = l;
	pat->plan_right[n] = r;
	pat->plan_edge[n] = pat->plan_vertex[n] = -1;
	pat->plan_param[n] = 0;
	return n;
}

/* host join order from the leaf order of the E scans: start at the first scanned vertex, then bind
 * vertices edge by edge; an edge whose endpoints are both unbound waits until one of them is bound */
static void
host_order(PlanCtx *c)
{
	RptgPattern *p = c->pat;
	bool		bound[RPTG_MAXV] = {0}, used[RPTG_MAXE] = {0};
	int			progress = 1;

	if (c->first_vertex >= 0)
		p->start = c->first_vertex;
	else if (c->nleaf > 0)
		p->start = p->ea[c->leaf_edges[0]];
	else
		p->start = 0;
	bound[p->start] = true;
	p->nsteps = 0;
	while (progress)
	{
		progress = 0;
		for (int i = 0; i < c->nleaf; i++)
		{
			int			e = c->leaf_edges[i];

			if (used[e])
				continue;
			if (bound[p->ea[e]] && bound[p->eb[e]])
				used[e] = true, progress = 1;	/* closes a cycle: checked by the engine */
			else if (bound[p->ea[e]] || bound[p->eb[e]])
			{
				int			x = bound[p->ea[e]] ? p->ea[e] : p->eb[e];

				p->step_bound[p->nsteps] = x;
				p->step_edge[p->nsteps++] = e;
				bound[x == p->ea[e] ? p->eb[e] : p->ea[e]] = true;
				used[e] = true;
				progress = 1;
				break;			/* restart: keep the leaf order as far as possible */
			}
		}
	}
}

static int	prescreen_pattern(RptgPattern *p);
static uint64 *predicate_bitmap(RptgPattern *p, int x, uint64 words);
static double predicate_estimate(RptgPattern *p, int x);
static rptg_colindex *column_index(Oid rel, AttrNumber att, bool build);
static bool pred_indexed(RptgPattern *p, int x);
static void build_graph(Oid erel);

/* a bare SELECT count(*) FROM <pattern> WHERE <joins and predicates>: no grouping, DISTINCT, ORDER BY, LIMIT,
 * FILTER, or other output column */
static bool
is_count_star(Query *parse)
{
	TargetEntry *tle;
	Aggref	   *agg;

	if (!parse->hasAggs || parse->groupClause || parse->groupingSets || parse->havingQual ||
		parse->distinctClause || parse->sortClause || parse->limitCount || parse->limitOffset ||
		parse->rowMarks || list_length(parse->targetList) != 1)
		return false;
	tle = linitial_node(TargetEntry, parse->targetList);
	if (tle->resjunk || !IsA(tle->expr, Aggref))
		return false;
	agg = (Aggref *) tle->expr;
	return agg->aggfnoid == F_COUNT_ && agg->aggstar && agg->aggfilter == NULL && agg->aggdistinct == NIL &&
		agg->aggorder == NIL && agg->args == NIL;
}

/* Counting shortcut (2026-10-06): the number of matches of a tree pattern by the core's counting join (every
 * predicate set materialized, transfers under the counting benefit, one forward pass over the counting
 * semiring), when its estimated cost is at most rptg.count_host times the engine's own enumeration estimate.
 * Returns the plan of SELECT <count>::int8, or NULL when the host keeps its own plan. */
static PlannedStmt *
count_plan(Query *parse, RptgPattern *p, const char *query_string, int cursorOptions, ParamListInfo boundParams,
		   ExplainState *es)
{
	rptg_pattern rp;
	rptg_options opt;
	uint64	   *init[RPTG_MAXV] = {0};
	uint64		cnt = 0;
	double		E = 0, C = 0;
	double		est[RPTG_MAXV], stats[5 * RPTG_MAXV];
	int			did = 0;
	char		log[2048];
	instr_time	t0, t1;

	memset(&rp, 0, sizeof(rp));
	memset(&opt, 0, sizeof(opt));
	rp.k = p->k;
	rp.nedges = p->ne;
	rp.ea = p->ea;
	rp.eb = p->eb;
	rp.start = p->start;
	rp.nsteps = p->nsteps;
	rp.step_bound = p->step_bound;
	rp.step_edge = p->step_edge;
	rp.plan_root = -1;
	opt.beta = rptg_beta;
	log[0] = 0;
	INSTR_TIME_SET_CURRENT(t0);
	in_rptg = true;
	PG_TRY();
	{
		uint64		words;

		if (SPI_connect() != SPI_OK_CONNECT)
			elog(ERROR, "pg_rptg: SPI_connect failed");
		if (graph == NULL || graph_rel != p->erel)
			build_graph(p->erel);
		/* the decision from estimates (column index: exact sizes and degree sums; else the planner's rows and
		 * the average degree), before any predicate set is materialized */
		for (int x = 0; x < p->k; x++)
		{
			rptg_colindex *ix = pred_indexed(p, x) ? column_index(p->vrel, p->pred_att[x], true) : NULL;

			stats[5 * x] = -1;
			est[x] = -1;
			if (p->pred_sql[x] == NULL)
				continue;
			if (ix)
				est[x] = (double) rptg_colindex_range(ix, p->pred_lo[x], p->pred_lo_incl[x], p->pred_hi[x],
													  p->pred_hi_incl[x], &stats[5 * x]);
			else
				est[x] = p->est_rows[x] >= 0 ? p->est_rows[x] : predicate_estimate(p, x);
		}
		did = rptg_count_decide(graph, &rp, est, stats, &opt, rptg_count_host, rptg_count_floor, &E, &C);
		if (did)
		{
			words = (rptg_graph_n(graph) + 63) / 64;
			for (int x = 0; x < p->k; x++)
				if (p->pred_sql[x])
					init[x] = predicate_bitmap(p, x, words);
		}
		SPI_finish();
	}
	PG_FINALLY();
	{
		in_rptg = false;
	}
	PG_END_TRY();
	if (did)
		did = rptg_count(graph, &rp, init, &opt, rptg_count_host, rptg_count_floor, &cnt, &E, &C,
						 rptg_debug ? log : NULL, sizeof(log));
	for (int x = 0; x < p->k; x++)
		if (init[x])
			free(init[x]);
	INSTR_TIME_SET_CURRENT(t1);
	if (rptg_debug)
		elog(LOG, "pg_rptg: plan %d count(*) %s (E %.3g, C %.3g) in %.2f ms; %s", p->id,
			 did ? "by the counting join" : "left to the host", E, C,
			 INSTR_TIME_GET_MILLISEC(t1) - INSTR_TIME_GET_MILLISEC(t0), did ? log : "");
	if (!did)
		return NULL;
	{
		Query	   *q = makeNode(Query);
		TargetEntry *otle = linitial_node(TargetEntry, parse->targetList);
		Const	   *c = makeConst(INT8OID, -1, InvalidOid, sizeof(int64), Int64GetDatum((int64) cnt), false,
								  FLOAT8PASSBYVAL);

		q->commandType = CMD_SELECT;
		q->canSetTag = parse->canSetTag;
		q->jointree = makeFromExpr(NIL, NULL);
		q->targetList = list_make1(makeTargetEntry((Expr *) c, 1,
												   otle->resname ? pstrdup(otle->resname) : "count", false));
		q->stmt_location = parse->stmt_location;
		q->stmt_len = parse->stmt_len;
		return prev_planner ? prev_planner(q, query_string, cursorOptions, boundParams, es)
			: standard_planner(q, query_string, cursorOptions, boundParams, es);
	}
}

static PlannedStmt *
rptg_planner(Query *parse, const char *query_string, int cursorOptions, ParamListInfo boundParams,
			 ExplainState *es)
{
	RptgPattern *pat = NULL;
	int			rt_kind[RPTG_MAXRT], rt_node[RPTG_MAXRT];
	PlannedStmt *stmt;

	if (rptg_enabled && !in_rptg && !IsParallelWorker())
	{
		if (!OidIsValid(member_oid))
		{
			Oid			argt[3] = {INT4OID, INT4OID, INT4OID};

			member_oid = LookupFuncName(list_make1(makeString("rptg_member")), 3, argt, true);
		}
		if (OidIsValid(member_oid))
			pat = recognize(parse, rt_kind, rt_node);
	}
	if (pat)
	{
		capture_parse = parse;
		for (int i = 0; i < RPTG_MAXRT; i++)
			captured_rows[i] = -1;
	}
	stmt = prev_planner ? prev_planner(parse, query_string, cursorOptions, boundParams, es)
		: standard_planner(parse, query_string, cursorOptions, boundParams, es);
	capture_parse = NULL;
	if (pat)
	{
		PlanCtx		c;

		memset(&c, 0, sizeof(c));
		c.rt_kind = rt_kind;
		c.rt_node = rt_node;
		c.pat = pat;
		c.first_vertex = -1;
		c.a_src = get_attnum(pat->erel, "src");
		c.a_dst = get_attnum(pat->erel, "dst");
		c.a_id = OidIsValid(pat->vrel) ? get_attnum(pat->vrel, "id") : InvalidAttrNumber;
		pat->id = next_pattern_id++;
		decorate(stmt->planTree, &c);
		host_order(&c);
		pat->nplan = 0;
		pat->plan_root = host_tree(stmt->planTree, &c);
		/* pre-screen on the host's own estimates (histograms): a query in which no transfer can pass the
		 * budget keeps its plan untouched and pays nothing at execution */
		for (int x = 0; x < pat->k; x++)
			pat->est_rows[x] = -1;
		for (int rti = 1; rti < RPTG_MAXRT; rti++)
			if (rt_kind[rti] == 2 && pat->pred_sql[rt_node[rti]] && captured_rows[rti] >= 0)
			{
				int			x = rt_node[rti];

				pat->est_rows[x] = pat->est_rows[x] < 0 ? captured_rows[rti] : Min(pat->est_rows[x], captured_rows[rti]);
			}
		if (rptg_count_on && pat->nsteps == pat->ne && is_count_star(parse))
		{
			PlannedStmt *cs = count_plan(parse, pat, query_string, cursorOptions, boundParams, es);

			if (cs)
				return cs;
		}
		pat->admitted = prescreen_pattern(pat);
		if (pat->admitted > 0)
		{
			c.add = true;
			decorate(stmt->planTree, &c);
		}
		if (c.nquals > 0)
		{
			int			slot = pat->id % RPTG_KEEP;

			if (patterns[slot])
			{
				for (int x = 0; x < patterns[slot]->k; x++)
					if (patterns[slot]->pred_sql[x])
						pfree(patterns[slot]->pred_sql[x]);
				pfree(patterns[slot]);
			}
			patterns[slot] = pat;
			stmt->extension_state = lappend(stmt->extension_state,
											makeDefElem("pg_rptg", (Node *) makeInteger(pat->id), -1));
		}
	}
	return stmt;
}

static void
rptg_upper_paths(PlannerInfo *root, UpperRelationKind stage, RelOptInfo *input_rel,
				 RelOptInfo *output_rel, void *extra)
{
	if (prev_upper_paths)
		prev_upper_paths(root, stage, input_rel, output_rel, extra);
	if (capture_parse && root->parse == capture_parse && stage == UPPERREL_FINAL)
		for (int rti = 1; rti < root->simple_rel_array_size && rti < RPTG_MAXRT; rti++)
		{
			RelOptInfo *rel = root->simple_rel_array[rti];

			if (rel && rel->reloptkind == RELOPT_BASEREL)
				captured_rows[rti] = rel->rows;
		}
}

/* ------------------------------------------------------------------ execution */
static void
build_graph(Oid erel)
{
	instr_time	t0, t1;
	uint64		cap = 1 << 20, m = 0, n = 0;
	uint32	   *src, *dst;
	Portal		cur;
	char		sql[256];

	INSTR_TIME_SET_CURRENT(t0);
	src = malloc(cap * sizeof(uint32));
	dst = malloc(cap * sizeof(uint32));
	snprintf(sql, sizeof(sql), "SELECT src, dst FROM %s", quote_identifier(get_rel_name(erel)));
	cur = SPI_cursor_open_with_args(NULL, sql, 0, NULL, NULL, NULL, true, 0);
	for (;;)
	{
		SPI_cursor_fetch(cur, true, 100000);
		if (SPI_processed == 0)
			break;
		if (m + SPI_processed > cap)
		{
			while (m + SPI_processed > cap)
				cap *= 2;
			src = realloc(src, cap * sizeof(uint32));
			dst = realloc(dst, cap * sizeof(uint32));
		}
		for (uint64 i = 0; i < SPI_processed; i++)
		{
			bool		isnull;
			HeapTuple	tup = SPI_tuptable->vals[i];

			src[m] = DatumGetInt32(SPI_getbinval(tup, SPI_tuptable->tupdesc, 1, &isnull));
			dst[m] = DatumGetInt32(SPI_getbinval(tup, SPI_tuptable->tupdesc, 2, &isnull));
			n = Max(n, (uint64) Max(src[m], dst[m]) + 1);
			m++;
		}
		SPI_freetuptable(SPI_tuptable);
	}
	SPI_cursor_close(cur);
	if (OidIsValid(RelnameGetRelid(rptg_vertex_table)))
	{
		snprintf(sql, sizeof(sql), "SELECT max(id) FROM %s", quote_identifier(rptg_vertex_table));
		if (SPI_execute(sql, true, 1) == SPI_OK_SELECT && SPI_processed == 1)
		{
			bool		isnull;
			Datum		d = SPI_getbinval(SPI_tuptable->vals[0], SPI_tuptable->tupdesc, 1, &isnull);

			if (!isnull)
				n = Max(n, (uint64) DatumGetInt32(d) + 1);
		}
	}
	if (graph)
		rptg_graph_free(graph);
	graph = rptg_graph_build(n, m, src, dst);
	graph_rel = erel;
	free(src);
	free(dst);
	INSTR_TIME_SET_CURRENT(t1);
	INSTR_TIME_SUBTRACT(t1, t0);
	graph_build_ms = INSTR_TIME_GET_MILLISEC(t1);
	elog(rptg_debug ? LOG : DEBUG1, "pg_rptg: adjacency index of %s: n=%lu m=%lu in %.1f ms",
		 get_rel_name(erel), (unsigned long) n, (unsigned long) m, graph_build_ms);
}

/* estimated number of rows of "SELECT id FROM V WHERE pred" from the host planner (histograms) */
static double
predicate_estimate(RptgPattern *p, int x)
{
	StringInfoData sql;
	SPIPlanPtr	plan;
	CachedPlan *cp;
	double		rows = -1;

	initStringInfo(&sql);
	appendStringInfo(&sql, "SELECT id FROM %s WHERE %s", quote_identifier(get_rel_name(p->vrel)), p->pred_sql[x]);
	plan = SPI_prepare(sql.data, 0, NULL);
	if (plan)
	{
		cp = SPI_plan_get_cached_plan(plan);
		if (cp && list_length(cp->stmt_list) == 1)
			rows = linitial_node(PlannedStmt, cp->stmt_list)->planTree->plan_rows;
		if (cp)
			ReleaseCachedPlan(cp, NULL);	/* unsaved SPI plan: no resource owner */
		SPI_freeplan(plan);
	}
	pfree(sql.data);
	return rows;
}

/* a DestReceiver that sets the bit of every received vertex id: no tuple is copied */
typedef struct BitmapDest
{
	DestReceiver pub;
	uint64	   *w;
	uint64		words;
} BitmapDest;

static bool
bd_receive(TupleTableSlot *slot, DestReceiver *self)
{
	BitmapDest *d = (BitmapDest *) self;
	bool		isnull;
	Datum		v = slot_getattr(slot, 1, &isnull);

	if (!isnull)
	{
		int32		id = DatumGetInt32(v);

		if (id >= 0 && (uint64) id < d->words * 64)
			d->w[id >> 6] |= UINT64CONST(1) << (id & 63);
	}
	return true;
}

static void
bd_startup(DestReceiver *self, int operation, TupleDesc typeinfo)
{
}

static void
bd_noop(DestReceiver *self)
{
}

/* ------------------------------------------------------------------ predicate column indexes
 * One per (vertex table, numeric column) that a range predicate uses, built once per backend like the
 * adjacency index: a sorted copy of the column with prefix sums of degrees and degree products
 * (rptg_colindex). It gives exact sizes, degree sums, and moments of a range predicate at plan time by
 * binary search and materializes its candidate set without a query. Assumes a static vertex table. */
typedef struct ColCache
{
	Oid			rel;
	AttrNumber	att;
	rptg_colindex *ix;
} ColCache;
static ColCache colcache[16];
static int	ncolcache = 0;

typedef struct PairDest
{
	DestReceiver pub;
	uint32	   *ids;
	double	   *vals;
	uint64		n, cap;
} PairDest;

static bool
pd_receive(TupleTableSlot *slot, DestReceiver *self)
{
	PairDest   *d = (PairDest *) self;
	bool		n1, n2;
	Datum		id = slot_getattr(slot, 1, &n1);
	Datum		v = slot_getattr(slot, 2, &n2);

	if (n1 || n2 || DatumGetInt32(id) < 0)
		return true;
	if (d->n == d->cap)
	{
		d->cap = d->cap ? 2 * d->cap : 1 << 16;
		d->ids = realloc(d->ids, d->cap * sizeof(uint32));
		d->vals = realloc(d->vals, d->cap * sizeof(double));
	}
	d->ids[d->n] = (uint32) DatumGetInt32(id);
	d->vals[d->n++] = DatumGetFloat8(v);
	return true;
}

/* the column index of (rel, att); builds it through SPI (the caller is connected) unless cached */
static rptg_colindex *
column_index(Oid rel, AttrNumber att, bool build)
{
	PairDest	d;
	SPIExecuteOptions o;
	StringInfoData sql;
	char	   *col;

	for (int i = 0; i < ncolcache; i++)
		if (colcache[i].rel == rel && colcache[i].att == att)
			return colcache[i].ix;
	if (!build || ncolcache == lengthof(colcache) || graph == NULL)
		return NULL;
	col = get_attname(rel, att, false);
	memset(&d, 0, sizeof(d));
	d.pub.receiveSlot = pd_receive;
	d.pub.rStartup = bd_startup;
	d.pub.rShutdown = bd_noop;
	d.pub.rDestroy = bd_noop;
	d.pub.mydest = DestNone;
	memset(&o, 0, sizeof(o));
	o.read_only = true;
	o.dest = (DestReceiver *) &d;
	initStringInfo(&sql);
	appendStringInfo(&sql, "SELECT id, %s::float8 FROM %s", quote_identifier(col), quote_identifier(get_rel_name(rel)));
	if (SPI_execute_extended(sql.data, &o) < 0)
		elog(ERROR, "pg_rptg: column index query failed: %s", sql.data);
	colcache[ncolcache].rel = rel;
	colcache[ncolcache].att = att;
	colcache[ncolcache].ix = rptg_colindex_build(graph, d.n, d.ids, d.vals);
	free(d.ids);
	free(d.vals);
	pfree(sql.data);
	elog(rptg_debug ? LOG : DEBUG1, "pg_rptg: column index of %s.%s: %lu rows", get_rel_name(rel), col, (unsigned long) d.n);
	return colcache[ncolcache++].ix;
}

/* the predicate of x can use a column index */
static bool
pred_indexed(RptgPattern *p, int x)
{
	return rptg_column_index && p->pred_sql[x] != NULL && p->pred_att[x] > 0;
}

static uint64 *
predicate_bitmap(RptgPattern *p, int x, uint64 words)
{
	BitmapDest	d;
	SPIExecuteOptions o;
	StringInfoData sql;

	memset(&d, 0, sizeof(d));
	d.pub.receiveSlot = bd_receive;
	d.pub.rStartup = bd_startup;
	d.pub.rShutdown = bd_noop;
	d.pub.rDestroy = bd_noop;
	d.pub.mydest = DestNone;
	d.w = calloc(words, sizeof(uint64));
	d.words = words;
	if (pred_indexed(p, x))
	{
		rptg_colindex *ix = column_index(p->vrel, p->pred_att[x], true);

		if (ix)
		{
			rptg_colindex_bitmap(ix, p->pred_lo[x], p->pred_lo_incl[x], p->pred_hi[x], p->pred_hi_incl[x], d.w);
			return d.w;
		}
	}
	memset(&o, 0, sizeof(o));
	o.read_only = true;
	o.dest = (DestReceiver *) &d;
	initStringInfo(&sql);
	appendStringInfo(&sql, "SELECT id FROM %s WHERE %s", quote_identifier(get_rel_name(p->vrel)), p->pred_sql[x]);
	if (SPI_execute_extended(sql.data, &o) < 0)
		elog(ERROR, "pg_rptg: predicate query failed: %s", sql.data);
	pfree(sql.data);
	return d.w;
}

/* ------------------------------------------------------------------ filter placement
 * A member filter on (scan, vertex x) is redundant when the scan is a direct input of the join that
 * first equates its x column with the other input, and the other input is already restricted to B_x by
 * a kept filter: that join discards the same rows, and the filter would only add per-row work. */
typedef struct Filt
{
	Plan	   *scan;
	FuncExpr   *f;
	int			x;
	bool		keep;
} Filt;

typedef struct FiltSet
{
	Filt	   *v;
	int			n;
	RptgExec   *e;
	int			planid;
	int		   *rt_mask;		/* classes of the columns of each range-table entry (by scanrelid) */
} FiltSet;

static bool
is_member_qual(Node *q, int planid, int *x)
{
	FuncExpr   *f;

	if (!IsA(q, FuncExpr) || ((FuncExpr *) q)->funcid != member_oid)
		return false;
	f = (FuncExpr *) q;
	if (DatumGetInt32(((Const *) linitial(f->args))->constvalue) != planid)
		return false;
	*x = DatumGetInt32(((Const *) lsecond(f->args))->constvalue);
	return true;
}

static void
collect_filters(Plan *plan, FiltSet *fs)
{
	ListCell   *lc;

	if (plan == NULL)
		return;
	foreach(lc, plan->qual)
	{
		int			x;

		if (is_member_qual(lfirst(lc), fs->planid, &x))
		{
			Filt	   *f = &fs->v[fs->n++];

			f->scan = plan;
			f->f = lfirst(lc);
			f->x = x;
			f->keep = x < fs->e->k && fs->e->bits[x] != NULL;
		}
	}
	collect_filters(outerPlan(plan), fs);
	collect_filters(innerPlan(plan), fs);
}

static bool
is_join(Plan *p)
{
	return IsA(p, NestLoop) || IsA(p, HashJoin) || IsA(p, MergeJoin);
}

static bool
is_scan(Plan *p)
{
	return IsA(p, SeqScan) || IsA(p, IndexScan) || IsA(p, IndexOnlyScan) || IsA(p, BitmapHeapScan);
}

/* the scan below p through single-input nodes (Hash, Sort, Material, Memoize, Gather, ...), or NULL */
static Plan *
direct_scan(Plan *p)
{
	while (p && !is_scan(p) && !is_join(p) && innerPlan(p) == NULL)
		p = outerPlan(p);
	return p && is_scan(p) ? p : NULL;
}

typedef struct Masks
{
	uint32		present, kept;
} Masks;

static uint32
kept_mask_of(Plan *scan, FiltSet *fs)
{
	uint32		m = 0;

	for (int i = 0; i < fs->n; i++)
		if (fs->v[i].scan == scan && fs->v[i].keep)
			m |= 1u << fs->v[i].x;
	return m;
}

static void
drop_filter(Plan *scan, int x, FiltSet *fs)
{
	for (int i = 0; i < fs->n; i++)
		if (fs->v[i].scan == scan && fs->v[i].x == x)
			fs->v[i].keep = false;
}

static Masks
place_filters(Plan *p, FiltSet *fs)
{
	Masks		m = {0, 0};

	if (p == NULL)
		return m;
	if (is_scan(p))
	{
		int			rti = ((Scan *) p)->scanrelid;

		if (rti > 0 && rti < RPTG_MAXRT)
			m.present = fs->rt_mask[rti];
		m.kept = kept_mask_of(p, fs);
		return m;
	}
	if (is_join(p))
	{
		Masks		l = place_filters(outerPlan(p), fs), r = place_filters(innerPlan(p), fs);
		uint32		both = l.present & r.present;
		Plan	   *dl = direct_scan(outerPlan(p)), *dr = direct_scan(innerPlan(p));

		for (int x = 0; x < RPTG_MAXV; x++)
		{
			if (!(both & (1u << x)))
				continue;
			if (dr && (l.kept & (1u << x)) && (r.kept & (1u << x)))
			{
				drop_filter(dr, x, fs);
				r.kept &= ~(1u << x);
			}
			else if (dl && (r.kept & (1u << x)) && (l.kept & (1u << x)))
			{
				drop_filter(dl, x, fs);
				l.kept &= ~(1u << x);
			}
		}
		m.present = l.present | r.present;
		m.kept = l.kept | r.kept;
		return m;
	}
	/* single-input nodes; other multi-input nodes (Append, SubqueryScan...) do not occur in patterns */
	m = place_filters(outerPlan(p), fs);
	if (innerPlan(p))
	{
		Masks		r = place_filters(innerPlan(p), fs);

		m.present |= r.present;
		m.kept |= r.kept;
	}
	return m;
}

/* remove the dropped member filters; renumber the kept ones to the execution id. Returns whether the
 * plan has a Gather (workers need the published file). */
static bool
apply_filters(Plan *plan, FiltSet *fs)
{
	bool		parallel = false;

	if (plan == NULL)
		return false;
	if (IsA(plan, Gather) || IsA(plan, GatherMerge))
		parallel = true;
	if (plan->qual)
	{
		List	   *keep = NIL;
		ListCell   *lc;

		foreach(lc, plan->qual)
		{
			Node	   *q = lfirst(lc);
			int			x;

			if (is_member_qual(q, fs->planid, &x))
			{
				bool		k = false;

				for (int i = 0; i < fs->n; i++)
					if (fs->v[i].f == (FuncExpr *) q)
						k = fs->v[i].keep;
				if (!k)
					continue;
				((Const *) linitial(((FuncExpr *) q)->args))->constvalue = Int32GetDatum(fs->e->execid);
			}
			keep = lappend(keep, q);
		}
		plan->qual = keep;
	}
	parallel |= apply_filters(outerPlan(plan), fs);
	parallel |= apply_filters(innerPlan(plan), fs);
	return parallel;
}

static void
publish_file(RptgExec *e)
{
	int			fd;
	uint64		hdrw = 2 + e->k, off = hdrw;
	uint64	   *hdr = calloc(hdrw, sizeof(uint64));

	hdr[0] = e->k;
	hdr[1] = e->words;
	for (int x = 0; x < e->k; x++)
		if (e->bits[x])
		{
			hdr[2 + x] = off;
			off += e->words;
		}
	exec_path(e->path, MyProcNumber, e->execid);
	fd = open(e->path, O_CREAT | O_TRUNC | O_WRONLY, 0600);
	if (fd < 0)
		elog(ERROR, "pg_rptg: cannot create %s: %m", e->path);
	if (write(fd, hdr, hdrw * sizeof(uint64)) != (ssize_t) (hdrw * sizeof(uint64)))
		elog(ERROR, "pg_rptg: write %s: %m", e->path);
	for (int x = 0; x < e->k; x++)
		if (e->bits[x] &&
			write(fd, e->bits[x], e->words * sizeof(uint64)) != (ssize_t) (e->words * sizeof(uint64)))
			elog(ERROR, "pg_rptg: write %s: %m", e->path);
	close(fd);
	free(hdr);
}

/* stats of the small predicate sets (at most rptg.exact_rows estimated rows), materialized through SPI */
static void
small_set_stats(RptgPattern *p, double *est, double *stats)
{
	uint64		words = (rptg_graph_n(graph) + 63) / 64;
	bool		any = false;

	for (int i = 0; i < 5 * p->k; i++)
		stats[i] = -1;
	for (int x = 0; x < p->k; x++)
		any |= p->pred_sql[x] != NULL && est[x] >= 0 && est[x] <= rptg_exact_rows;
	if (!any)
		return;
	in_rptg = true;
	PG_TRY();
	{
		if (SPI_connect() != SPI_OK_CONNECT)
			elog(ERROR, "pg_rptg: SPI_connect failed");
		for (int x = 0; x < p->k; x++)
			if (p->pred_sql[x] != NULL && est[x] >= 0 && est[x] <= rptg_exact_rows)
			{
				uint64	   *w = predicate_bitmap(p, x, words);
				uint64		cnt;

				rptg_bitmap_stats(graph, w, &cnt, &stats[5 * x]);
				est[x] = (double) cnt;
				free(w);
			}
		SPI_finish();
	}
	PG_FINALLY();
	{
		in_rptg = false;
	}
	PG_END_TRY();
}

/* plan time: build the adjacency index if needed, estimate missing predicate sizes, and dry-run the
 * transfer sequence; returns the number of admitted transfers and sets p->needed */
static int
prescreen_pattern(RptgPattern *p)
{
	rptg_pattern rp;
	rptg_options opt;
	double		est[RPTG_MAXV];
	bool		need_spi = graph == NULL || graph_rel != p->erel;
	int			admitted;
	char		log[2048];

	for (int x = 0; x < p->k; x++)
		need_spi |= (p->pred_sql[x] != NULL && p->est_rows[x] < 0 && !pred_indexed(p, x)) ||
			(pred_indexed(p, x) && column_index(p->vrel, p->pred_att[x], false) == NULL);
	if (need_spi)
	{
		in_rptg = true;
		PG_TRY();
		{
			if (SPI_connect() != SPI_OK_CONNECT)
				elog(ERROR, "pg_rptg: SPI_connect failed");
			if (graph == NULL || graph_rel != p->erel)
				build_graph(p->erel);
			for (int x = 0; x < p->k; x++)
				if (pred_indexed(p, x))
					column_index(p->vrel, p->pred_att[x], true);
				else if (p->pred_sql[x] && p->est_rows[x] < 0)
					p->est_rows[x] = predicate_estimate(p, x);
			SPI_finish();
		}
		PG_FINALLY();
		{
			in_rptg = false;
		}
		PG_END_TRY();
	}
	for (int x = 0; x < p->k; x++)
		est[x] = p->pred_sql[x] ? p->est_rows[x] : -1;
	rp.k = p->k;
	rp.nedges = p->ne;
	rp.ea = p->ea;
	rp.eb = p->eb;
	rp.start = p->start;
	rp.nsteps = p->nsteps;
	rp.step_bound = p->step_bound;
	rp.step_edge = p->step_edge;
	rp.nplan = p->plan_root >= 0 ? p->nplan : 0;
	rp.plan_root = p->plan_root;
	rp.plan_left = p->plan_left;
	rp.plan_right = p->plan_right;
	rp.plan_edge = p->plan_edge;
	rp.plan_vertex = p->plan_vertex;
	rp.plan_param = p->plan_param;
	opt.beta = rptg_beta;
	opt.pred_cost = rptg_pred_cost;
	opt.first_cost = rptg_first_cost;
	opt.filter_cost = rptg_filter_cost;
	p->needed = 0;
	rptg_set_trace(rptg_trace);
	/* every predicate has a column index: exact sizes, degree sums, and moments by binary search */
	{
		bool		all = true;
		double		stats[5 * RPTG_MAXV];

		for (int x = 0; x < p->k; x++)
		{
			rptg_colindex *ix = pred_indexed(p, x) ? column_index(p->vrel, p->pred_att[x], false) : NULL;

			stats[5 * x] = -1;
			if (p->pred_sql[x] == NULL)
				continue;
			if (ix == NULL)
			{
				all = false;
				continue;
			}
			est[x] = (double) rptg_colindex_range(ix, p->pred_lo[x], p->pred_lo_incl[x], p->pred_hi[x],
												  p->pred_hi_incl[x], &stats[5 * x]);
		}
		if (all)
		{
			opt.optimistic = 0;
			opt.pred_cost = rptg_index_pred_cost;
			admitted = rptg_prescreen(graph, &rp, est, stats, &opt, &p->needed, rptg_debug ? log : NULL, sizeof(log));
			if (rptg_debug)
				elog(LOG, "pg_rptg: plan %d indexed pre-screen: %d admitted, needed %x; %s", p->id, admitted, p->needed, log);
			return admitted;
		}
	}
	/* level 1: estimated sizes with the largest degree sums such sets could have; no SPI at all */
	opt.optimistic = 1;
	admitted = rptg_prescreen(graph, &rp, est, NULL, &opt, &p->needed, rptg_debug ? log : NULL, sizeof(log));
	if (rptg_debug)
		elog(LOG, "pg_rptg: plan %d optimistic pre-screen: %d admitted; %s", p->id, admitted, log);
	opt.optimistic = 0;
	if (admitted > 0)
	{
		/* level 2: materialize the small predicate sets for their exact sizes, degree sums, and moments
		 * (evaluated again at execution: the data may change between planning and execution) */
		double		stats[5 * RPTG_MAXV];

		small_set_stats(p, est, stats);
		p->needed = 0;
		admitted = rptg_prescreen(graph, &rp, est, stats, &opt, &p->needed, rptg_debug ? log : NULL, sizeof(log));
		if (rptg_debug)
			elog(LOG, "pg_rptg: plan %d exact pre-screen: %d admitted; %s", p->id, admitted, log);
	}
	if (rptg_debug)
		elog(LOG, "pg_rptg: plan %d pre-screen: %d transfers admitted, needed %x", p->id, admitted, p->needed);
	return admitted;
}

static void
run_transfers(QueryDesc *qd, RptgPattern *p)
{
	instr_time	t0, t1, t2, t3, t4;
	uint64	   *init[RPTG_MAXV] = {0};
	uint64		init_cnt[RPTG_MAXV];
	uint64		words;
	rptg_pattern rp;
	rptg_options opt;
	char		log[4096];
	RptgExec   *e;
	PlannedStmt *copy;
	MemoryContextCallback *cb;
	int			nfilters = 0, admitted = 0, nkept = 0;
	uint32		needed = 0;
	FiltSet		fs;
	bool		empty = false;
	uint32		selff = 0;

	rp.k = p->k;
	rp.nedges = p->ne;
	rp.ea = p->ea;
	rp.eb = p->eb;
	rp.start = p->start;
	rp.nsteps = p->nsteps;
	rp.step_bound = p->step_bound;
	rp.step_edge = p->step_edge;
	rp.nplan = p->plan_root >= 0 ? p->nplan : 0;
	rp.plan_root = p->plan_root;
	rp.plan_left = p->plan_left;
	rp.plan_right = p->plan_right;
	rp.plan_edge = p->plan_edge;
	rp.plan_vertex = p->plan_vertex;
	rp.plan_param = p->plan_param;
	opt.beta = rptg_beta;
	opt.pred_cost = rptg_pred_cost;
	opt.first_cost = 0;
	opt.filter_cost = rptg_filter_cost;
	log[0] = 0;

	e = (RptgExec *) calloc(1, sizeof(RptgExec));
	e->execid = next_exec_id++;
	e->k = p->k;
	cb = MemoryContextAlloc(CurrentMemoryContext, sizeof(MemoryContextCallback));
	cb->func = exec_release;
	cb->arg = e;
	MemoryContextRegisterResetCallback(CurrentMemoryContext, cb);

	INSTR_TIME_SET_CURRENT(t0);
	in_rptg = true;
	PG_TRY();
	{
		if (SPI_connect() != SPI_OK_CONNECT)
			elog(ERROR, "pg_rptg: SPI_connect failed");
		if (graph == NULL || graph_rel != p->erel)
			build_graph(p->erel);
		INSTR_TIME_SET_CURRENT(t1);
		words = (rptg_graph_n(graph) + 63) / 64;
		e->words = words;
		admitted = p->admitted;
		needed = p->needed;
		INSTR_TIME_SET_CURRENT(t2);
		/* only the predicates whose information an admitted transfer carries are evaluated; the other
		 * vertices enter the transfer phase unconstrained (supersets stay correct) */
		for (int x = 0; x < p->k; x++)
			if (p->pred_sql[x] && ((needed >> x) & 1))
				init[x] = predicate_bitmap(p, x, words);
		SPI_finish();
	}
	PG_FINALLY();
	{
		in_rptg = false;
	}
	PG_END_TRY();
	INSTR_TIME_SET_CURRENT(t3);

	if (admitted > 0)
	{
		for (int x = 0; x < p->k; x++)
		{
			init_cnt[x] = 0;
			if (init[x])
				for (uint64 i = 0; i < words; i++)
					init_cnt[x] += pg_popcount64(init[x][i]);
		}
		e->red = rptg_reduce(graph, &rp, init, &opt, log, sizeof(log));
		selff = rptg_self_filters(e->red);
		for (int x = 0; x < p->k; x++)
		{
			int			full;
			uint64		cnt;
			const uint64 *w = rptg_result(e->red, x, &full, &cnt);

			/* a filter pays only if transfers removed vertices beyond the vertex's own predicate,
			 * which the host applies anyway */
			e->bits[x] = (full || (init[x] && cnt >= init_cnt[x] && !((selff >> x) & 1))) ? NULL : w;
			nfilters += e->bits[x] != NULL;
			empty |= !full && cnt == 0;
			if (init[x])
				free(init[x]);
		}
		/* an empty candidate set proves the result empty: every vertex then has the empty set as its
		 * candidate set, and with every filter kept the first scan of the plan returns nothing */
		if (empty)
		{
			e->zero = calloc(words, sizeof(uint64));
			for (int x = 0; x < p->k; x++)
				e->bits[x] = e->zero;
			nfilters = p->k;
		}
	}
	INSTR_TIME_SET_CURRENT(t4);

	copy = copyObject(qd->plannedstmt);
	memset(&fs, 0, sizeof(fs));
	fs.v = palloc0(sizeof(Filt) * 4 * RPTG_MAXE + sizeof(Filt) * RPTG_MAXRT);
	fs.e = e;
	fs.planid = p->id;
	fs.rt_mask = p->rt_mask;
	collect_filters(copy->planTree, &fs);
	if (nfilters > 0 && !empty)
		place_filters(copy->planTree, &fs);
	for (int i = 0; i < fs.n; i++)
		nkept += fs.v[i].keep;
	if (apply_filters(copy->planTree, &fs) && nkept > 0)
		publish_file(e);
	qd->plannedstmt = copy;
	cur_exec = e;

	if (rptg_debug)
	{
		INSTR_TIME_SUBTRACT(t4, t3);
		INSTR_TIME_SUBTRACT(t3, t2);
		INSTR_TIME_SUBTRACT(t2, t1);
		INSTR_TIME_SUBTRACT(t1, t0);
		elog(LOG, "pg_rptg: plan %d exec %d: index %.2f ms, pre-screen %.2f ms (%d admitted, needed %x), predicates %.2f ms, "
			 "transfers %.2f ms, %d reduced vertices, %d of %d filters kept; %s",
			 p->id, e->execid, INSTR_TIME_GET_MILLISEC(t1), INSTR_TIME_GET_MILLISEC(t2), admitted, needed,
			 INSTR_TIME_GET_MILLISEC(t3), INSTR_TIME_GET_MILLISEC(t4), nfilters, nkept, fs.n, log);
	}
}

static void
rptg_ExecutorStart(QueryDesc *qd, int eflags)
{
	if (rptg_enabled && !in_rptg && !IsParallelWorker() && !(eflags & EXEC_FLAG_EXPLAIN_ONLY) &&
		qd->plannedstmt && qd->plannedstmt->extension_state)
	{
		ListCell   *lc;

		foreach(lc, qd->plannedstmt->extension_state)
		{
			DefElem    *d = lfirst(lc);

			if (strcmp(d->defname, "pg_rptg") == 0)
			{
				int			id = intVal(d->arg);
				RptgPattern *p = patterns[id % RPTG_KEEP];

				if (p && p->id == id)
					run_transfers(qd, p);
				break;
			}
		}
	}
	if (prev_ExecutorStart)
		prev_ExecutorStart(qd, eflags);
	else
		standard_ExecutorStart(qd, eflags);
}

void
_PG_init(void)
{
	DefineCustomBoolVariable("rptg.enabled", "Run RPT-G transfers for graph pattern queries.", NULL,
							 &rptg_enabled, false, PGC_USERSET, 0, NULL, NULL, NULL);
	/* calibration (DBLP, 8 workers): a nested-loop step over the adjacency index costs ~60 ns in
	 * PostgreSQL, an adjacency entry of a transfer ~4 ns, a row of a predicate query ~0.7 us */
	DefineCustomRealVariable("rptg.beta", "RPT-G transfer budget: host join work per transfer cost unit (0 = no budget).", NULL,
							 &rptg_beta, 10.0, 0.0, 1e9, PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomRealVariable("rptg.first_cost", "Cost units of running a transfer phase at all (SPI, ~0.6 ms).", NULL,
							 &rptg_first_cost, 150000.0, 0.0, 1e12, PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomIntVariable("rptg.exact_rows", "Predicate sets estimated at most this many rows are materialized at plan time.", NULL,
							&rptg_exact_rows, 20000, 0, INT_MAX, PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomBoolVariable("rptg.trace", "Trace the host-plan benefit model to the server log (stderr).", NULL,
							 &rptg_trace, false, PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomBoolVariable("rptg.column_index", "Evaluate range predicates on numeric vertex columns through an in-memory sorted column index.", NULL,
							 &rptg_column_index, true, PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomRealVariable("rptg.index_pred_cost", "Cost units per row of materializing a predicate through a column index.", NULL,
							 &rptg_index_pred_cost, 2.0, 0, 1e9, PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomRealVariable("rptg.filter_cost", "Cost units per scanned row of a candidate filter.", NULL,
							 &rptg_filter_cost, 3.0, 0.0, 1e9, PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomRealVariable("rptg.pred_cost", "Cost units per row of evaluating a vertex predicate.", NULL,
							 &rptg_pred_cost, 160.0, 0.0, 1e9, PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomStringVariable("rptg.edge_table", "Edge table (columns src, dst).", NULL,
							   &rptg_edge_table, "e", PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomStringVariable("rptg.vertex_table", "Vertex table (column id).", NULL,
							   &rptg_vertex_table, "v", PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomBoolVariable("rptg.debug", "Log RPT-G decisions.", NULL,
							 &rptg_debug, false, PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomBoolVariable("rptg.count", "Answer a bare count(*) over a tree pattern by the counting join.", NULL,
							 &rptg_count_on, true, PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomRealVariable("rptg.count_host", "Count when the counting cost is at most this factor times the "
							 "engine's own enumeration estimate.", NULL, &rptg_count_host, 8.0, 0.0, 1e9,
							 PGC_USERSET, 0, NULL, NULL, NULL);
	DefineCustomRealVariable("rptg.count_floor", "Count whenever the counting cost is below this many adjacency "
							 "entries.", NULL, &rptg_count_floor, 2e6, 0.0, 1e12, PGC_USERSET, 0, NULL, NULL, NULL);
	MarkGUCPrefixReserved("rptg");
	prev_planner = planner_hook;
	planner_hook = rptg_planner;
	prev_upper_paths = create_upper_paths_hook;
	create_upper_paths_hook = rptg_upper_paths;
	prev_ExecutorStart = ExecutorStart_hook;
	ExecutorStart_hook = rptg_ExecutorStart;
}
