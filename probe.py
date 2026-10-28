"""Sonda: ceny hráčů, play-off, šampioni (jen pro vývoj)."""
import json, os, urllib.request
UA = "Mozilla/5.0 (compatible; nhl-statistiky/1.0)"
OUT = "cache/probe"; os.makedirs(OUT, exist_ok=True)
def get(u, t=120):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=t).read()
def save(name, u, keep=None):
    try:
        d = json.loads(get(u))
        if keep: d = {k: d.get(k) for k in keep}
        if isinstance(d, dict) and isinstance(d.get("data"), list): d["data"] = d["data"][:40]
        json.dump({"url": u, "data": d}, open(os.path.join(OUT, name + ".json"), "w"), indent=1, ensure_ascii=False); print("ok", name)
    except Exception as e:
        json.dump({"url": u, "error": str(e)}, open(os.path.join(OUT, name + ".json"), "w")); print("ERR", name, e)
W = "https://api-web.nhle.com/v1"
for pid, n in [(8479314, "tkachuk"), (8471675, "crosby"), (8448208, "jagr"), (8471214, "ovechkin")]:
    save("landing_" + n, "%s/player/%d/landing" % (W, pid), keep=["awards", "badges", "inTop100AllTime", "inHHOF", "careerTotals"])
save("rec_trophy", "https://records.nhl.com/site/api/trophy")
save("rec_award_cup", "https://records.nhl.com/site/api/award-details?cayenneExp=trophyId=1")
save("rec_award_hart", "https://records.nhl.com/site/api/award-details?cayenneExp=trophyId=4&sort=seasonId&dir=DESC")
save("bracket_2024", W + "/playoff-bracket/2024")
save("bracket_2008", W + "/playoff-bracket/2008")
save("series_2024", W + "/schedule/playoff-series/20232024/a")
save("rest_po", "https://api.nhle.com/stats/rest/en/skater/summary?isAggregate=false&isGame=false&start=0&limit=2&cayenneExp=seasonId=20232024%20and%20gameTypeId=3")
for u in ["https://moneypuck.com/moneypuck/playerData/seasonSummary/2023/playoffs/skaters.csv", "https://moneypuck.com/moneypuck/playerData/seasonSummary/2010/playoffs/goalies.csv", "https://moneypuck.com/moneypuck/playerData/seasonSummary/2023/playoffs/lines.csv"]:
    try: print("mp", u, len(get(u)))
    except Exception as e: print("mp ERR", u, e)
