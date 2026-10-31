"""Doplňkové přehledy z kariér hráčů NHL: reprezentace, líheň (mateřské kluby) a draft.

Vše kromě draftu se počítá z dat, která už stránka má (kariéry z NHL API včetně juniorských,
evropských a reprezentačních soutěží). Draft se stahuje z veřejného API NHL (api-web.nhle.com),
každý ročník jen jednou, aktuální ročník nejvýš jednou týdně.
"""
import glob
import json
import os
import re
import time
import unicodedata

MS = {"WC", "WC-A", "WEC-A"}
OH = {"OG", "Olympics"}
CUP = {"Can-Cup", "CC", "WCup", "W-Cup", "4 Nations"}
JR = {"WJC-A", "WJC-20"}
U18 = {"WJ18-A", "WJC-18", "EJC-A", "U-18", "Hlinka Gretzky Cup", "Ivan Hlinka Memorial"}
CATS = [("ms", MS), ("oh", OH), ("cup", CUP), ("jr", JR), ("u18", U18)]
INTL = MS | OH | CUP | JR | U18 | {
    "EHT", "Nat-Tm", "International", "Spengler Cup", "WHC-17", "WJAC-19", "Summit-72", "Summit-74", "YOG", "OGQ", "WC-Q",
    "WEC-B", "WC-B", "WC-C", "U-17", "WSI U12", "WSI U13", "WSI U14", "WSI U15", "WJC-B", "WJ18-B", "EJC-B", "Friendly", "Intl"}
NATION = {"CZE": ("Czechia", "Czech Republic", "Czechoslovakia"), "SVK": ("Slovakia",)}
COUNTRIES = ("Czechia", "Czech Republic", "Czechoslovakia", "Slovakia", "Canada", "USA", "United States", "Sweden", "Finland", "Russia",
             "Soviet Union", "USSR", "Switzerland", "Germany", "West Germany", "Latvia", "Norway", "Denmark", "Austria", "Belarus", "Ukraine",
             "Slovenia", "Kazakhstan", "France", "Italy", "Poland", "Great Britain", "Hungary", "Japan", "Netherlands", "Team North America",
             "Team Europe", "Team World")

# Mateřské kluby: hledá se podle názvu města nebo klubu (bez diakritiky), konkrétnější vzory první.
TOWNS = [
    ("hr kralove", "Hradec Králové"), ("havl brod", "Havlíčkův Brod"), ("havlickuv", "Havlíčkův Brod"), ("ml boleslav", "Mladá Boleslav"), ("rokycany", "Rokycany"),
    ("c budejovice", "České Budějovice"), ("k vary", "Karlovy Vary"), ("b bystrica", "Banská Bystrica"), ("l mikulas", "Liptovský Mikuláš"),
    ("sp nova ves", "Spišská Nová Ves"), ("letnany", "Praha"), ("czech knights", "Praha"), ("plzensky", "Plzeň"), ("uh hradiste", "Uherské Hradiště"),
    ("fr mistek", "Frýdek-Místek"), ("val mezirici", "Valašské Meziříčí"), ("j hradec", "Jindřichův Hradec"),
    ("horacka slavia", "Třebíč"), ("dukla trencin", "Trenčín"), ("dukla jihlava", "Jihlava"), ("sparta", "Sparta Praha"), ("slavia", "Slavia Praha"),
    ("havirov", "Havířov"), ("trinec", "Třinec"), ("vitkovice", "Vítkovice"), ("poruba", "Poruba"), ("ostrava", "Ostrava"),
    ("kometa", "Brno"), ("zbrojovka", "Brno"), ("brno", "Brno"), ("kladno", "Kladno"), ("litvinov", "Litvínov"), ("plzen", "Plzeň"), ("skoda", "Plzeň"),
    ("pardubice", "Pardubice"), ("liberec", "Liberec"), ("mlada boleslav", "Mladá Boleslav"), ("jihlava", "Jihlava"), ("zlin", "Zlín"),
    ("gottwaldov", "Zlín"), ("olomouc", "Olomouc"), ("hradec kralove", "Hradec Králové"), ("karlovy vary", "Karlovy Vary"),
    ("ceske budejovice", "České Budějovice"), ("budejovice", "České Budějovice"), ("chomutov", "Chomutov"), ("kadan", "Kadaň"),
    ("prerov", "Přerov"), ("prostejov", "Prostějov"), ("frydek", "Frýdek-Místek"), ("novy jicin", "Nový Jičín"), ("vsetin", "Vsetín"),
    ("jindrichuv hradec", "Jindřichův Hradec"), ("pisek", "Písek"), ("tabor", "Tábor"), ("benatky", "Benátky nad Jizerou"),
    ("usti nad labem", "Ústí nad Labem"), ("beroun", "Beroun"), ("kolin", "Kolín"), ("kutna hora", "Kutná Hora"), ("havlickuv brod", "Havlíčkův Brod"),
    ("zdar", "Žďár nad Sázavou"), ("trebic", "Třebíč"), ("znojmo", "Znojmo"), ("hodonin", "Hodonín"), ("uherske hradiste", "Uherské Hradiště"),
    ("uhersky brod", "Uherský Brod"), ("kromeriz", "Kroměříž"), ("vyskov", "Vyškov"), ("sumperk", "Šumperk"), ("opava", "Opava"), ("karvina", "Karviná"),
    ("orlova", "Orlová"), ("bohumin", "Bohumín"), ("frenstat", "Frenštát pod Radhoštěm"), ("roznov", "Rožnov pod Radhoštěm"),
    ("valasske mezirici", "Valašské Meziříčí"), ("koprivnice", "Kopřivnice"), ("chrudim", "Chrudim"), ("kralupy", "Kralupy nad Vltavou"),
    ("rakovnik", "Rakovník"), ("slany", "Slaný"), ("sokolov", "Sokolov"), ("cheb", "Cheb"), ("klatovy", "Klatovy"), ("strakonice", "Strakonice"),
    ("pribram", "Příbram"), ("vlasim", "Vlašim"), ("nymburk", "Nymburk"), ("nachod", "Náchod"), ("trutnov", "Trutnov"), ("jablonec", "Jablonec nad Nisou"),
    ("ceska lipa", "Česká Lípa"), ("decin", "Děčín"), ("teplice", "Teplice"), ("zatec", "Žatec"), ("louny", "Louny"), ("melnik", "Mělník"),
    ("neratovice", "Neratovice"), ("studenka", "Studénka"), ("blansko", "Blansko"), ("tisnov", "Tišnov"), ("boskovice", "Boskovice"),
    ("velke mezirici", "Velké Meziříčí"), ("pelhrimov", "Pelhřimov"), ("humpolec", "Humpolec"), ("chotebor", "Chotěboř"), ("svitavy", "Svitavy"),
    ("ceska trebova", "Česká Třebová"), ("hronov", "Hronov"), ("dvur kralove", "Dvůr Králové nad Labem"), ("prague", "Praha"), ("praha", "Praha"),
    ("most", "Most"), ("kosice", "Košice"), ("bratislava", "Bratislava"), ("slovan", "Bratislava"), ("ruzinov", "Bratislava"), ("trencin", "Trenčín"),
    ("zvolen", "Zvolen"), ("nitra", "Nitra"), ("poprad", "Poprad"), ("martin", "Martin"), ("banska bystrica", "Banská Bystrica"),
    ("liptovsky mikulas", "Liptovský Mikuláš"), ("skalica", "Skalica"), ("zilina", "Žilina"), ("presov", "Prešov"), ("spisska nova ves", "Spišská Nová Ves"),
    ("topolcany", "Topoľčany"), ("michalovce", "Michalovce"), ("detva", "Detva"), ("piestany", "Piešťany"), ("trnava", "Trnava"), ("dubnica", "Dubnica nad Váhom"),
    ("povazska bystrica", "Považská Bystrica"), ("nove zamky", "Nové Zámky"), ("humenne", "Humenné"), ("senica", "Senica"), ("ziar", "Žiar nad Hronom"),
]


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()


def strip_age(team):
    t = team or ""
    for _ in range(3):
        t = re.sub(r"\s+(U\d{2}|Jr\.?|Juniors?|II|B|2|U\d{2}\s*\(\w+\))$", "", t).strip()
    return t


def is_national(team):
    return any((team or "").startswith(c) for c in COUNTRIES)


def town_of(team):
    f = " " + re.sub(r"\s+", " ", re.sub(r"[^a-z ]+", " ", fold(team))).strip() + " "
    for key, name in TOWNS:
        if (" " + key + " ") in f if len(key) <= 5 else key in f:
            return name
    return strip_age(team)


def load_careers(site):
    out = {}
    for f in sorted(glob.glob(os.path.join(site, "hist", "careers", "*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                out.update(json.load(fh))
        except Exception:  # noqa: BLE001
            pass
    try:
        with open(os.path.join(site, "careers.json"), encoding="utf-8") as fh:
            out.update(json.load(fh))
    except Exception:  # noqa: BLE001
        pass
    return out


def load_names(site, data):
    names = {}
    try:
        with open(os.path.join(site, "hist", "names.json"), encoding="utf-8") as fh:
            for x in json.load(fh):
                names[str(x[0])] = {"n": x[1], "f": x[2], "l": x[3], "g": x[4], "t": x[5]}
    except Exception:  # noqa: BLE001
        pass
    cur = int(str(data.get("season") or time.strftime("%Y"))[:4]) if data else None
    for rows, g in (((data or {}).get("sk") or [], 0), ((data or {}).get("gk") or [], 1)):
        for r in rows:
            k = str(r[0])
            if k not in names:
                names[k] = {"n": "%s %s" % (r[1], r[2]), "f": cur, "l": cur, "g": g, "t": r[3]}
            elif cur:
                names[k]["l"] = max(names[k]["l"] or cur, cur)
                names[k]["t"] = r[3]
    return names


def nhl_totals(c):
    gp = pts = 0
    first = None
    for r in c.get("t") or []:
        if r[1] == 2 and r[2] == "NHL":
            gp += r[4] or 0
            pts += (r[5] if c.get("g") else r[7]) or 0
            first = r[0] if first is None else min(first, r[0])
    return gp, pts, first


def build_repre(car, names):
    out = {k: [] for k in NATION}
    for pid, c in car.items():
        nm = names.get(pid)
        if not nm:
            continue
        g = 1 if c.get("g") else 0
        for nat, prefixes in NATION.items():
            acc = {k: [0, 0, set()] for k, _ in CATS}
            for r in c.get("t") or []:
                team = r[3] or ""
                if not team.startswith(prefixes):
                    continue
                for k, lg in CATS:
                    if r[2] in lg:
                        if k not in ("jr", "u18") and re.search(r"U\d{2}|Jr", team):
                            continue
                        acc[k][0] += r[4] or 0
                        acc[k][1] += 0 if g else (r[7] or 0)
                        acc[k][2].add(r[0])
            if not any(v[0] for v in acc.values()):
                continue
            row = [int(pid), nm["n"], g, nm["l"], nm["t"]]
            for k, _ in CATS:
                row += [acc[k][0], acc[k][1], len(acc[k][2])]
            out[nat].append(row)
    for nat in out:
        # řazení: body dospělých (MS + OH + pohár), pak zápasy
        out[nat].sort(key=lambda r: (-(r[6] + r[9] + r[12]), -(r[5] + r[8] + r[11])))
    return out


def build_lihen(car, names):
    out = {"CZE": {}, "SVK": {}}
    for pid, c in car.items():
        co = c.get("co")
        if co not in out:
            continue
        nm = names.get(pid)
        if not nm:
            continue
        rows = sorted((r for r in c.get("t") or [] if r[1] == 2 and r[2] not in INTL and not is_national(r[3]) and r[2] != "NHL"),
                      key=lambda r: r[0])
        if not rows:
            continue
        first = rows[0]
        town = town_of(first[3])
        gp, pts, fs = nhl_totals(c)
        out[co].setdefault(town, []).append([int(pid), nm["n"], 1 if c.get("g") else 0, nm["l"], nm["t"], gp, pts, fs, first[3], first[0]])
    res = {}
    for co, d in out.items():
        clubs = [{"k": k, "p": sorted(v, key=lambda r: (-r[5], -r[6]))} for k, v in d.items()]
        clubs.sort(key=lambda x: (-len(x["p"]), -sum(r[5] for r in x["p"])))
        res[co] = clubs
    return res


def fetch_drafts(cache, jget, log):
    os.makedirs(os.path.join(cache, "draft"), exist_ok=True)
    y_now = int(time.strftime("%Y"))
    latest = y_now if int(time.strftime("%m")) >= 7 else y_now - 1
    got = 0
    for y in range(1963, latest + 1):
        path = os.path.join(cache, "draft", "%d.json" % y)
        fresh = os.path.exists(path) and (y < y_now or time.time() - os.path.getmtime(path) < 7 * 86400)
        if fresh:
            continue
        try:
            raw = jget("https://api-web.nhle.com/v1/draft/picks/%d/all" % y)
        except Exception as e:  # noqa: BLE001
            log("  draft %d: nelze stáhnout (%s)" % (y, e))
            continue
        picks = []
        for p in raw.get("picks") or []:
            nm = lambda k: ((p.get(k) or {}).get("default") if isinstance(p.get(k), dict) else p.get(k)) or ""
            picks.append([p.get("overallPick"), p.get("round"), p.get("pickInRound"), p.get("teamAbbrev") or "",
                          ("%s %s" % (nm("firstName"), nm("lastName"))).strip(), p.get("positionCode") or "", p.get("countryCode") or "",
                          p.get("amateurClubName") or "", p.get("amateurLeague") or ""])
        if picks:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(picks, f, ensure_ascii=False, separators=(",", ":"))
            got += 1
        time.sleep(0.3)
    log("  draft: staženo %d ročníků" % got)


def build_draft(site, cache, car, names, log):
    by_pick = {}
    for pid, c in car.items():
        d = c.get("d")
        if d and d[0] and d[4]:
            by_pick[(int(d[0]), int(d[4]))] = pid
    outdir = os.path.join(site, "draft")
    os.makedirs(outdir, exist_ok=True)
    years, cz = [], []
    for path in sorted(glob.glob(os.path.join(cache, "draft", "*.json"))):
        y = int(os.path.basename(path)[:4])
        with open(path, encoding="utf-8") as f:
            picks = json.load(f)
        rows = []
        for p in picks:
            pid = by_pick.get((y, p[0])) if p[0] else None
            c = car.get(pid) if pid else None
            gp, pts, _ = nhl_totals(c) if c else (0, 0, None)
            nm = names.get(pid) if pid else None
            g = (1 if (c and c.get("g")) else 0) if c else (1 if p[5] == "G" else 0)
            row = p + [int(pid) if pid else None, gp, pts, g, nm["l"] if nm else None]
            rows.append(row)
            if p[6] in ("CZE", "CSK", "SVK"):
                cz.append([y] + row)
        with open(os.path.join(outdir, "%d.json" % y), "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
        years.append(y)
    cz.sort(key=lambda r: (-r[0], r[1] or 999))
    with open(os.path.join(outdir, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"years": sorted(years, reverse=True), "cz": cz, "updated": time.strftime("%Y-%m-%d")}, f, ensure_ascii=False, separators=(",", ":"))
    log("  draft: %d ročníků, %d Čechů a Slováků" % (len(years), len(cz)))


def run(site, cache, data, jget, log, fetch=True):
    car = load_careers(site)
    names = load_names(site, data)
    log("  kariér: %d, jmen: %d" % (len(car), len(names)))
    with open(os.path.join(site, "repre.json"), "w", encoding="utf-8") as f:
        json.dump(build_repre(car, names), f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(site, "lihen.json"), "w", encoding="utf-8") as f:
        json.dump(build_lihen(car, names), f, ensure_ascii=False, separators=(",", ":"))
    if fetch:
        fetch_drafts(cache, jget, log)
    build_draft(site, cache, car, names, log)
    return True


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "site", "data.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    run(os.path.join(here, "site"), os.path.join(here, "cache"), d, None, print, fetch=False)
