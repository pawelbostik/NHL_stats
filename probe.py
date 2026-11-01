import json, os, urllib.request
UA = "Mozilla/5.0 (compatible; nhl-statistiky/1.0; personal non-commercial stats page)"
os.makedirs("cache/probe", exist_ok=True)
res = {}
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return -1, str(e)
def j(t):
    try: return json.loads(t)
    except Exception: return None
for dt in ["goalieStats", "goalkeeperStats", "goaliesStats", "goalkeeper"]:
    for flag in ["true", "false"]:
        u = "https://liiga.fi/api/v2/players/stats/summed/2027/2027/runkosarja/%s?dataType=%s" % (flag, dt)
        st, t = get(u); d = j(t)
        gk = [x for x in d if isinstance(x, dict) and x.get("goalkeeper")] if isinstance(d, list) else []
        res["liiga %s %s" % (dt, flag)] = {"st": st, "n": len(d) if isinstance(d, list) else None, "gk": len(gk), "gk_sample": gk[:1], "keys": sorted(d[0].keys()) if isinstance(d, list) and d else None}
st, t = get("https://liiga.fi/api/v2/players/stats/summed/2027/2027/runkosarja/true?dataType=basicStats"); d = j(t) or []
res["liiga basic gk"] = [x for x in d if x.get("goalkeeper")][:2]
B = "https://data.sihf.ch/Statistic/api/cms/cache300?alias=%s&searchQuery=1/2015-2099/1&filterQuery=2027&orderBy=%s&orderByDescending=true&take=%d&filterBy=Season,Phase&skip=%d&language=de"
for alias in ["goalie", "goalkeeper", "goalieSummary", "playerGoalie", "goaltender"]:
    st, t = get(B % (alias, "rank", 20, 0)); d = j(t) or {}
    res["sihf " + alias] = {"st": st, "stub": d.get("stub"), "n": len(d.get("data") or []), "header": [h.get("alias") for h in d.get("header") or []], "row": (d.get("data") or [None])[0], "menu": d.get("secondaryMenu")}
for take, skip in [(100, 0), (100, 100), (100, 1), (20, 1), (20, 20), (500, 0)]:
    st, t = get(B % ("player", "points", take, skip)); d = j(t) or {}
    rows = d.get("data") or []
    res["sihf player take%d skip%d" % (take, skip)] = {"n": len(rows), "pages": d.get("pages"), "sel": d.get("selectedPage"), "first": rows[0][:2] if rows else None}
json.dump(res, open("cache/probe/p3.json", "w"), ensure_ascii=False, indent=1, default=str)
print("ok")
