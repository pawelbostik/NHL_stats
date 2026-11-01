"""Sonda 2: ukázky dat z HockeyTech, Liiga a SIHF (pole, sezony, národnost)."""
import json
import os
import re
import urllib.request

UA = "Mozilla/5.0 (compatible; nhl-statistiky/1.0; personal non-commercial stats page)"
OUT = os.path.join("cache", "probe")
os.makedirs(OUT, exist_ok=True)
res = {}


def get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {}, ""
    except Exception as e:  # noqa: BLE001
        return -1, {}, str(e)


def js(txt):
    t = txt.strip()
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1]
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        return None


def cut(o, n=3):
    if isinstance(o, list):
        return [cut(x, n) for x in o[:n]]
    if isinstance(o, dict):
        return {k: cut(v, n) for k, v in list(o.items())[:60]}
    return o


HT = {"ahl": "50c2cd9b5e18e390", "ohl": "2976319eb44abe94", "whl": "41b145a848f4bd67", "lhjmq": "f1aa699db3d81487", "ushl": "e828f89b243dc43f"}
B = "https://lscluster.hockeytech.com/feed/?key=%s&client_code=%s&lang=en&fmt=json&"
for cc, key in HT.items():
    base = B % (key, cc)
    r = {}
    st, h, t = get(base + "feed=modulekit&view=seasons")
    seas = (js(t) or {}).get("SiteKit", {}).get("Seasons", [])
    r["seasons"] = seas[:6]
    r["cors"] = h.get("Access-Control-Allow-Origin")
    sid = (js(t) or {}).get("SiteKit", {}).get("Parameters", {}).get("season_id")
    r["default_sid"] = sid
    st, h, t = get(base + "feed=modulekit&view=statviewtype&type=topscorers&season_id=%s&first=0&limit=3" % sid)
    r["topscorers"] = cut(js(t), 3)
    st, h, t = get(base + "feed=modulekit&view=statviewtype&type=topgoalies&season_id=%s&first=0&limit=2&qualified=all" % sid)
    r["topgoalies"] = cut(js(t), 2)
    for name, q in [("standings_mk", "feed=modulekit&view=statviewtype&type=standings&stat=conference&season_id=%s" % sid),
                    ("teams_sv", "feed=statviewfeed&view=teams&groupTeamsBy=division&context=overall&site_id=0&season=%s&special=false&league_id=&sort=points" % sid),
                    ("players_sv", "feed=statviewfeed&view=players&season=%s&team=all&position=skaters&rookies=0&statsType=standard&rosterstatus=undefined&site_id=0&first=0&limit=3&sort=points&league_id=&qualified=all" % sid)]:
        st, h, t = get(base + q)
        r[name] = {"status": st, "head": t[:200], "data": cut(js(t), 3)}
    pid = None
    try:
        pid = r["topscorers"]["SiteKit"]["Statviewtype"][0]["player_id"]
    except Exception:  # noqa: BLE001
        pass
    if pid:
        st, h, t = get(base + "feed=modulekit&view=player&category=profile&player_id=%s" % pid)
        r["profile"] = cut(js(t), 4)
    res[cc] = r

# Liiga
L = {}
st, h, t = get("https://liiga.fi/api/v2/players/stats/summed/2027/2027/runkosarja/true?dataType=basicStats")
d = js(t)
L["players2027"] = {"status": st, "n": len(d) if isinstance(d, list) else None, "sample": cut(d, 2), "cors": h.get("Access-Control-Allow-Origin")}
st, h, t = get("https://liiga.fi/api/v2/players/stats/summed/2027/2027/runkosarja/false?dataType=basicStats")
d = js(t)
L["goalies2027"] = {"status": st, "n": len(d) if isinstance(d, list) else None, "sample": cut(d, 2)}
st, h, t = get("https://liiga.fi/api/v2/standings/?season=2027")
L["standings2027"] = {"status": st, "sample": cut(js(t), 2)}
st, h, t = get("https://liiga.fi/api/v2/games?tournament=runkosarja&season=2027")
d = js(t)
L["games2027"] = {"status": st, "n": len(d) if isinstance(d, list) else None, "sample": cut(d[:1] if isinstance(d, list) else d, 2)}
res["liiga"] = L

# SIHF
S = {}
for name, u in [("player", "https://data.sihf.ch/Statistic/api/cms/cache300?alias=player&searchQuery=1/2015-2099/1&filterQuery=2027&orderBy=points&orderByDescending=true&take=20&filterBy=Season,Phase&skip=0&language=de"),
                ("goalie", "https://data.sihf.ch/Statistic/api/cms/cache300?alias=goalie&searchQuery=1/2015-2099/1&filterQuery=2027&orderBy=gaa&orderByDescending=false&take=20&filterBy=Season,Phase&skip=0&language=de"),
                ("standing", "https://data.sihf.ch/Statistic/api/cms/cache300?alias=standing&searchQuery=1/2015-2099/1&filterQuery=2027&orderBy=rank&orderByDescending=false&take=20&filterBy=Season&skip=-1&language=de")]:
    st, h, t = get(u)
    S[name] = {"status": st, "cors": h.get("Access-Control-Allow-Origin"), "sample": cut(js(t), 4), "raw": t[:1500]}
res["sihf"] = S

with open(os.path.join(OUT, "samples.json"), "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print("ok")
