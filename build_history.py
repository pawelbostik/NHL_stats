#!/usr/bin/env python3
"""Historické sezony NHL (od 2007/08) pro výběr sezony na stránce.

Stáhne pro každou uzavřenou sezonu tabulku, statistiky hráčů a brankářů (NHL.com),
pokročilé statistiky, formace a jednotlivé střely (MoneyPuck), speciální formace
(NHL stats) a od sezony 2021/22 i sledovací data NHL EDGE. Výsledek uloží do
site/hist/<sezona>/. Uzavřené sezony se už nemění, takže se stahují jen jednou;
znovu se stáhnou jen chybějící soubory (nebo vše při HIST_FORCE=1).

Navíc vytvoří kariéru a osobní údaje všech hráčů z historických sezon
(site/hist/careers/<id % 32>.json), které stránka načítá podle potřeby.
"""
import json
import os
import time

import build as b

FIRST = int(os.environ.get("HIST_FIRST", "2007"))
LAST = int(b.SEASON[:4]) - 1
FORCE = os.environ.get("HIST_FORCE") == "1"
HIST = os.path.join(b.SITE, "hist")
NEED = ["data.json", "mp.json", "lines.json", "shots.json", "goalies_shots.json", "special.json"]
SHARDS = 32


def wj(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    b.log("  zapsáno %s (%d B)" % (os.path.relpath(path, b.SITE), os.path.getsize(path)))


def season_end_dates():
    out = {}
    for s in b.jget(b.NHL + "/standings-season").get("seasons", []):
        out[str(s["id"])] = s.get("standingsEnd")
    return out


def team_ids():
    try:
        for t in b.jget(b.REST + "/team").get("data", []):
            if t.get("id") and t.get("triCode"):
                b.TID[t["id"]] = t["triCode"]
    except Exception as e:  # noqa: BLE001
        b.log("  seznam týmů: %s" % e)


def hist_nhl(sid, end):
    st = b.jget("%s/standings/%s" % (b.NHL, end)).get("standings", [])
    tm, tx = [], {}
    for t in st:
        ab = t["teamAbbrev"]["default"]
        b.TNAME[b.norm_name((t.get("teamName") or {}).get("default", ""))] = ab
        conf = (t.get("conferenceName") or " ")[0].upper()
        streak = (t.get("streakCode") or "") + (str(t.get("streakCount")) if t.get("streakCount") else "")
        tm.append([ab, (t.get("teamCommonName") or {}).get("default", ab), (t.get("placeName") or {}).get("default", ""),
                   conf if conf in "EW" else "", t.get("divisionName", ""), t.get("gamesPlayed", 0), t.get("wins", 0),
                   t.get("losses", 0), t.get("otLosses", 0), t.get("points", 0), t.get("goalFor", 0), t.get("goalAgainst", 0), streak])
        tx[ab] = [t.get(k) or 0 for k in ("homeWins", "homeLosses", "homeOtLosses", "roadWins", "roadLosses", "roadOtLosses",
                                           "l10Wins", "l10Losses", "l10OtLosses", "regulationWins", "regulationPlusOtWins",
                                           "shootoutWins", "shootoutLosses", "leagueSequence", "conferenceSequence",
                                           "divisionSequence", "wildcardSequence", "homeGoalsFor", "homeGoalsAgainst",
                                           "roadGoalsFor", "roadGoalsAgainst", "l10GoalsFor", "l10GoalsAgainst")]
    nat = {}
    for kind in ("skater", "goalie"):
        for r in b.rest(kind, "bios"):
            if r.get("playerId"):
                nat[r["playerId"]] = r.get("birthCountryCode") or r.get("nationalityCode")

    def split(full, last):
        full, last = full or "", last or ""
        return (full[:-len(last)].strip() if last and full.endswith(last) else full.split(" ")[0]), last or full

    def team_of(r):
        return ((r.get("teamAbbrevs") or "").split(",") or [""])[-1].strip()
    sk = []
    for r in b.rest("skater", "summary"):
        first, last = split(r.get("skaterFullName"), r.get("lastName"))
        sk.append([r["playerId"], first, last, team_of(r), r.get("positionCode", ""), r.get("gamesPlayed") or 0,
                   r.get("goals") or 0, r.get("assists") or 0, r.get("points") or 0, r.get("plusMinus") or 0,
                   r.get("penaltyMinutes") or 0, r.get("ppGoals") or 0, r.get("shGoals") or 0, r.get("gameWinningGoals") or 0,
                   r.get("otGoals") or 0, r.get("shots") or 0, b.r4(r.get("shootingPct") or 0), round(r.get("timeOnIcePerGame") or 0),
                   b.r4(r.get("faceoffWinPct") or 0), nat.get(r["playerId"]), None])
    gk = []
    for r in b.rest("goalie", "summary"):
        first, last = split(r.get("goalieFullName"), r.get("lastName"))
        gk.append([r["playerId"], first, last, team_of(r), r.get("gamesPlayed") or 0, r.get("gamesStarted") or 0,
                   r.get("wins") or 0, r.get("losses") or 0, (r.get("otLosses") or 0) + (r.get("ties") or 0),
                   b.r4(r.get("goalsAgainstAverage") or 0), round(float(r.get("savePct") or 0), 4), r.get("shotsAgainst") or 0,
                   r.get("saves") or 0, r.get("goalsAgainst") or 0, r.get("shutouts") or 0, r.get("timeOnIce") or 0,
                   nat.get(r["playerId"]), None])
    b.log("  %s: týmů %d, hráčů %d, brankářů %d" % (sid, len(tm), len(sk), len(gk)))
    return {"sk": sk, "gk": gk, "tm": tm, "tx": tx, "updated": end, "season": sid, "final": True}


def build_season(y, ends):
    sid = "%d%d" % (y, y + 1)
    d = os.path.join(HIST, sid)
    have = set(os.listdir(d)) if os.path.isdir(d) else set()
    want = NEED + (["edge.json"] if y >= 2021 else [])
    if not FORCE and all(n in have for n in want):
        b.log("Sezona %s už je stažená" % sid)
        return sid, json.load(open(os.path.join(d, "data.json"), encoding="utf-8"))
    b.log("Sezona %s" % sid)
    b.SEASON, b.MP_YEAR = sid, str(y)
    b.MP = "https://moneypuck.com/moneypuck/playerData/seasonSummary/%d/regular/" % y
    b.MP_SHOTS = "https://peter-tanner.com/moneypuck/downloads/shots_%d.zip" % y
    data = None
    if FORCE or "data.json" not in have:
        data = b.step("NHL %s" % sid, lambda: hist_nhl(sid, ends.get(sid)))
        if data:
            wj(os.path.join(d, "data.json"), data)
    if data is None and os.path.exists(os.path.join(d, "data.json")):
        data = json.load(open(os.path.join(d, "data.json"), encoding="utf-8"))
    jobs = [("special.json", b.build_special), ("mp.json", b.build_mp), ("lines.json", b.build_lines)]
    for name, fn in jobs:
        if FORCE or name not in have:
            out = b.step("%s %s" % (name, sid), fn)
            if out:
                wj(os.path.join(d, name), out)
    if FORCE or "shots.json" not in have or "goalies_shots.json" not in have:
        sh = b.step("střely %s" % sid, b.build_shots)
        if sh:
            wj(os.path.join(d, "shots.json"), sh[0])
            wj(os.path.join(d, "goalies_shots.json"), sh[1])
    if y >= 2021 and data and (FORCE or "edge.json" not in have):
        ed = b.step("EDGE %s" % sid, lambda: b.build_edge(data))
        if ed:
            wj(os.path.join(d, "edge.json"), ed)
    fix_phx(d, data)
    po = os.path.join(d, "po")
    if data and (FORCE or not os.path.exists(os.path.join(po, "data.json"))) and os.environ.get("HIST_PO", "1") == "1":
        b.SEASON = sid
        b.step("play-off %s" % sid, lambda: b.build_playoffs(sid, y, po, data, wj))
        fix_phx(po, data)
    return sid, data


def fix_phx(d, data):
    """MoneyPuck označuje Phoenix kódem ARI i v sezonách, kdy NHL používala PHX. Sjednotí kódy podle NHL."""
    if not data or "PHX" not in {t[0] for t in data.get("tm", [])}:
        return
    for name in ("mp.json", "lines.json", "shots.json", "goalies_shots.json", "edge.json"):
        path = os.path.join(d, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            txt = f.read()
        new = txt.replace('"ARI"', '"PHX"').replace('-ARI"', '-PHX"')
        if new != txt:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            b.log("  %s: ARI -> PHX" % name)


def build_careers_hist(all_ids):
    """Kariéra a osobní údaje hráčů z historických sezon, rozdělená do menších souborů."""
    cur = b.rjson(os.path.join(b.SITE, "careers.json"), {}) or {}
    cdir = os.path.join(HIST, "careers")
    old = {}
    for i in range(SHARDS):
        old.update(b.rjson(os.path.join(cdir, "%d.json" % i), {}) or {})
    todo = sorted(pid for pid in all_ids if str(pid) not in cur and (str(pid) not in old or "aw" not in old[str(pid)]))
    b.log("Kariéra historických hráčů: %d nových, %d už staženo" % (len(todo), len(old)))
    if todo:
        fake = {"sk": [[pid] + [None] * 20 for pid in todo], "gk": []}
        got = b.build_careers(fake) or {}
        old.update(got)
    shards = [{} for _ in range(SHARDS)]
    for k, v in old.items():
        shards[int(k) % SHARDS][k] = v
    for i, sh in enumerate(shards):
        wj(os.path.join(cdir, "%d.json" % i), sh)


def build_indexes(seasons):
    """Pokročilá kariéra po sezonách (z MoneyPuck souhrnů v archivu), nejlepší sezony a čeští hráči."""
    adv = [{} for _ in range(SHARDS)]
    best = {"p": [], "g": [], "ixg": [], "gax": [], "gsax": [], "svp": []}
    czech = {}
    for sid in seasons:
        d = os.path.join(HIST, sid)
        data = b.rjson(os.path.join(d, "data.json"), {}) or {}
        mp = b.rjson(os.path.join(d, "mp.json"), {}) or {}
        names = {r[0]: (r[1] + " " + r[2]).strip() for r in data.get("sk", [])}
        names.update({r[0]: (r[1] + " " + r[2]).strip() for r in data.get("gk", [])})
        nat = {r[0]: r[19] for r in data.get("sk", [])}
        nat.update({r[0]: r[16] for r in data.get("gk", [])})
        for r in data.get("sk", []):
            best["p"].append([r[8], r[0], names[r[0]], r[3], sid, r[5]])
            best["g"].append([r[6], r[0], names[r[0]], r[3], sid, r[5]])
            if nat.get(r[0]) in ("CZE", "SVK"):
                c = czech.setdefault(r[0], {"n": names[r[0]], "nat": nat[r[0]], "s": [], "g": 0})
                c["s"].append([sid, r[3], r[5], r[6], r[7], r[8]])
        for r in data.get("gk", []):
            if r[4] >= 25:
                best["svp"].append([r[10], r[0], names[r[0]], r[3], sid, r[4]])
            if nat.get(r[0]) in ("CZE", "SVK"):
                c = czech.setdefault(r[0], {"n": names[r[0]], "nat": nat[r[0]], "s": [], "g": 1})
                c["g"] = 1
                c["s"].append([sid, r[3], r[4], r[6], r[10], r[14]])
        for m in mp.get("sk", []):
            pid, gp = m[0], m[2]
            if not gp:
                continue
            gax = round(m[6] - m[5], 1)
            adv[pid % SHARDS].setdefault(str(pid), []).append([int(sid), m[1], gp, m[3], m[5], m[6], m[24], m[25], round(m[4] / gp, 2) if gp else 0, m[9], m[10]])
            if pid in names:
                best["ixg"].append([m[5], pid, names[pid], m[1], sid, gp])
                best["gax"].append([gax, pid, names[pid], m[1], sid, gp])
        for m in mp.get("gk", []):
            pid, gp = m[0], m[2]
            if not gp:
                continue
            gsax = round(m[4] - m[5], 1)
            adv[pid % SHARDS].setdefault(str(pid), []).append([int(sid), m[1], gp, m[3], m[4], m[5], m[6], gsax, None, None, None, "g"])
            if pid in names:
                best["gsax"].append([gsax, pid, names[pid], m[1], sid, gp])
    for k in best:
        best[k] = sorted(best[k], key=lambda x: -(x[0] or 0))[:50]
    for i, sh in enumerate(adv):
        wj(os.path.join(HIST, "advc", "%d.json" % i), sh)
    wj(os.path.join(HIST, "best.json"), best)
    wj(os.path.join(HIST, "czech.json"), czech)


def main():
    t0 = time.time()
    team_ids()
    ends = season_end_dates()
    seasons, ids = [], set()
    for y in range(LAST, FIRST - 1, -1):
        sid, data = build_season(y, ends)
        if data:
            seasons.append(sid)
            ids |= {r[0] for r in data.get("sk", [])} | {r[0] for r in data.get("gk", [])}
    b.SEASON = os.environ.get("SEASON", "20262027")
    if os.environ.get("HIST_CAREERS", "1") == "1":
        b.step("kariéra historických hráčů", lambda: build_careers_hist(ids))
    b.step("indexy archivu", lambda: build_indexes(seasons))
    po = [sid for sid in seasons if os.path.exists(os.path.join(HIST, sid, "po", "data.json"))]
    wj(os.path.join(HIST, "index.json"), {"current": b.SEASON, "seasons": seasons, "shards": SHARDS, "po": po,
                                          "edge_from": "20212022", "updated": time.strftime("%Y-%m-%d")})
    b.log("Hotovo za %d s" % (time.time() - t0))


if __name__ == "__main__":
    main()
