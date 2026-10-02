#!/usr/bin/env python3
"""
Convert a Yomitan JA-RU dictionary (Kolobok, Jitendex-based) into a
JMdict-format XML file that yomikiri-dictionary-generator can read as
`jmdict_english.xml`.

Usage:
  python kolobok_to_jmdict.py KOLOBOK.zip OUT.xml [--orig ORIGINAL_JMDICT.xml]

--orig is optional: if given, the "meta" entry (ent_seq 9999999, holds the
dictionary creation date) is copied from it verbatim.
"""
import argparse
import json
import re
import sys
import zipfile
from collections import OrderedDict, defaultdict
from xml.sax.saxutils import escape

# Row-level tags are separated by a normal space; the tag names themselves
# contain a non-breaking space (\xa0), so never use str.split() without args.
NB = "\xa0"
T_POPULAR = "★"
T_FREQ = "приор." + NB + "форма"
T_IRREG = "нерег." + NB + "форма"
T_OLDKANJI = "стар." + NB + "кандзи"
T_OLDREAD = "устар." + NB + "чтение"
T_RARE = "редк." + NB + "форма"
T_ATEJI = "атэдзи"
T_SPECIAL = "особ." + NB + "чтение"

SKIP = {"xref", "antonym", "example-sentence", "lang-source", "forms",
        "attribution", "graphic", "redirect-glossary"}
INFO_KINDS = {"misc-info": "misc", "field-info": "field", "dialect-info": "dial"}


def kind(node):
    d = node.get("data") if isinstance(node, dict) else None
    return (d or {}).get("content")


def code(node):
    return ((node.get("data") or {}).get("code"))


def text_of(n):
    if n is None:
        return ""
    if isinstance(n, str):
        return n
    if isinstance(n, list):
        return "".join(text_of(x) for x in n)
    if isinstance(n, dict):
        return text_of(n.get("content"))
    return ""


def iter_nodes(n, stop=SKIP):
    """Yield all descendant dict nodes, not descending into `stop` kinds
    (the stopped node itself is not yielded either)."""
    if isinstance(n, list):
        for x in n:
            yield from iter_nodes(x, stop)
    elif isinstance(n, dict):
        k = kind(n)
        if k in stop:
            return
        yield n
        yield from iter_nodes(n.get("content"), stop)


def collect_info(n, out):
    """Collect misc/field/dialect codes under n, not entering senses."""
    for x in iter_nodes(n, SKIP | {"sense"}):
        k = kind(x)
        if k in INFO_KINDS and code(x):
            out[INFO_KINDS[k]].append(code(x))


def parse_senses(content):
    """-> list of dict(pos=[], misc=[], field=[], dial=[], gloss=[], inf=[])"""
    senses = []
    groups = [g for g in _find(content, "sense-group")]
    for g in groups:
        gpos, ginfo = [], defaultdict(list)
        for x in iter_nodes(g.get("content"), SKIP | {"sense"}):
            if kind(x) == "part-of-speech-info" and code(x):
                gpos.append(code(x))
        collect_info(g.get("content"), ginfo)
        for s in _find(g.get("content"), "sense"):
            sinfo = defaultdict(list)
            collect_info(s.get("content"), sinfo)
            gloss, inf, expl = [], [], []
            for x in iter_nodes(s.get("content"), SKIP):
                k = kind(x)
                if k == "glossary":
                    for li in _children(x):
                        t = text_of(li).strip()
                        if t:
                            gloss.append(t)
                elif k == "sense-note-content":
                    t = text_of(x).strip()
                    if t:
                        inf.append(t)
                elif k == "info-gloss-content":
                    t = text_of(x).strip()
                    if t:
                        expl.append(t)
            if not gloss:
                gloss = expl  # entries that only have an explanation
            elif expl:
                inf += expl
            if not gloss:
                continue
            senses.append({
                "pos": gpos,
                "misc": ginfo["misc"] + sinfo["misc"],
                "field": ginfo["field"] + sinfo["field"],
                "dial": ginfo["dial"] + sinfo["dial"],
                "gloss": gloss,
                "inf": inf,
            })
    return senses


def _children(node):
    c = node.get("content")
    if isinstance(c, list):
        return [x for x in c if x is not None]
    return [c] if c is not None else []


def _find(n, k):
    """Find top-most descendant nodes of kind k (not nested in each other)."""
    if isinstance(n, list):
        for x in n:
            yield from _find(x, k)
    elif isinstance(n, dict):
        if kind(n) == k:
            yield n
        elif kind(n) in SKIP:
            return
        else:
            yield from _find(n.get("content"), k)


def uniq(seq):
    return list(OrderedDict.fromkeys(seq))


def build_entry(seq, rows):
    pairs = []  # (term, reading, tags:set)
    for r in rows:
        term, reading = r[0], r[1]
        if not reading:
            reading = term
        tags = set(r[2].split(" ")) if r[2] else set()
        tags.discard("")
        pairs.append((term, reading, tags))

    kanjis = uniq(t for t, rd, _ in pairs if t != rd)
    readings = uniq(rd for _, rd, _ in pairs)
    if not readings:
        return None

    # kanji-level info / priority
    k_inf, k_pri = {}, {}
    for kj in kanjis:
        rs = [tg for t, rd, tg in pairs if t == kj]
        all_have = lambda tag: all(tag in tg for tg in rs)
        any_have = lambda tag: any(tag in tg for tg in rs)
        inf = []
        if all_have(T_IRREG):
            inf.append("iK")
        if all_have(T_OLDKANJI):
            inf.append("oK")
        if all_have(T_RARE):
            inf.append("rK")
        if any_have(T_ATEJI):
            inf.append("ateji")
        k_inf[kj] = inf
        k_pri[kj] = any_have(T_POPULAR)

    # reading-level info / priority
    r_inf, r_pri = {}, {}
    for rd in readings:
        rs = [(t, tg) for t, r2, tg in pairs if r2 == rd]
        kana_rows = [tg for t, tg in rs if t == rd]
        inf = []
        # tags on kana-only rows describe the reading itself
        if kana_rows and all(T_IRREG in tg for tg in kana_rows):
            inf.append("ik")
        if kana_rows and all(T_RARE in tg for tg in kana_rows):
            inf.append("rk")
        if any(T_OLDREAD in tg for _, tg in rs):
            inf.append("ok")
        if any(T_SPECIAL in tg for _, tg in rs):
            inf.append("gikun")
        r_inf[rd] = inf
        r_pri[rd] = any(T_POPULAR in tg for _, tg in rs)

    out = [f"<entry>\n<ent_seq>{seq}</ent_seq>\n"]
    for kj in kanjis:
        out.append(f"<k_ele>\n<keb>{escape(kj)}</keb>\n")
        for i in k_inf[kj]:
            out.append(f"<ke_inf>&{i};</ke_inf>\n")
        if k_pri[kj]:
            out.append("<ke_pri>news1</ke_pri>\n")
        out.append("</k_ele>\n")
    for rd in readings:
        partners = uniq(t for t, r2, _ in pairs if r2 == rd and t != rd)
        out.append(f"<r_ele>\n<reb>{escape(rd)}</reb>\n")
        if kanjis and not partners:
            out.append("<re_nokanji/>\n")
        elif partners and set(partners) != set(kanjis):
            for p in partners:
                out.append(f"<re_restr>{escape(p)}</re_restr>\n")
        for i in r_inf[rd]:
            out.append(f"<re_inf>&{i};</re_inf>\n")
        if r_pri[rd]:
            out.append("<re_pri>news1</re_pri>\n")
        out.append("</r_ele>\n")

    senses = parse_senses(rows[0][5])
    if not senses:
        return None
    for s in senses:
        out.append("<sense>\n")
        for p in uniq(s["pos"]):
            out.append(f"<pos>&{p};</pos>\n")
        for f in uniq(s["field"]):
            out.append(f"<field>&{f};</field>\n")
        for m in uniq(s["misc"]):
            out.append(f"<misc>&{m};</misc>\n")
        for d in uniq(s["dial"]):
            out.append(f"<dial>&{d};</dial>\n")
        for i in s["inf"]:
            out.append(f"<s_inf>{escape(i)}</s_inf>\n")
        for g in s["gloss"]:
            out.append(f"<gloss>{escape(g)}</gloss>\n")
        out.append("</sense>\n")
    out.append("</entry>\n")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zip")
    ap.add_argument("out")
    ap.add_argument("--orig", help="original JMdict_e xml to copy meta entry from")
    a = ap.parse_args()

    by_seq = defaultdict(list)
    with zipfile.ZipFile(a.zip) as z:
        banks = sorted(n for n in z.namelist() if re.match(r"term_bank_\d+\.json$", n))
        for n in banks:
            for row in json.loads(z.read(n)):
                seq = row[6]
                if isinstance(seq, int) and seq > 0 and row[0]:
                    by_seq[seq].append(row)

    meta = ""
    if a.orig:
        txt = open(a.orig, encoding="utf-8").read()
        m = re.search(r"<entry>\s*<ent_seq>9999999</ent_seq>.*?</entry>", txt, re.S)
        if m:
            meta = m.group(0) + "\n"
        else:
            print("warning: meta entry not found in --orig", file=sys.stderr)

    written = skipped = 0
    with open(a.out, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<JMdict>\n')
        for seq in sorted(by_seq):
            e = build_entry(seq, by_seq[seq])
            if e is None:
                skipped += 1
                continue
            f.write(e)
            written += 1
        f.write(meta)
        f.write("</JMdict>\n")
    print(f"entries written: {written}, skipped (no senses/readings): {skipped}")


if __name__ == "__main__":
    main()
