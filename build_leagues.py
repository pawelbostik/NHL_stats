"""Další ligy: AHL a zámořské juniorské ligy (HockeyTech), finská Liiga a švýcarská National League (SIHF).

Všechny zdroje jsou veřejná datová rozhraní, ze kterých čtou weby samotných lig. Stahuje se jen
aktuální sezona (tabulka, hráči, brankáři), dvakrát denně spolu se zbytkem stránky. U HockeyTech
ligy vyžadují uvedení zdroje, stránka ho zobrazuje u každé ligy.
"""
import json
import os
import re
import time
import unicodedata
import urllib.parse

HT = {
    "ahl": ("AHL", "American Hockey League", "50c2cd9b5e18e390", "ahl"),
    "ohl": ("OHL", "Ontario Hockey League", "2976319eb44abe94", "ohl"),
    "whl": ("WHL", "Western Hockey League", "41b145a848f4bd67", "whl"),
    "qmjhl": ("QMJHL", "Quebec Maritimes Junior Hockey League", "f1aa699db3d81487", "lhjmq"),
    "ushl": ("USHL", "United States Hockey League", "e828f89b243dc43f", "ushl"),
}
HTB = "https://lscluster.hockeytech.com/feed/?key=%s&client_code=%s&lang=en&fmt=json&"
CZ_RE = re.compile(r"\b(Czech|Czechia|CZE|Czech Republic|Cesko|Česko)\b", re.I)
SK_RE = re.compile(r"\b(Slovakia|SVK|Slovak Republic|Slovensko)\b", re.I)


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()


def nkey(name):
    parts = re.findall(r"[a-z]+", fold(name).replace(",", " "))
    return " ".join(sorted(parts))


def num(v, f=int):
    try:
        return f(v)
    except (TypeError, ValueError):
        return 0


def nhl_index(site, data):
    """Jméno -> hráč NHL (jen jednoznačné shody) a národnost podle NHL dat."""
    idx, nat = {}, {}
    try:
        with open(os.path.join(site, "hist", "names.json"), encoding="utf-8") as f:
            for x in json.load(f):
                k = nkey(x[1])
                idx[k] = None if k in idx else [x[0], x[4], x[3], x[5]]
    except Exception:  # noqa: BLE001
        pass
    try:
        import glob
        for fn in glob.glob(os.path.join(site, "hist", "careers", "*.json")) + [os.path.join(site, "careers.json")]:
            with open(fn, encoding="utf-8") as f:
                for pid, c in json.load(f).items():
                    if c.get("co") in ("CZE", "SVK"):
                        nat[int(pid)] = c["co"]
    except Exception:  # noqa: BLE001
        pass
    for rows, ni in (((data or {}).get("sk") or [], 19), ((data or {}).get("gk") or [], 16)):
        for r in rows:
            if len(r) > ni and r[ni] in ("CZE", "SVK"):
                nat[r[0]] = r[ni]
    return idx, nat


def match(name, idx, nat):
    m = idx.get(nkey(name))
    if not m:
        return None, None
    return m, nat.get(m[0])


def hockeytech(code, jget, idx, nat, log):
    short, full, key, cc = HT[code]
    base = HTB % (key, cc)
    seas = jget(base + "feed=modulekit&view=seasons").get("SiteKit", {}).get("Seasons", [])
    reg = [s for s in seas if s.get("career") == "1" and s.get("playoff") == "0" and "pre" not in s.get("season_name", "").lower()]
    if not reg:
        raise RuntimeError("žádná sezona")
    s = reg[0]
    sid = s["season_id"]
    sk = jget(base + "feed=modulekit&view=statviewtype&type=topscorers&season_id=%s&first=0&limit=3000" % sid).get("SiteKit", {}).get("Statviewtype", []) or []
    gk = jget(base + "feed=modulekit&view=statviewtype&type=topgoalies&season_id=%s&first=0&limit=500&qualified=all" % sid).get("SiteKit", {}).get("Statviewtype", []) or []
    stv = jget(base + "feed=modulekit&view=statviewtype&type=standings&stat=conference&season_id=%s" % sid).get("SiteKit", {}).get("Statviewtype", []) or []

    def natof(p, nm):
        txt = " ".join(p.get(k) or "" for k in ("homeplace", "birthtown", "birthcntry", "homecntry", "hometown"))
        n = "CZE" if CZ_RE.search(txt) else "SVK" if SK_RE.search(txt) else None
        m, mn = match(nm, idx, nat)
        return n or mn, m

    def pname(p):
        n = p.get("name") or ""
        if "," in n:  # QMJHL: "Příjmení, Jméno"
            a, b = [x.strip() for x in n.split(",", 1)]
            n = b + " " + a
        return n

    skaters = []
    for p in sk:
        nm = pname(p)
        n, m = natof(p, nm)
        skaters.append([nm, p.get("team_code") or "", p.get("position") or "", num(p.get("games_played")), num(p.get("goals")), num(p.get("assists")),
                        num(p.get("points")), num(p.get("plus_minus")), num(p.get("penalty_minutes")), num(p.get("power_play_goals")), num(p.get("shots")),
                        num(p.get("age")), 1 if p.get("rookie") == "1" else 0, n, m[0] if m else None, m[1] if m else None, m[2] if m else None])
    goalies = []
    for p in gk:
        nm = pname(p)
        n, m = natof(p, nm)
        secs = num(p.get("seconds_played"))
        ga = num(p.get("goals_against"))
        goalies.append([nm, p.get("team_code") or "", num(p.get("games_played")), num(p.get("wins")), num(p.get("losses")),
                        num(p.get("ot_losses")) + num(p.get("shootout_losses")), round(ga * 3600 / secs, 2) if secs else None,
                        num(p.get("save_percentage"), float) or None, num(p.get("shutouts")), num(p.get("saves")), ga, n,
                        m[0] if m else None, m[1] if m else None, m[2] if m else None])
    groups, cur = [], None
    for t in stv:
        if t.get("repeatheader"):
            cur = {"n": t.get("name") or "", "t": []}
            groups.append(cur)
            continue
        if cur is None:
            cur = {"n": "", "t": []}
            groups.append(cur)
        cur["t"].append([t.get("team_code") or "", t.get("name") or "", num(t.get("games_played")), num(t.get("wins")), num(t.get("losses")),
                         num(t.get("ot_losses")) + num(t.get("shootout_losses")), num(t.get("points")), num(t.get("goals_for")), num(t.get("goals_against")),
                         t.get("streak") or "", t.get("past_10") or "%s-%s-%s" % (t.get("past_10_wins", ""), t.get("past_10_losses", ""), t.get("past_10_ot_losses", ""))])
    return {"code": code, "short": short, "name": full, "season": s.get("season_name"), "kind": "ht",
            "credit": "Official statistics provided by %s · Powered by HockeyTech.com" % full, "credit_url": "https://hockeytech.com",
            "st": groups, "sk": skaters, "gk": goalies}


def liiga(jget, idx, nat, log):
    y = int(time.strftime("%Y")) + (1 if int(time.strftime("%m")) >= 7 else 0)
    pl = jget("https://liiga.fi/api/v2/players/stats/summed/%d/%d/runkosarja/true?dataType=basicStats" % (y, y))
    if not pl:
        y -= 1
        pl = jget("https://liiga.fi/api/v2/players/stats/summed/%d/%d/runkosarja/true?dataType=basicStats" % (y, y))
    st = jget("https://liiga.fi/api/v2/standings/?season=%d" % y).get("season", [])
    gst = []
    for gu in ("https://liiga.fi/api/v2/goalies/stats/summed/%d/%d/runkosarja/true", "https://liiga.fi/api/v2/goalkeepers/stats/summed/%d/%d/runkosarja/true",
               "https://liiga.fi/api/v2/players/stats/summed/%d/%d/runkosarja/true?dataType=goalkeeperStats&goalkeeper=true"):
        try:
            gst = jget(gu % (y, y))
        except Exception:  # noqa: BLE001
            gst = []
        if isinstance(gst, list) and gst:
            break
    pl = list(pl or []) + [g for g in gst or [] if isinstance(g, dict) and g.get("playerId") not in {p.get("playerId") for p in pl or []}]
    gmap = {g.get("playerId"): g for g in gst or [] if isinstance(g, dict)}
    skaters, goalies = [], []
    for p in pl or []:
        if p.get("removed"):
            continue
        nm = "%s %s" % (p.get("firstName", ""), p.get("lastName", ""))
        m, mn = match(nm, idx, nat)
        n = p.get("nationality") if p.get("nationality") in ("CZE", "SVK") else mn
        if p.get("goalkeeper") or "saves" in p or "savePercentage" in p:
            g = gmap.get(p.get("playerId"), p)
            sv, ga = g.get("saves"), g.get("goalsAgainst") if g.get("goalsAgainst") is not None else g.get("goalsAllowed")
            svp = g.get("savePercentage")
            if svp is None and sv is not None and ga is not None and (sv + ga):
                svp = sv / (sv + ga)
            gp = g.get("games") or 0
            if not gp:
                continue
            goalies.append([nm, p.get("teamShortName") or "", gp, g.get("wins") or 0, g.get("losses") or 0, g.get("overtimeLosses") or 0,
                            round(g["goalsAgainstAverage"], 2) if isinstance(g.get("goalsAgainstAverage"), (int, float)) else None,
                            round(float(svp), 3) if isinstance(svp, (int, float)) else None, g.get("shutouts") or 0, sv or 0, ga or 0, n,
                            m[0] if m else None, m[1] if m else None, m[2] if m else None])
        else:
            if not p.get("games"):
                continue
            toi = p.get("timeOnIceAvg")
            skaters.append([nm, p.get("teamShortName") or "", {"H": "F", "P": "D", "VL": "LW", "OL": "RW", "KH": "C"}.get(p.get("role"), p.get("role") or ""),
                            p.get("games") or 0, p.get("goals") or 0, p.get("assists") or 0, p.get("points") or 0, p.get("plusMinus") or 0,
                            p.get("penaltyMinutes") or 0, p.get("powerplayGoals") or 0, p.get("shots") or 0, None, 1 if p.get("rookie") else 0, n,
                            m[0] if m else None, m[1] if m else None, m[2] if m else None, round(p.get("expectedGoals") or 0, 1), toi])
    table = [[t.get("teamName", ""), t.get("teamName", ""), t.get("games", 0), (t.get("wins") or 0) + (t.get("overtimeWins") or 0), t.get("losses", 0),
              (t.get("overtimeLosses") or 0), t.get("points", 0), t.get("goals", 0), t.get("goalsAgainst", 0), "", ""] for t in st]
    return {"code": "liiga", "short": "Liiga", "name": "Liiga (Finsko)", "season": "%d/%02d" % (y - 1, y % 100), "kind": "liiga",
            "credit": "Statistiky: Liiga (liiga.fi)", "credit_url": "https://liiga.fi", "st": [{"n": "", "t": table}], "sk": skaters, "gk": goalies,
            "note": "3 body za výhru v základní době, 2 za výhru v prodloužení, 1 za prohru v prodloužení."}


def sihf_table(jget, alias, y, order, extra=""):
    u = ("https://data.sihf.ch/Statistic/api/cms/cache300?alias=%s&searchQuery=1/2015-2099/1&filterQuery=%d%s&orderBy=%s&orderByDescending=true"
         "&take=1000&filterBy=Season,Phase&skip=0&language=de") % (alias, y, extra, order)
    d = jget(u)
    if not d or d.get("stub") or not d.get("data"):
        return None, []
    return [h.get("alias") for h in d.get("header") or []], d["data"]


def nl(jget, idx, nat, log):
    y = int(time.strftime("%Y")) + (1 if int(time.strftime("%m")) >= 7 else 0)
    hdr, rows = sihf_table(jget, "player", y, "points")
    skaters = []
    for r in rows:
        d = dict(zip(hdr or [], r))
        nm = d.get("player") or ""
        if isinstance(nm, dict):
            nm = nm.get("name", "")
        parts = nm.split()
        full = " ".join(parts[1:] + parts[:1]) if len(parts) > 1 else nm  # SIHF: "Příjmení Jméno"
        team = d.get("team")
        tcode = team.get("acronym") if isinstance(team, dict) else (team or "")
        m, mn = match(full, idx, nat)
        nation = d.get("nation") or d.get("nationality")
        n = nation if nation in ("CZE", "SVK") else mn
        pos = {"Stürmer": "F", "Verteidiger": "D"}.get(d.get("position"), d.get("position") or "")
        skaters.append([full, tcode or "", pos, num(d.get("gamesPlayed")), num(d.get("goals")), num(d.get("assists")), num(d.get("points")),
                        num(d.get("plusMinus")), num(d.get("penaltyMinutes") or d.get("pim")), num(d.get("powerPlayGoals") or d.get("ppg")),
                        num(d.get("shotsOnGoal") or d.get("sog")), None, 0, n, m[0] if m else None, m[1] if m else None, m[2] if m else None])
    goalies = []
    hdr2, rows2 = sihf_table(jget, "goalkeeper", y, "gamesPlayed")
    for r in rows2 if rows2 else []:
        d = dict(zip(hdr2 or [], r))
        nm = d.get("player") or ""
        parts = nm.split()
        full = " ".join(parts[1:] + parts[:1]) if len(parts) > 1 else nm
        team = d.get("team")
        tcode = team.get("acronym") if isinstance(team, dict) else (team or "")
        m, mn = match(full, idx, nat)
        svp = d.get("savesPercentage") or d.get("savePercentage")
        try:
            svp = float(str(svp).replace("%", "")) / (100 if float(str(svp).replace("%", "")) > 1 else 1)
        except (TypeError, ValueError):
            svp = None
        gaa = d.get("goalsAgainstAverage") or d.get("gaa")
        if not num(d.get("gamesPlayed")):
            continue
        goalies.append([full, tcode or "", num(d.get("gamesPlayed")), None, None, None,
                        num(gaa, float) or None, round(svp, 3) if svp else None, None, num(d.get("saves")),
                        num(d.get("goalsAgainst")), mn, m[0] if m else None, m[1] if m else None, m[2] if m else None])
    d = jget(("https://data.sihf.ch/Statistic/api/cms/cache300?alias=standing&searchQuery=1/2015-2099/1&filterQuery=%d&orderBy=rank"
              "&orderByDescending=false&take=20&filterBy=Season&skip=-1&language=de") % y)
    hs = [h.get("alias") for h in d.get("header") or []]
    table = []
    for r in d.get("data") or []:
        x = dict(zip(hs, r))
        t = x.get("team") or {}
        table.append([t.get("acronym", "") if isinstance(t, dict) else "", t.get("name", "") if isinstance(t, dict) else str(t), num(x.get("gamesPlayed")),
                      num(x.get("gamesWonInTime")) + num(x.get("gamesWonExtraTime")) + num(x.get("gamesWonPenalty")), num(x.get("gamesLostInTime")),
                      num(x.get("gamesLostExtraTime")) + num(x.get("gamesLostPenalty")), num(x.get("points")),
                      num(x.get("goalsFor")), num(x.get("goalsAgainst")), x.get("streak") if isinstance(x.get("streak"), str) else "", ""])
    return {"code": "nl", "short": "NL", "name": "National League (Švýcarsko)", "season": "%d/%02d" % (y - 1, y % 100), "kind": "sihf",
            "credit": "Statistiky: Swiss Ice Hockey Federation (sihf.ch)", "credit_url": "https://www.sihf.ch", "st": [{"n": "", "t": table}],
            "sk": skaters, "gk": goalies, "cols": hdr, "gcols": hdr2 if rows2 else None, "scols": hs}


def run(site, data, jget, log):
    out = os.path.join(site, "ligy")
    os.makedirs(out, exist_ok=True)
    idx, nat = nhl_index(site, data)
    index = {"updated": time.strftime("%Y-%m-%d %H:%M"), "leagues": [], "cz": []}
    jobs = [(c, (lambda c=c: hockeytech(c, jget, idx, nat, log))) for c in HT] + [("liiga", lambda: liiga(jget, idx, nat, log)), ("nl", lambda: nl(jget, idx, nat, log))]
    for code, fn in jobs:
        try:
            d = fn()
        except Exception as e:  # noqa: BLE001
            log("  liga %s: chyba (%s)" % (code, e))
            old = os.path.join(out, code + ".json")
            if os.path.exists(old):
                with open(old, encoding="utf-8") as f:
                    d = json.load(f)
            else:
                continue
        d["updated"] = d.get("updated") or time.strftime("%Y-%m-%d")
        with open(os.path.join(out, code + ".json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        index["leagues"].append([code, d["short"], d["name"], d.get("season"), len(d.get("sk") or []), len(d.get("gk") or [])])
        for r in d.get("sk") or []:
            if r[13] in ("CZE", "SVK"):
                index["cz"].append([code, 0, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[13], r[14], r[15], r[16]])
        for r in d.get("gk") or []:
            if r[11] in ("CZE", "SVK"):
                index["cz"].append([code, 1, r[0], r[1], "G", r[2], r[3], r[7], r[6], r[11], r[12], r[13], r[14]])
        log("  liga %s: hráčů %d, brankářů %d, týmů %d" % (code, len(d.get("sk") or []), len(d.get("gk") or []), sum(len(g["t"]) for g in d.get("st") or [])))
        time.sleep(0.5)
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    return True


if __name__ == "__main__":
    import urllib.request

    def _jget(u):
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (compatible; nhl-statistiky/1.0)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            t = r.read().decode("utf-8", "replace").strip()
        if t.startswith("(") and t.endswith(")"):
            t = t[1:-1]
        return json.loads(t)
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "site", "data.json"), encoding="utf-8") as fh:
        dd = json.load(fh)
    run(os.path.join(here, "site"), dd, _jget, print)
