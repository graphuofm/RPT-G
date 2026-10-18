#!/bin/bash
# Rebuild the anonymous public tree in ~/rptg-public (fresh single-commit history, identity scrubbed) and show what to push.
# After it finishes:  cd ~/rptg-public && git push -u origin main --force
set -e
RPTG_SRC=$RPTG_ROOT
set -e
cd $RPTG_ROOT
A=${TMPDIR:-/tmp}/rptg-public-stage
rm -rf $A; mkdir -p $A
for d in prototype hosts scripts queries docs; do rsync -a --exclude '*.o' --exclude '*.so' --exclude 'bin/' --exclude '__pycache__' --exclude '*.pyc' $d $A/; done
mkdir -p $A/results $A/paper/figgen; cp results/README.md $A/results/
for f in $(ls results | grep -E "^(final25_|final18c_|chain25_|pg19_|duckdb_|duckdb300_rptplus|duckdb300_4way|kuzu_|ladybug_|neo4j_|abl17|count1|dblp_qgen_v8|lj_qgen_v8|order_|headroom|cyc).*\.csv$"); do s=$(stat -c %s results/$f); [ $s -lt 60000000 ] && cp results/$f $A/results/; done
cp paper/figgen/*.py paper/figgen/example.json paper/figgen/numbers.json paper/figgen/ops5.json paper/figgen/series.pkl $A/paper/figgen/ 2>/dev/null || true; rsync -a paper/experiments $A/paper/
grep -r -l "jding" $A | xargs -r sed -i 's#$RPTG_ROOT#$RPTG_ROOT#g; s#python#python#g; s#python#python#g; s#\python#python#g; s#python#python#g; s###g; s#export JAVA_HOME=~/miniconda3/envs/neo4j PATH=~/miniconda3/envs/neo4j/bin:\$PATH#export JAVA_HOME=<a JDK 17>#g; s#^conda activate rptg-build.*#\# toolchain: GCC 11 or newer, cmake, ninja, Python 3.11 (see the root README)#; s#python#python#g; s#python#python#g; s#python#python#g; s#$HOME/\.TinyTeX#$HOME/.TinyTeX#g; s#$HOME#$HOME#g'
sed -i 's#^OUT=/tmp/claude-1006/[^ ]*#OUT=${OUT_DIR:-/tmp/rptg_profile}#' $A/scripts/profile.sh
cp $RPTG_SRC/scripts/publish_readme.md $A/README.md
echo "identifying strings left: $(grep -r -l -i -E 'jding|memphis|dingjiacheng|graphuofm|jiacheng|claude|anthropic' $A | wc -l)"
grep -r -l -i -E 'jding|memphis|dingjiacheng|graphuofm|jiacheng|claude|anthropic' $A | sed "s#$A/##" | head

# scrub what the tarball build does not: review wording, scratch paths, planning notes in Chinese, third-party PDFs
sed -i "s/Professor's request\. /Added after review. /" $A/docs/reports/gain_diagnosis.md
sed -i "s/Asked for by the professor's review\. /Added after review. /" $A/docs/insights.md
sed -i "s/asked for by the professor's review/added after review/" $A/scripts/duckdb_300_rptplus.sh
sed -i 's#/tmp/claude-1006/[^ `)]*scratchpad#/tmp/rptg#g' $A/docs/reports/gain_diagnosis.md
rm -rf $A/docs/plan $A/docs/papers
printf 'bin/\n*.o\n__pycache__/\n*.pyc\n*.progress\nshards_*/\n' > $A/.gitignore
echo "identity hits: $(grep -r -l -i -E 'jding|jiacheng|dingjiacheng|graphuofm|memphis|uofm|tsinghua|yiming|xiaofei|professor|outlook\.com|gmail\.com|/home/|claude|anthropic|/tmp/claude|教授|张哥' $A | wc -l)  chinese files: $(grep -r -l -P '[\x{4e00}-\x{9fff}]' $A | wc -l)"
P=$HOME/rptg-public; mkdir -p $P; rsync -a --delete --exclude .git $A/ $P/
cd $P; [ -d .git ] || { git init -q && git symbolic-ref HEAD refs/heads/main; }
git config user.name "RPT-G authors"; git config user.email "rptg-anonymous@users.noreply.github.com"
git add -A; git -c commit.gpgsign=false commit -q -m "RPT-G anonymous artifact: update" || true
git remote get-url origin >/dev/null 2>&1 || git remote add origin https://github.com/graphuofm/RPT-G.git
git log --format='%h %an <%ae> | %s' | head -3; git ls-files | wc -l
