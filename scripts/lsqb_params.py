#!/usr/bin/env python
"""LSQB-P: parameterized variants of the conjunctive LSQB queries (2026-09-29).

LSQB's nine queries count whole-graph patterns without predicates; the data sets carry only identifiers.
LDBC workloads instead start from given entities (a country, a tag, a person). LSQB-P keeps the LSQB
pattern shapes and adds identifier-equality predicates on one or two anchor vertices, drawn uniformly at
random from the entities of the data set (seeded):

  q1c   q1 (8-vertex path)        country = X
  q1t   q1                        tag class = Y
  q1ct  q1                        country = X and tag class = Y   (both ends of the path)
  q2p   q2 (4-cycle)              person1 = X
  q3c   q3 (country + knows triangle, cyclic)   country = X
  q4t   q4 (star around a message)              tag = X
  q5t   q5 without the tag inequality           tag1 = X
  q6t   q6 without the person inequality        tag = X

Output: queries/lsqb_p_sf{SF}.txt with lines "id=N cypher=MATCH ... RETURN count(*)" (scripts/run_kuzu.py
runs such lines directly) and a side CSV id,template,params.
usage: lsqb_params.py --sf 1 [--per 40] [--seed 7]
"""
import argparse, csv, os, random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

Q1 = ('MATCH (country:Country)<-[:City_isPartOf_Country]-(:City)<-[:Person_isLocatedIn_City]-(:Person)'
      '<-[:Forum_hasMember_Person]-(:Forum)-[:Forum_containerOf_Message]->(:Message)<-[:Message_replyOf_Message]-'
      '(:Message)-[:Message_hasTag_Tag]->(:Tag)-[:Tag_hasType_TagClass]->(tc:TagClass)')
Q2 = ('MATCH (person1:Person)-[:Person_knows_Person]->(person2:Person), (person1)<-[:Message_hasCreator_Person]-'
      '(comment:Message)-[:Comment_replyOf_Post]->(post:Message)-[:Message_hasCreator_Person]->(person2)')
Q3 = ('MATCH (person1:Person)-[:Person_isLocatedIn_City]->(city1:City)-[:City_isPartOf_Country]->(country:Country), '
      '(person2:Person)-[:Person_isLocatedIn_City]->(city2:City)-[:City_isPartOf_Country]->(country), '
      '(person3:Person)-[:Person_isLocatedIn_City]->(city3:City)-[:City_isPartOf_Country]->(country), '
      '(person1)-[:Person_knows_Person]->(person2)-[:Person_knows_Person]->(person3)-[:Person_knows_Person]->(person1)')
Q4 = ('MATCH (tag:Tag)<-[:Message_hasTag_Tag]-(message:Message)-[:Message_hasCreator_Person]->(creator:Person), '
      '(message)<-[:Person_likes_Message]-(liker:Person), (message)<-[:Message_replyOf_Message]-(comment:Message)')
Q5 = ('MATCH (tag1:Tag)<-[:Message_hasTag_Tag]-(message:Message)<-[:Message_replyOf_Message]-(comment:Message)'
      '-[:Message_hasTag_Tag]->(tag2:Tag)')
Q6 = ('MATCH (person1:Person)-[:Person_knows_Person]->(person2:Person)-[:Person_knows_Person]->(person3:Person)'
      '-[:Person_hasInterest_Tag]->(tag:Tag)')


def ids(sf, table):
    path = os.path.join(ROOT, f'data/raw/lsqb/social-network-sf{sf}-merged-fk/{table}.csv')
    with open(path) as f:
        next(f)
        return [int(l.split('|', 1)[0]) for l in f if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sf', default='1')
    ap.add_argument('--per', type=int, default=40)
    ap.add_argument('--seed', type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    country, person, tag, tagclass = ids(a.sf, 'Country'), ids(a.sf, 'Person'), ids(a.sf, 'Tag'), ids(a.sf, 'TagClass')
    templates = [
        ('q1c', lambda: (f'{Q1} WHERE country.CountryId = {{0}}', [rng.choice(country)])),
        ('q1t', lambda: (f'{Q1} WHERE tc.TagClassId = {{0}}', [rng.choice(tagclass)])),
        ('q1ct', lambda: (f'{Q1} WHERE country.CountryId = {{0}} AND tc.TagClassId = {{1}}',
                          [rng.choice(country), rng.choice(tagclass)])),
        ('q2p', lambda: (f'{Q2} WHERE person1.PersonId = {{0}}', [rng.choice(person)])),
        ('q3c', lambda: (f'{Q3} WHERE country.CountryId = {{0}}', [rng.choice(country)])),
        ('q4t', lambda: (f'{Q4} WHERE tag.TagId = {{0}}', [rng.choice(tag)])),
        ('q5t', lambda: (f'{Q5} WHERE tag1.TagId = {{0}}', [rng.choice(tag)])),
        ('q6t', lambda: (f'{Q6} WHERE tag.TagId = {{0}}', [rng.choice(tag)])),
    ]
    out = os.path.join(ROOT, f'queries/lsqb_p_sf{a.sf}.txt')
    qid = 0
    with open(out, 'w') as f, open(out + '.meta.csv', 'w', newline='') as m:
        w = csv.writer(m)
        w.writerow(['qid', 'template', 'params'])
        for name, make in templates:
            for _ in range(a.per):
                qid += 1
                text, params = make()
                f.write(f'id={qid} cypher={text.format(*params)} RETURN count(*)\n')
                w.writerow([qid, name, ';'.join(map(str, params))])
    print('wrote', out, qid, 'queries')


if __name__ == '__main__':
    main()
