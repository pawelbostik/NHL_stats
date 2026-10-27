"""Sonda pro historické sezony (jen pro vývoj)."""
import json, os, urllib.request
UA = "Mozilla/5.0 (compatible; nhl-statistiky/1.0)"
OUT = "cache/probe"; os.makedirs(OUT, exist_ok=True)
def get(u, t=120):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=t)
def save(name, u, cut=None):
    try:
        d = json.loads(get(u).read())
        if isinstance(d, dict) and isinstance(d.get("data"), list): d["data"] = d["data"][:2]
        for k in cut or []:
            if isinstance(d.get(k), list): d[k] = d[k][:2]
        json.dump({"url": u, "data": d}, open(os.path.join(OUT, name + ".json"), "w"), indent=1, ensure_ascii=False); print("ok", name)
    except Exception as e:
        json.dump({"url": u, "error": str(e)}, open(os.path.join(OUT, name + ".json"), "w")); print("ERR", name, e)
R = "https://api.nhle.com/stats/rest/en"
CE = "cayenneExp=seasonId=20082009%20and%20gameTypeId=2"
for rep in ["skater/bios", "goalie/bios", "skater/summary", "goalie/summary", "team/summary"]:
    save("h_" + rep.replace("/", "_"), "%s/%s?isAggregate=false&isGame=false&start=0&limit=2&%s" % (R, rep, CE))
save("h_standings_season", "https://api-web.nhle.com/v1/standings-season")
save("h_standings_2009", "https://api-web.nhle.com/v1/standings/2009-04-12", cut=["standings"])
save("h_team_list", "%s/team" % R)
res = {}
for y in (2007, 2008, 2009, 2015, 2025):
    for u in ["https://moneypuck.com/moneypuck/playerData/seasonSummary/%d/regular/skaters.csv" % y,
              "https://moneypuck.com/moneypuck/playerData/seasonSummary/%d/regular/lines.csv" % y,
              "https://peter-tanner.com/moneypuck/downloads/shots_%d.zip" % y]:
        try:
            r = get(u, 60); n = len(r.read()); res[u] = n
        except Exception as e:
            res[u] = str(e)
json.dump(res, open(os.path.join(OUT, "h_mp.json"), "w"), indent=1); print(res)
