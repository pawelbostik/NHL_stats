"""Sonda: které zdroje statistik dalších lig jsou dostupné a co o automatickém přístupu říkají jejich robots.txt."""
import json
import os
import re
import urllib.request

UA = "Mozilla/5.0 (compatible; nhl-statistiky/1.0; personal non-commercial stats page)"
OUT = os.path.join("cache", "probe")
os.makedirs(OUT, exist_ok=True)
log = []


def get(url, n=600):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return r.status, r.headers.get("content-type", ""), body
    except urllib.error.HTTPError as e:
        return e.code, "", b""
    except Exception as e:  # noqa: BLE001
        return -1, str(e)[:120], b""


def show(name, url, n=500):
    st, ct, body = get(url)
    txt = body.decode("utf-8", "replace")
    log.append("### %s\n%s\nstatus=%s type=%s len=%d\n%s\n" % (name, url, st, ct, len(body), txt[:n]))
    return st, txt


ROBOTS = ["https://lscluster.hockeytech.com/robots.txt", "https://theahl.com/robots.txt", "https://ontariohockeyleague.com/robots.txt",
          "https://chl.ca/robots.txt", "https://whl.ca/robots.txt", "https://theqmjhl.ca/robots.txt", "https://ushl.com/robots.txt",
          "https://liiga.fi/robots.txt", "https://www.nationalleague.ch/robots.txt", "https://data.sihf.ch/robots.txt", "https://www.sihf.ch/robots.txt",
          "https://www.penny-del.org/robots.txt", "https://www.shl.se/robots.txt", "https://stats.swehockey.se/robots.txt",
          "https://www.hockeyslovakia.sk/robots.txt", "https://www.hokej.cz/robots.txt", "https://www.tipsportextraliga.cz/robots.txt"]
for u in ROBOTS:
    show("robots " + u.split("/")[2], u, 1500)

# Domovské stránky: hledáme datová rozhraní a klíče, které weby samy používají.
HOMES = {"ahl": "https://theahl.com/stats/player-stats", "ohl": "https://chl.ca/ohl/stats/players/", "whl": "https://chl.ca/whl/stats/players/",
         "qmjhl": "https://chl.ca/lhjmq/en/stats/players/", "ushl": "https://ushl.com/view#/player-stats", "ohl2": "https://ontariohockeyleague.com/stats/players",
         "liiga": "https://liiga.fi/fi/tilastot", "nl": "https://www.nationalleague.ch/de/statistiken", "del": "https://www.penny-del.org/statistik",
         "shl": "https://www.shl.se/statistik/spelare", "svk": "https://www.hockeyslovakia.sk/sk/stats", "hokejcz": "https://www.hokej.cz/tipsport-extraliga/stats-center"}
found = {}
for k, u in HOMES.items():
    st, txt = show("home " + k, u, 300)
    keys = sorted(set(re.findall(r"key[\"'=:\s]+([0-9a-f]{16})", txt)))
    codes = sorted(set(re.findall(r"client_code[\"'=:\s]+([a-z]+)", txt)))
    apis = sorted(set(re.findall(r"https?://[a-zA-Z0-9.\-]+/(?:api|feed|Statistic|statistic|stats-api|data)[^\"'\s<>]{0,120}", txt)))[:30]
    scripts = sorted(set(re.findall(r"<script[^>]+src=[\"']([^\"']+)", txt)))[:25]
    found[k] = {"keys": keys, "codes": codes, "apis": apis, "scripts": scripts}
    # projdi i skripty stránky, klíče bývají v nich
    for s in scripts[:12]:
        if s.startswith("//"):
            s = "https:" + s
        elif s.startswith("/"):
            s = "/".join(u.split("/")[:3]) + s
        if not s.startswith("http"):
            continue
        st2, ct2, b2 = get(s)
        t2 = b2.decode("utf-8", "replace")
        found[k]["keys"] = sorted(set(found[k]["keys"]) | set(re.findall(r"key[\"'=:\s]+([0-9a-f]{16})", t2)))
        found[k]["codes"] = sorted(set(found[k]["codes"]) | set(re.findall(r"client_code[\"'=:\s]+[\"']?([a-z]+)", t2)))
        found[k]["apis"] = sorted(set(found[k]["apis"]) | set(re.findall(r"https?://[a-zA-Z0-9.\-]+/(?:api|feed|Statistic|statistic|stats-api|data)[^\"'\s<>`]{0,100}", t2)))[:40]
log.append("### NALEZENO\n" + json.dumps(found, indent=1, ensure_ascii=False))

# HockeyTech: zkus známé kombinace klíčů a lig + klíče nalezené na webech.
cand = {"50c2cd9b5e18e390", "f1aa699db3d81487", "2976319eb44abe94", "41b145a848f4bd67", "e828f89b243dc43f", "f322673b6bcae299"}
for v in found.values():
    cand |= set(v["keys"])
for client in ["ahl", "ohl", "whl", "lhjmq", "ushl"]:
    for key in sorted(cand):
        st, txt = show("ht %s %s" % (client, key), "https://lscluster.hockeytech.com/feed/?feed=modulekit&view=seasons&key=%s&client_code=%s&fmt=json&lang=en" % (key, client), 300)
        if st == 200 and "SiteKit" in txt and "error" not in txt[:200].lower():
            break

# Liiga a Švýcarsko: odhad veřejných datových cest
for name, u in [("liiga games", "https://liiga.fi/api/v2/games?tournament=runkosarja&season=2026"),
                ("liiga standings", "https://liiga.fi/api/v2/standings/?season=2026"),
                ("liiga players", "https://liiga.fi/api/v2/players/stats/summed/2026/2026/runkosarja/true?dataType=basicStats"),
                ("sihf standing", "https://data.sihf.ch/Statistic/api/cms/cache300?alias=standing&searchQuery=1/2015-2099/1&filterQuery=2026&orderBy=rank&orderByDescending=false&take=20&filterBy=Season&skip=-1&language=de"),
                ("sihf player", "https://data.sihf.ch/Statistic/api/cms/cache300?alias=player&searchQuery=1/2015-2099/1&filterQuery=2026&orderBy=points&orderByDescending=true&take=20&filterBy=Season,Phase&skip=0&language=de"),
                ("del players", "https://www.penny-del.org/statistik/saison-2025-26/hauptrunde/playerstats/basis/"),
                ("swehockey", "https://stats.swehockey.se/")]:
    show(name, u, 700)

with open(os.path.join(OUT, "leagues.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
print("hotovo", len(log))
