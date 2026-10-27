#!/usr/bin/env python3
"""Stáhne data NHL a MoneyPuck a sestaví statickou stránku do složky site/.

Spouští se automaticky přes GitHub Actions (viz .github/workflows/update.yml).
Používá jen standardní knihovnu Pythonu.

Zdroje:
  - api-web.nhle.com (oficiální statistiky, tabulka, zápisy a události zápasů)
  - MoneyPuck.com (xG, Corsi, GSAx, formace, data jednotlivých střel) – zdarma
    pro nekomerční použití s uvedením zdroje.
"""
import csv
import io
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import OrderedDict, defaultdict

SEASON = os.environ.get("SEASON", "20262027")
MP_YEAR = SEASON[:4]
ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")
CACHE = os.path.join(ROOT, "cache")
GCACHE = os.path.join(CACHE, "games")
NHL = "https://api-web.nhle.com/v1"
REST = "https://api.nhle.com/stats/rest/en"
TID, FUT, TNAME = {}, {}, {}
MP = "https://moneypuck.com/moneypuck/playerData/seasonSummary/%s/regular/" % MP_YEAR
MP_SHOTS = "https://peter-tanner.com/moneypuck/downloads/shots_%s.zip" % MP_YEAR
UA = "Mozilla/5.0 (compatible; nhl-statistiky/1.0; personal non-commercial stats page)"
FIX = {"T.B": "TBL", "N.J": "NJD", "L.A": "LAK", "S.J": "SJS"}
B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

os.makedirs(SITE, exist_ok=True)
os.makedirs(GCACHE, exist_ok=True)


def log(*a):
    print(*a, flush=True)


def get(url, tries=4, timeout=60):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 404):
                break
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(2 * (i + 1))
    raise RuntimeError("Stažení selhalo: %s (%s)" % (url, last))


def jget(url):
    return json.loads(get(url))


def wjson(name, obj):
    path = os.path.join(SITE, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    log("  zapsáno %s (%d B)" % (name, os.path.getsize(path)))


def rjson(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def fix(t):
    return FIX.get(t, t)


def r4(v):
    return round(float(v), 4)


def c1(v):
    v = int(v)
    return B64[max(0, min(63, v))]


def c2(v):
    v = max(0, min(4095, int(v)))
    return B64[v >> 6] + B64[v & 63]


def norm_name(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if c.isalnum()).lower()


def sec(t):
    if not t:
        return 0
    m, s = t.split(":")
    return int(m) * 60 + int(s)


# ---------------------------------------------------------------- NHL: tabulka, hráči, brankáři
def build_nhl():
    log("NHL: tabulka")
    st = jget(NHL + "/standings/now")["standings"]
    tm = []
    for t in st:
        streak = (t.get("streakCode") or "") + (str(t.get("streakCount")) if t.get("streakCount") else "")
        tm.append([t["teamAbbrev"]["default"], t["teamCommonName"]["default"], t["placeName"]["default"],
                   t.get("conferenceAbbrev", ""), t.get("divisionName", ""), t["gamesPlayed"], t["wins"],
                   t["losses"], t["otLosses"], t["points"], t["goalFor"], t["goalAgainst"], streak])
    teams = [t[0] for t in tm]
    tx = {}
    for t in st:
        ab = t["teamAbbrev"]["default"]
        TNAME[norm_name((t.get("teamName") or {}).get("default", ""))] = ab
        tx[ab] = [t.get(k) or 0 for k in ("homeWins", "homeLosses", "homeOtLosses", "roadWins", "roadLosses", "roadOtLosses",
                                           "l10Wins", "l10Losses", "l10OtLosses", "regulationWins", "regulationPlusOtWins",
                                           "shootoutWins", "shootoutLosses", "leagueSequence", "conferenceSequence",
                                           "divisionSequence", "wildcardSequence", "homeGoalsFor", "homeGoalsAgainst",
                                           "roadGoalsFor", "roadGoalsAgainst", "l10GoalsFor", "l10GoalsAgainst")]

    natf = os.path.join(CACHE, "nat.json")
    nat = rjson(natf, {}) or {}
    sk, gk, num = [], [], {}
    log("NHL: statistiky a soupisky %d týmů" % len(teams))
    for ab in teams:
        try:
            ro = jget("%s/roster/%s/%s" % (NHL, ab, SEASON))
            for grp in ("forwards", "defensemen", "goalies"):
                for p in ro.get(grp, []):
                    if p.get("birthCountry"):
                        nat[str(p["id"])] = p["birthCountry"]
                    if p.get("sweaterNumber") is not None:
                        num[(p["id"], ab)] = p["sweaterNumber"]
        except Exception as e:  # noqa: BLE001
            log("  soupiska %s: %s" % (ab, e))
        cs = jget("%s/club-stats/%s/%s/2" % (NHL, ab, SEASON))
        for p in cs.get("skaters", []):
            sk.append([p["playerId"], p["firstName"]["default"], p["lastName"]["default"], ab, p.get("positionCode", ""),
                       p.get("gamesPlayed", 0), p.get("goals", 0), p.get("assists", 0), p.get("points", 0),
                       p.get("plusMinus", 0), p.get("penaltyMinutes", 0), p.get("powerPlayGoals", 0),
                       p.get("shorthandedGoals", 0), p.get("gameWinningGoals", 0), p.get("overtimeGoals", 0),
                       p.get("shots", 0), r4(p.get("shootingPctg") or 0), round(p.get("avgTimeOnIcePerGame") or 0),
                       r4(p.get("faceoffWinPctg") or 0), None, num.get((p["playerId"], ab))])
        for p in cs.get("goalies", []):
            gk.append([p["playerId"], p["firstName"]["default"], p["lastName"]["default"], ab,
                       p.get("gamesPlayed", 0), p.get("gamesStarted", 0), p.get("wins", 0), p.get("losses", 0),
                       p.get("overtimeLosses", 0), r4(p.get("goalsAgainstAverage") or 0),
                       round(float(p.get("savePercentage") or 0), 4), p.get("shotsAgainst", 0), p.get("saves", 0),
                       p.get("goalsAgainst", 0), p.get("shutouts", 0), p.get("timeOnIce", 0), None,
                       num.get((p["playerId"], ab))])
        time.sleep(0.1)
    for rows, ni in ((sk, 19), (gk, 16)):
        for r in rows:
            k = str(r[0])
            if k not in nat:
                try:
                    nat[k] = jget("%s/player/%s/landing" % (NHL, k)).get("birthCountry") or ""
                except Exception:  # noqa: BLE001
                    nat[k] = ""
            r[ni] = nat.get(k) or None
    with open(natf, "w", encoding="utf-8") as f:
        json.dump(nat, f, separators=(",", ":"))
    log("  hráčů %d, brankářů %d" % (len(sk), len(gk)))
    return {"sk": sk, "gk": gk, "tm": tm, "tx": tx}, teams


# ---------------------------------------------------------------- NHL: kariéra a osobní údaje
def _landing(pid):
    try:
        return pid, jget("%s/player/%s/landing" % (NHL, pid))
    except Exception as e:  # noqa: BLE001
        return pid, e


def build_careers(data):
    from concurrent.futures import ThreadPoolExecutor
    ids = sorted({r[0] for r in data["sk"]} | {r[0] for r in data["gk"]})
    goalies = {r[0] for r in data["gk"]}
    log("NHL: kariéra %d hráčů" % len(ids))
    out, fails, sample = {}, 0, None
    with ThreadPoolExecutor(max_workers=8) as ex:
        for pid, L in ex.map(_landing, ids):
            if isinstance(L, Exception):
                fails += 1
                continue
            if sample is None:
                sample = L
            g = pid in goalies or L.get("position") == "G"
            dd = L.get("draftDetails") or {}
            rows = []
            for t in L.get("seasonTotals") or []:
                gt = t.get("gameTypeId")
                lg = t.get("leagueAbbrev") or ""
                if gt != 2 and not (gt == 3 and lg == "NHL"):
                    continue
                team = (t.get("teamName") or {}).get("default") or ""
                base = [t.get("season"), gt, lg, team, t.get("gamesPlayed") or 0]
                if g:
                    gaa = t.get("goalsAgainstAvg")
                    svp = t.get("savePctg")
                    rows.append(base + [t.get("wins"), t.get("losses"), t.get("otLosses") if t.get("otLosses") is not None else t.get("ties"),
                                        round(gaa, 2) if isinstance(gaa, (int, float)) else None,
                                        round(svp, 3) if isinstance(svp, (int, float)) else None, t.get("shutouts")])
                else:
                    rows.append(base + [t.get("goals"), t.get("assists"), t.get("points"), t.get("plusMinus"), t.get("pim")])
            out[str(pid)] = {
                "n": L.get("sweaterNumber"), "p": L.get("position"), "h": L.get("heightInCentimeters"),
                "w": L.get("weightInKilograms"), "b": L.get("birthDate"),
                "c": (L.get("birthCity") or {}).get("default"), "co": L.get("birthCountry"),
                "s": L.get("shootsCatches"),
                "d": [dd.get("year"), dd.get("teamAbbrev"), dd.get("round"), dd.get("pickInRound"), dd.get("overallPick")] if dd else None,
                "g": 1 if g else 0, "t": rows}
    if sample is not None:
        with open(os.path.join(CACHE, "sample_landing.json"), "w", encoding="utf-8") as f:
            json.dump({k: (v if not isinstance(v, list) else v[:3]) for k, v in sample.items()}, f, ensure_ascii=False, indent=1)
    for rows, ni in ((data["sk"], 20), (data["gk"], 17)):
        for r in rows:
            c = out.get(str(r[0]))
            if r[ni] is None and c and c.get("n") is not None:
                r[ni] = c["n"]
    log("  hotovo, neúspěšných %d" % fails)
    return out


# ---------------------------------------------------------------- NHL: zápasy (zápis + události)
SHT = ["wrist", "snap", "slap", "backhand", "tip-in", "deflected", "wrap-around", "poke", "bat", "between-legs", "cradle"]


def extract_game(gid):
    b = jget("%s/gamecenter/%d/boxscore" % (NHL, gid))
    p = jget("%s/gamecenter/%d/play-by-play" % (NHL, gid))
    hid = p["homeTeam"]["id"]
    ext = defaultdict(lambda: [0, 0, 0, 0])  # fw, fl, mis, sb
    go, pe = [], []
    for pl in p.get("plays", []):
        d = pl.get("details") or {}
        t = pl.get("typeDescKey")
        per = pl.get("periodDescriptor") or {}
        so = per.get("periodType") == "SO"
        if t == "faceoff":
            if d.get("winningPlayerId"):
                ext[d["winningPlayerId"]][0] += 1
            if d.get("losingPlayerId"):
                ext[d["losingPlayerId"]][1] += 1
        elif t == "missed-shot" and d.get("shootingPlayerId") and not so:
            ext[d["shootingPlayerId"]][2] += 1
        elif t == "blocked-shot" and d.get("shootingPlayerId"):
            ext[d["shootingPlayerId"]][3] += 1
        elif t == "goal" and not so:
            side = 1 if d.get("eventOwnerTeamId") == hid else 0
            sc = pl.get("situationCode") or "1551"
            ag, as_, hs, hg = int(sc[0]), int(sc[1]), int(sc[2]), int(sc[3])
            own, opp, opp_g = (hs, as_, ag) if side else (as_, hs, hg)
            stt = 4 if own + opp <= 2 else 3 if opp_g == 0 else 1 if own > opp else 2 if own < opp else 0
            ty = SHT.index(d["shotType"]) if d.get("shotType") in SHT else 63
            go.append([per.get("number", 1), sec(pl.get("timeInPeriod")), stt, side, d.get("scoringPlayerId") or 0,
                       d.get("assist1PlayerId") or 0, d.get("assist2PlayerId") or 0, d.get("goalieInNetId") or 0, ty])
        elif t == "penalty" and not so:
            side = 1 if d.get("eventOwnerTeamId") == hid else 0
            pe.append([per.get("number", 1), sec(pl.get("timeInPeriod")), side,
                       d.get("committedByPlayerId") or d.get("servedByPlayerId") or 0, d.get("drawnByPlayerId") or 0,
                       min(63, d.get("duration") or 0), d.get("descKey") or "", 0 if d.get("committedByPlayerId") else 1])
    sk, gk = [], []
    for side, key in ((0, "awayTeam"), (1, "homeTeam")):
        T = (b.get("playerByGameStats") or {}).get(key) or {}
        for r in (T.get("forwards") or []) + (T.get("defense") or []):
            e = ext.get(r["playerId"], [0, 0, 0, 0])
            sk.append([r["playerId"], side, r.get("plusMinus", 0), r.get("pim", 0), r.get("sog", 0), e[2], e[3],
                       r.get("hits", 0), r.get("blockedShots", 0), r.get("giveaways", 0), r.get("takeaways", 0),
                       e[0], e[1], r.get("shifts", 0), sec(r.get("toi"))])
        for r in T.get("goalies") or []:
            def sp(x):
                a = (x or "0/0").split("/")
                return int(a[0]), int(a[1])
            evs, eva = sp(r.get("evenStrengthShotsAgainst"))
            pps, ppa = sp(r.get("powerPlayShotsAgainst"))
            shs, sha = sp(r.get("shorthandedShotsAgainst"))
            dec = {"W": 1, "L": 2, "O": 3}.get(r.get("decision"), 0)
            gk.append([r["playerId"], side, sec(r.get("toi")), r.get("shotsAgainst") or 0, r.get("saves") or 0,
                       eva, evs, ppa, pps, sha, shs, dec, 1 if r.get("starter") else 0])
    return {"id": gid, "state": b.get("gameState"), "date": b.get("gameDate"),
            "hs": b["homeTeam"].get("score", 0), "as": b["awayTeam"].get("score", 0),
            "lt": (b.get("gameOutcome") or {}).get("lastPeriodType", "REG"),
            "away": b["awayTeam"]["abbrev"], "home": b["homeTeam"]["abbrev"],
            "sk": sk, "gk": gk, "go": go, "pe": pe}


def completed_games(teams):
    ids = {}
    for ab in teams:
        sc = jget("%s/club-schedule-season/%s/%s" % (NHL, ab, SEASON))
        for g in sc.get("games", []):
            for side in ("awayTeam", "homeTeam"):
                t = g.get(side) or {}
                if t.get("id") and t.get("abbrev"):
                    TID[t["id"]] = t["abbrev"]
            if g.get("gameType") != 2:
                continue
            if g.get("gameState") in ("OFF", "FINAL"):
                ids[g["id"]] = g.get("gameDate")
            else:
                FUT[g["id"]] = [g["id"], g.get("startTimeUTC") or "", (g.get("awayTeam") or {}).get("abbrev", ""),
                                (g.get("homeTeam") or {}).get("abbrev", ""), (g.get("venue") or {}).get("default", ""),
                                g.get("gameState") or ""]
        time.sleep(0.05)
    return ids


def build_schedule():
    """Nadcházející zápasy základní části (příštích 21 dní) pro záložku Program."""
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for g in FUT.values():
        try:
            t = dt.datetime.strptime(g[1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        except Exception:  # noqa: BLE001
            continue
        if now - dt.timedelta(hours=6) <= t <= now + dt.timedelta(days=21):
            out.append(g)
    out.sort(key=lambda g: (g[1], g[0]))
    log("  nadcházejících zápasů %d" % len(out))
    return {"updated": now.strftime("%Y-%m-%dT%H:%MZ"), "g": out}


def build_games(teams):
    log("NHL: rozpis odehraných zápasů")
    done = completed_games(teams)
    log("  odehráno %d zápasů základní části" % len(done))
    games, new = [], 0
    for gid in sorted(done):
        path = os.path.join(GCACHE, "%d.json" % gid)
        g = rjson(path)
        if not g or g.get("state") != "OFF":
            try:
                g = extract_game(gid)
                new += 1
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(g, f, separators=(",", ":"))
                time.sleep(0.1)
            except Exception as e:  # noqa: BLE001
                log("  zápas %d: %s" % (gid, e))
                if not g:
                    continue
        games.append(g)
    log("  nově staženo %d zápasů" % new)

    P, PI, D = [0], {}, []

    def pidx(i):
        if not i:
            return 0
        if i not in PI:
            PI[i] = len(P)
            P.append(i)
        return PI[i]

    def didx(k):
        if k not in D:
            D.append(k)
        return D.index(k)

    gl, go, pe = [], [], []
    sk, gkd = OrderedDict(), OrderedDict()
    for gi, g in enumerate(games):
        gl.append("|".join([g["date"].replace("-", ""), str(g["hs"]), str(g["as"]), g["lt"], g["away"], g["home"],
                           str(g["id"])]))
        for e in g["go"]:
            per, t, stt, side, scr, a1, a2, gkid, ty = e
            go.append(c2(gi) + c1(per) + c2(t) + c1(stt * 2 + side) + c2(pidx(scr)) + c2(pidx(a1)) + c2(pidx(a2))
                      + c2(pidx(gkid)) + c1(ty))
        for e in g["pe"]:
            per, t, side, who, drawn, dur, desc, bench = e
            pe.append(c2(gi) + c1(per) + c2(t) + c1(side) + c2(pidx(who)) + c2(pidx(drawn)) + c1(dur) + c1(didx(desc))
                      + c1(bench))
        for r in g["sk"]:
            pid, side = r[0], r[1]
            row = c2(gi * 2 + side) + c1(r[2] + 32) + "".join(c1(v) for v in r[3:14]) + c2(r[14])
            sk.setdefault(pid, []).append(row)
        for r in g["gk"]:
            pid, side = r[0], r[1]
            row = c2(gi * 2 + side) + c2(r[2]) + "".join(c1(v) for v in r[3:11]) + c1(r[11] * 2 + r[12])
            gkd.setdefault(pid, []).append(row)
    for pid in list(sk) + list(gkd):
        pidx(pid)
    out = {"v": 2, "src": "NHL.com boxscore + play-by-play", "g": gl, "P": P, "D": D,
           "s": ",".join(c2(PI[p]) + "".join(rows) for p, rows in sk.items()),
           "k": ",".join(c2(PI[p]) + "".join(rows) for p, rows in gkd.items()),
           "go": "".join(go), "pe": "".join(pe)}
    last = max((g["date"] for g in games), default=None)
    return out, last


# ---------------------------------------------------------------- NHL stats REST: speciální formace, tresty, vhazování
def rest(kind, report):
    url = "%s/%s/%s?isAggregate=false&isGame=false&start=0&limit=-1&cayenneExp=seasonId=%s%%20and%%20gameTypeId=2" % (
        REST, kind, report, SEASON)
    return jget(url).get("data", [])


def build_special():
    log("NHL: speciální formace, tresty, vhazování, brankáři podle situace")

    def safe(kind, report):
        try:
            rows = rest(kind, report)
            log("  %s/%s: %d" % (kind, report, len(rows)))
            return rows
        except Exception as e:  # noqa: BLE001
            log("  %s/%s selhalo: %s" % (kind, report, e))
            return []

    def by(rows, key="playerId"):
        return {r[key]: r for r in rows if r.get(key)}

    def v(r, k, nd=None):
        x = (r or {}).get(k)
        if not isinstance(x, (int, float)):
            return None if r is None else 0
        return round(x) if nd is None else round(x, nd)

    S, T = by(safe("skater", "summary")), by(safe("skater", "timeonice"))
    PP, PK = by(safe("skater", "powerplay")), by(safe("skater", "penaltykill"))
    RT, PN, FO = by(safe("skater", "realtime")), by(safe("skater", "penalties")), by(safe("skater", "faceoffwins"))
    sk = {}
    for pid in set(S) | set(T) | set(PP) | set(PK):
        s, t, pp, pk, rt, pn, fo = S.get(pid), T.get(pid), PP.get(pid), PK.get(pid), RT.get(pid), PN.get(pid), FO.get(pid)
        posts = (v(rt, "missedShotGoalpost") or 0) + (v(rt, "missedShotCrossbar") or 0) if rt else None
        sk[str(pid)] = [v(pp or s, "ppGoals"), v(pp, "ppAssists"), v(pp or s, "ppPoints"), v(pp, "ppShots"),
                        v(t or pp, "ppTimeOnIcePerGame"), v(pp, "ppTimeOnIcePctPerGame", 3),
                        v(pk or s, "shGoals"), v(pk, "shAssists"), v(pk or s, "shPoints"), v(t or pk, "shTimeOnIcePerGame"),
                        v(pk, "shTimeOnIcePctPerGame", 3),
                        v(s, "evGoals"), v(s, "evPoints"), v(t, "evTimeOnIcePerGame"),
                        v(t, "shiftsPerGame", 1), v(t, "timeOnIcePerShift", 1),
                        posts, v(rt, "missedShots"), v(rt, "shotAttemptsBlocked"), v(rt, "firstGoals"), v(rt, "emptyNetGoals"),
                        v(pn, "penalties"), v(pn, "penaltiesDrawn"), v(pn, "minorPenalties"), v(pn, "majorPenalties"),
                        v(fo, "offensiveZoneFaceoffWins"), v(fo, "offensiveZoneFaceoffLosses"),
                        v(fo, "neutralZoneFaceoffWins"), v(fo, "neutralZoneFaceoffLosses"),
                        v(fo, "defensiveZoneFaceoffWins"), v(fo, "defensiveZoneFaceoffLosses"),
                        v(pk, "ppGoalsAgainstPer60", 2)]
    gk = {}
    for r in safe("goalie", "savesByStrength"):
        if r.get("playerId"):
            gk[str(r["playerId"])] = [v(r, "evShotsAgainst"), v(r, "evGoalsAgainst"), v(r, "ppShotsAgainst"),
                                      v(r, "ppGoalsAgainst"), v(r, "shShotsAgainst"), v(r, "shGoalsAgainst")]

    def team_ab(r):
        return TID.get(r.get("teamId")) or TNAME.get(norm_name(r.get("teamFullName")))
    TS, TP, TK, TR = (by(safe("team", x), "teamId") for x in ("summary", "powerplay", "penaltykill", "realtime"))
    tm = {}
    for tid_ in set(TS) | set(TP) | set(TK):
        s, p, k, r = TS.get(tid_), TP.get(tid_), TK.get(tid_), TR.get(tid_)
        ab = team_ab(s or p or k)
        if not ab:
            continue
        tm[ab] = [v(s or p, "powerPlayPct", 4), v(s or k, "penaltyKillPct", 4), v(p, "ppOpportunities"), v(p, "powerPlayGoalsFor"),
                  v(p, "shGoalsAgainst"), v(k, "timesShorthanded"), v(k, "ppGoalsAgainst"), v(k, "shGoalsFor"),
                  v(s or p, "powerPlayNetPct", 4), v(s or k, "penaltyKillNetPct", 4), v(p, "ppTimeOnIcePerGame"),
                  v(k, "pkTimeOnIcePerGame"), v(s, "shotsForPerGame", 1), v(s, "shotsAgainstPerGame", 1), v(s, "faceoffWinPct", 4),
                  v(r, "hits"), v(r, "blockedShots"), v(r, "giveaways"), v(r, "takeaways"), v(r, "satPct", 4)]
    log("  speciální: hráčů %d, brankářů %d, týmů %d" % (len(sk), len(gk), len(tm)))
    return {"updated": time.strftime("%Y-%m-%d"), "skaters": sk, "goalies": gk, "teams": tm}


# ---------------------------------------------------------------- NHL EDGE (sledovací data)
EDGE_AREAS = ["Crease", "Low Slot", "High Slot", "L Net Side", "R Net Side", "L Circle", "R Circle", "L Corner", "R Corner",
              "Behind the Net", "Outside L", "Outside R", "L Point", "Center Point", "R Point", "Offensive Neutral Zone",
              "Beyond Red Line"]


def _edge(arg):
    pid, g = arg
    try:
        return pid, g, jget("%s/edge/%s-detail/%s/%s/2" % (NHL, "goalie" if g else "skater", pid, SEASON))
    except Exception as e:  # noqa: BLE001
        return pid, g, e


def edge_skater(E):
    def n(x, nd=1):
        return round(x, nd) if isinstance(x, (int, float)) else None
    ts, sp = E.get("topShotSpeed") or {}, E.get("skatingSpeed") or {}
    sm, b20 = sp.get("speedMax") or {}, sp.get("burstsOver20") or {}
    ds, dm, z = E.get("totalDistanceSkated") or {}, E.get("distanceMaxGame") or {}, E.get("zoneTimeDetails") or {}
    sog = {x.get("locationCode"): x for x in E.get("sogSummary") or []}
    det = {x.get("area"): x for x in E.get("sogDetails") or []}
    if not sm and not ts and not ds:
        return None, None
    row = [n(sm.get("metric")), n(sm.get("percentile"), 3), b20.get("value"), n(b20.get("percentile"), 3),
           n(ds.get("metric")), n(ds.get("percentile"), 3), n(dm.get("metric"), 2), n(ts.get("metric")),
           n(ts.get("percentile"), 3), n(z.get("offensiveZonePctg"), 3), n(z.get("offensiveZonePercentile"), 3),
           n(z.get("neutralZonePctg"), 3), n(z.get("defensiveZonePctg"), 3), n(z.get("defensiveZonePercentile"), 3)]
    for c in ("high", "mid", "long"):
        x = sog.get(c) or {}
        row += [x.get("shots"), x.get("goals"), n(x.get("shotsPercentile"), 2)]
    row.append([(det.get(a) or {}).get("shots") for a in EDGE_AREAS])
    row.append([n((det.get(a) or {}).get("shotsPercentile"), 2) for a in EDGE_AREAS])
    la = lambda o, k="metric": n((o.get("leagueAvg") or {}).get(k)) if isinstance(o.get("leagueAvg"), dict) else None  # noqa: E731
    avg = [la(sm), la(b20, "value"), la(ds), la(ts), n(z.get("offensiveZoneLeagueAvg"), 3), n(z.get("neutralZoneLeagueAvg"), 3),
           n(z.get("defensiveZoneLeagueAvg"), 3)] + [n((sog.get(c) or {}).get("shootingPctgLeagueAvg"), 3) for c in ("high", "mid", "long")]
    return row, avg


def edge_goalie(E):
    def n(x, nd=1):
        return round(x, nd) if isinstance(x, (int, float)) else None
    st = E.get("stats") or {}
    loc = {x.get("locationCode"): x for x in E.get("shotLocationSummary") or []}
    det = {x.get("area"): x for x in E.get("shotLocationDetails") or []}
    if not st and not loc:
        return None, None
    row = []
    for k in ("goalsAgainstAvg", "gamesAbove900", "goalDifferentialPer60", "goalSupportAvg", "pointPctg"):
        o = st.get(k) or {}
        row += [n(o.get("value"), 3), n(o.get("percentile"), 3)]
    for c in ("all", "high", "mid", "long"):
        x = loc.get(c) or {}
        row += [x.get("saves"), x.get("goalsAgainst"), n(x.get("savePctg"), 4), n(x.get("savePctgPercentile"), 3)]
    row.append([(det.get(a) or {}).get("saves") for a in EDGE_AREAS])
    row.append([n((det.get(a) or {}).get("savePctg"), 3) for a in EDGE_AREAS])
    avg = [n((loc.get(c) or {}).get("savePctgLeagueAvg"), 4) for c in ("all", "high", "mid", "long")]
    return row, avg


def build_edge(data):
    from concurrent.futures import ThreadPoolExecutor
    gks = {r[0] for r in data["gk"]}
    ids = sorted({(r[0], False) for r in data["sk"] if r[0] not in gks} | {(r[0], True) for r in data["gk"]})
    log("NHL EDGE: %d hráčů a brankářů" % len(ids))
    sk, gk, avg, fails = {}, {}, {}, 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for pid, g, E in ex.map(_edge, ids):
            if isinstance(E, Exception) or not isinstance(E, dict):
                fails += 1
                continue
            row, a = (edge_goalie if g else edge_skater)(E)
            if row is None:
                continue
            (gk if g else sk)[str(pid)] = row
            key = "gk" if g else "sk"
            if key not in avg and a and any(x is not None for x in a):
                avg[key] = a
    log("  bruslařů %d, brankářů %d, neúspěšných %d" % (len(sk), len(gk), fails))
    return {"updated": time.strftime("%Y-%m-%d"), "areas": EDGE_AREAS, "avg": avg, "sk": sk, "gk": gk}


# ---------------------------------------------------------------- MoneyPuck
def mp_csv(name):
    txt = get(MP + name + ".csv").decode("utf-8")
    rows = list(csv.reader(io.StringIO(txt)))
    head = rows[0]
    idx = {}
    for i, h in enumerate(head):
        idx.setdefault(h, i)
    return idx, [r for r in rows[1:] if r]


def fnum(v):
    try:
        return float(v)
    except Exception:  # noqa: BLE001
        return 0.0


def build_mp():
    log("MoneyPuck: souhrny hráčů, brankářů a týmů")
    si, srows = mp_csv("skaters")
    allr, five, ppr, pkr = {}, {}, {}, {}
    for r in srows:
        pid = int(fnum(r[si["playerId"]]))
        sit = r[si["situation"]]
        if sit == "all":
            allr[pid] = r
        elif sit == "5on5":
            five[pid] = r
        elif sit == "5on4":
            ppr[pid] = r
        elif sit == "4on5":
            pkr[pid] = r

    def g(r, k, nd=None):
        v = fnum(r[si[k]]) if k in si else 0.0
        return round(v) if nd is None else round(v, nd)

    sk = []
    for pid, r in allr.items():
        f = five.get(pid)
        sk.append([pid, fix(r[si["team"]]), g(r, "games_played"), g(r, "icetime"), g(r, "gameScore", 1),
                   g(r, "I_F_xGoals", 1), g(r, "I_F_goals"), g(r, "I_F_shotsOnGoal"), g(r, "I_F_shotAttempts"),
                   g(r, "I_F_highDangerShots"), g(r, "I_F_highDangerGoals"), g(r, "I_F_highDangerxGoals", 1),
                   g(r, "I_F_mediumDangerShots"), g(r, "I_F_lowDangerShots"), g(r, "I_F_rebounds"), g(r, "I_F_hits"),
                   g(r, "I_F_takeaways"), g(r, "I_F_giveaways"), g(r, "shotsBlockedByPlayer"), g(r, "penaltiesDrawn"),
                   g(r, "OnIce_F_xGoals", 1), g(r, "OnIce_A_xGoals", 1), g(r, "OnIce_F_goals"), g(r, "OnIce_A_goals"),
                   g(f, "onIce_xGoalsPercentage", 2) if f else None, g(f, "onIce_corsiPercentage", 2) if f else None,
                   g(f, "offIce_xGoalsPercentage", 2) if f else None, g(f, "icetime") if f else 0,
                   g(r, "I_F_primaryAssists")])
    skx = {}
    for pid, r in allr.items():
        p, k = ppr.get(pid), pkr.get(pid)
        skx[str(pid)] = [g(r, "I_F_oZoneShiftStarts"), g(r, "I_F_neutralZoneShiftStarts"), g(r, "I_F_dZoneShiftStarts"),
                         g(r, "I_F_flyShiftStarts"), g(r, "I_F_rebounds"), g(r, "I_F_reboundGoals"), g(r, "I_F_xRebounds", 1),
                         g(p, "icetime") if p else 0, g(p, "I_F_xGoals", 2) if p else 0, g(p, "I_F_goals") if p else 0,
                         g(p, "I_F_points") if p else 0, g(p, "OnIce_F_xGoals", 2) if p else 0, g(p, "OnIce_F_goals") if p else 0,
                         g(k, "icetime") if k else 0, g(k, "OnIce_A_xGoals", 2) if k else 0, g(k, "OnIce_A_goals") if k else 0,
                         g(r, "penalties"), g(r, "penaltiesDrawn"), g(r, "I_F_dZoneGiveaways")]

    gi_, grows = mp_csv("goalies")
    gk, gsit = [], defaultdict(dict)
    for r in grows:
        gsit[int(fnum(r[gi_["playerId"]]))][r[gi_["situation"]]] = r
    for r in grows:
        if r[gi_["situation"]] != "all":
            continue

        def h(k, nd=None):
            v = fnum(r[gi_[k]]) if k in gi_ else 0.0
            return round(v) if nd is None else round(v, nd)
        gk.append([int(fnum(r[gi_["playerId"]])), fix(r[gi_["team"]]), h("games_played"), h("icetime"), h("xGoals", 1),
                   h("goals"), h("ongoal"), h("highDangerShots"), h("highDangerxGoals", 1), h("highDangerGoals"),
                   h("mediumDangerShots"), h("mediumDangerxGoals", 1), h("mediumDangerGoals"), h("lowDangerShots"),
                   h("lowDangerxGoals", 1), h("lowDangerGoals"), h("rebounds"), h("xRebounds", 1)])

    def gv(r, k, nd=None):
        if r is None or k not in gi_:
            return 0
        v = fnum(r[gi_[k]])
        return round(v) if nd is None else round(v, nd)
    gkx = {}
    for pid, S in gsit.items():
        a, e, k, p = S.get("all"), S.get("5on5"), S.get("4on5"), S.get("5on4")
        gkx[str(pid)] = [gv(a, "freeze"), gv(a, "xFreeze", 1), gv(e, "xGoals", 2), gv(e, "goals"), gv(e, "icetime"),
                         gv(k, "xGoals", 2), gv(k, "goals"), gv(k, "icetime"), gv(p, "xGoals", 2), gv(p, "goals"),
                         gv(a, "ongoal"), gv(e, "ongoal"), gv(k, "ongoal"), gv(p, "ongoal")]

    ti, trows = mp_csv("teams")
    by = defaultdict(dict)
    for r in trows:
        by[fix(r[ti["team"]])][r[ti["situation"]]] = r

    def tv(r, k, nd=None):
        if r is None:
            return None
        v = fnum(r[ti[k]]) if k in ti else 0.0
        return round(v) if nd is None else round(v, nd)
    tm = []
    for t, s in by.items():
        f, a = s.get("5on5"), s.get("all")
        tm.append([t, tv(f, "xGoalsPercentage", 2), tv(f, "corsiPercentage", 2), tv(f, "xGoalsFor", 1),
                   tv(f, "xGoalsAgainst", 1), tv(f, "goalsFor"), tv(f, "goalsAgainst"), tv(a, "xGoalsFor", 1),
                   tv(a, "xGoalsAgainst", 1), tv(a, "goalsFor"), tv(a, "goalsAgainst"), tv(a, "highDangerShotsFor"),
                   tv(a, "highDangerShotsAgainst"), tv(a, "highDangerGoalsFor"), tv(a, "highDangerGoalsAgainst")])
    ice = "iceTime" if "iceTime" in ti else "icetime"
    tmx = {}
    for t, s in by.items():
        p, k, a = s.get("5on4"), s.get("4on5"), s.get("all")
        tmx[t] = [tv(p, "xGoalsFor", 2), tv(p, "goalsFor"), tv(p, ice), tv(p, "xGoalsAgainst", 2), tv(p, "goalsAgainst"),
                  tv(k, "xGoalsAgainst", 2), tv(k, "goalsAgainst"), tv(k, ice), tv(k, "xGoalsFor", 2), tv(k, "goalsFor"),
                  tv(a, "reboundsFor"), tv(a, "reboundGoalsFor"), tv(a, "reboundsAgainst"), tv(a, "reboundGoalsAgainst")]
    log("  hráčů %d, brankářů %d, týmů %d" % (len(sk), len(gk), len(tm)))
    return {"updated": time.strftime("%Y-%m-%d"), "sk": sk, "gk": gk, "tm": tm, "skx": skx, "gkx": gkx, "tmx": tmx}


def build_lines():
    log("MoneyPuck: formace")
    li, rows = mp_csv("lines")
    out = []
    for r in rows:
        if r[li["situation"]] != "5on5":
            continue
        toi = fnum(r[li["icetime"]])
        if toi < 600:
            continue
        digits = "".join(ch for ch in r[li["lineId"]].split(".")[0] if ch.isdigit())
        ids = [digits[i:i + 7] for i in range(0, len(digits), 7)]
        kind = "D" if r[li["position"]].lower().startswith("pair") else "L"

        def v(k, nd=None):
            x = fnum(r[li[k]])
            return round(x) if nd is None else round(x, nd)
        out.append(["-".join(ids), fix(r[li["team"]]), kind, v("games_played"), round(toi), v("xGoalsPercentage", 2),
                    v("corsiPercentage", 2), v("goalsFor"), v("goalsAgainst"), v("xGoalsFor", 1), v("xGoalsAgainst", 1),
                    v("shotAttemptsFor"), v("shotAttemptsAgainst"), v("highDangerShotsFor"), v("highDangerShotsAgainst")])
    log("  formací %d" % len(out))
    return {"src": "MoneyPuck.com lines %s 5on5" % MP_YEAR, "l": out}


SHOT_T = {"WRIST": 0, "SNAP": 1, "SLAP": 2, "BACK": 3, "TIP": 4, "DEFL": 4, "WRAP": 5}
EV = {"SHOT": 0, "MISS": 1, "GOAL": 2}


def b36(n):
    s = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = s[r] + out
        if not n:
            return out


def enc4(v):
    return B64[(v >> 18) & 63] + B64[(v >> 12) & 63] + B64[(v >> 6) & 63] + B64[v & 63]


def build_shots():
    log("MoneyPuck: jednotlivé střely")
    z = zipfile.ZipFile(io.BytesIO(get(MP_SHOTS, timeout=180)))
    name = [n for n in z.namelist() if n.endswith(".csv")][0]
    rdr = csv.reader(io.TextIOWrapper(z.open(name), encoding="utf-8"))
    head = next(rdr)
    H = {h: i for i, h in enumerate(head)}
    shots, games = [], {}
    for r in rdr:
        if not r or r[H["isPlayoffGame"]] not in ("0", "0.0"):
            continue
        ev = EV.get(r[H["event"]])
        pid = int(fnum(r[H["shooterPlayerId"]]))
        if ev is None or not pid:
            continue
        gid = int(fnum(r[H["game_id"]]))
        home, away = fix(r[H["homeTeamCode"]]), fix(r[H["awayTeamCode"]])
        games[gid] = (home, away)
        is_home = fnum(r[H["isHomeTeam"]]) >= 0.5
        en = fnum(r[H["shotOnEmptyNet"]]) >= 0.5
        t = 7 if en else SHOT_T.get(r[H["shotType"]], 6)
        x = max(0, min(99, int(round(fnum(r[H["xCordAdjusted"]])))))
        y = max(0, min(84, int(round(fnum(r[H["yCordAdjusted"]]))) + 42))
        q = max(0, min(63, int(round(math.sqrt(max(0.0, fnum(r[H["xGoal"]]))) * 63))))
        v = ((((x * 85 + y) * 64 + q) * 3 + ev) * 8 + t)
        tsec = int(fnum(r[H["time"]])) if "time" in H else 0
        fl = (1 if "shotRush" in H and fnum(r[H["shotRush"]]) >= 0.5 else 0) + (2 if "shotRebound" in H and fnum(r[H["shotRebound"]]) >= 0.5 else 0)
        shots.append((gid, pid, is_home, enc4(v), int(fnum(r[H["goalieIdForShot"]])), en, c2(tsec) + c1(fl)))
    glist = sorted(games)
    gindex = {g: i for i, g in enumerate(glist)}
    per = defaultdict(lambda: defaultdict(list))
    for gid, pid, is_home, code, goalie, en, tf in shots:
        per[pid][gindex[gid]].append((is_home, code, goalie, en, tf))
    gkeys = defaultdict(list)
    needs = set()
    for gid, pid, is_home, code, goalie, en, tf in shots:
        gi = gindex[gid]
        home, away = games[gid]
        key = "%d-%s" % (gi, away if is_home else home)
        if goalie and goalie not in gkeys[key]:
            gkeys[key].append(goalie)
        if not goalie:
            needs.add(key)
    for k, v in gkeys.items():
        if len(v) > 1:
            needs.add(k)
    pout, gx, tout = {}, {}, {}
    for pid in sorted(per):
        blocks, digits, times = [], [], []
        for gi in sorted(per[pid]):
            lst = per[pid][gi]
            times.append("".join(s[4] for s in lst))
            is_home = lst[0][0]
            blocks.append(b36(gi) + ("." if is_home else ":") + "".join(s[1] for s in lst))
            home, away = games[glist[gi]]
            key = "%d-%s" % (gi, away if is_home else home)
            if key in needs:
                gl = gkeys.get(key, [])
                for s in lst:
                    digits.append(str(gl.index(s[2])) if s[2] and s[2] in gl and gl.index(s[2]) < 9 else "9")
        pout[str(pid)] = ",".join(blocks)
        tout[str(pid)] = "".join(times)
        if digits:
            gx[str(pid)] = "".join(digits)
    log("  střel %d v %d zápasech" % (len(shots), len(glist)))
    shots_json = {"v": 1, "src": "MoneyPuck.com shots_%s" % MP_YEAR, "n": len(shots),
                  "g": [[g, games[g][0], games[g][1]] for g in glist], "p": pout, "t": tout}
    gs_json = {"gk": dict(gkeys), "gd": sorted(needs), "gx": gx}
    return shots_json, gs_json


# ---------------------------------------------------------------- stránka
SKELETON = ('<!doctype html>\n<html lang="cs">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '<style>[hidden]{display:none!important}</style>\n')


def build_page():
    with open(os.path.join(ROOT, "page.html"), encoding="utf-8") as f:
        src = f.read()
    i = src.index("</style>") + len("</style>")
    head = src[:i].replace('<meta name="claude:viewport-fit-sides" content="cover">\n', "")
    html = SKELETON + head + "\n</head>\n<body>\n" + src[i:] + "\n</body>\n</html>\n"
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    log("  zapsáno index.html")


def step(name, fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        log("!! %s selhalo, ponechávám předchozí data: %s" % (name, e))
        return None


def main():
    ok = True
    nhl = step("NHL statistiky", build_nhl)
    teams = None
    if nhl:
        data, teams = nhl
        gm = step("NHL zápasy", lambda: build_games(teams))
        if gm:
            games, last = gm
            wjson("games.json", games)
            data["updated"] = last or time.strftime("%Y-%m-%d")
        else:
            data["updated"] = time.strftime("%Y-%m-%d")
            ok = False
        cr = step("NHL kariéra", lambda: build_careers(data))
        if cr:
            wjson("careers.json", cr)
        sc = step("NHL program", build_schedule)
        if sc:
            wjson("schedule.json", sc)
        sp = step("NHL speciální formace", build_special)
        if sp:
            wjson("special.json", sp)
        ed = step("NHL EDGE", lambda: build_edge(data))
        if ed:
            wjson("edge.json", ed)
        wjson("data.json", data)
    else:
        ok = False
    mp = step("MoneyPuck souhrny", build_mp)
    if mp:
        wjson("mp.json", mp)
    ln = step("MoneyPuck formace", build_lines)
    if ln:
        wjson("lines.json", ln)
    sh = step("MoneyPuck střely", build_shots)
    if sh:
        wjson("shots.json", sh[0])
        wjson("goalies_shots.json", sh[1])
    build_page()
    if not nhl:
        sys.exit(1)
    log("Hotovo" + ("" if ok and mp and ln and sh else " (některé zdroje se nepodařilo obnovit)"))


if __name__ == "__main__":
    main()
