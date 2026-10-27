"""Jednorázová sonda struktur API (jen pro vývoj, výsledky do cache/probe)."""
import csv, io, json, os, urllib.request, zipfile
UA = "Mozilla/5.0 (compatible; nhl-statistiky/1.0)"
OUT = "cache/probe"; os.makedirs(OUT, exist_ok=True)
S = "20262027"; CE = "cayenneExp=seasonId=%s%%20and%%20gameTypeId=2" % S
def get(u, t=90):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=t).read()
def save(name, u, cut=None):
    try:
        d = json.loads(get(u))
        if cut and isinstance(d, dict):
            for k in cut:
                if isinstance(d.get(k), list): d[k] = d[k][:3]
        json.dump({"url": u, "data": d}, open(os.path.join(OUT, name + ".json"), "w"), indent=1, ensure_ascii=False)
        print("ok", name)
    except Exception as e:
        json.dump({"url": u, "error": str(e)}, open(os.path.join(OUT, name + ".json"), "w"), indent=1)
        print("ERR", name, e)
R = "https://api.nhle.com/stats/rest/en"
for rep in ["skater/summary", "skater/timeonice", "skater/powerplay", "skater/penaltykill", "skater/realtime", "skater/faceoffwins", "skater/penalties", "goalie/savesByStrength", "goalie/summary"]:
    save(rep.replace("/", "_"), "%s/%s?isAggregate=false&isGame=false&start=0&limit=3&%s" % (R, rep, CE))
for rep in ["team/summary", "team/powerplay", "team/penaltykill", "team/realtime"]:
    save(rep.replace("/", "_"), "%s/%s?isAggregate=false&isGame=false&start=0&limit=2&%s" % (R, rep, CE))
W = "https://api-web.nhle.com/v1"
for n, u in [("edge_skater_detail", "%s/edge/skater-detail/8478402/%s/2" % (W, S)), ("edge_skater_now", "%s/edge/skater-detail/8478402/now" % W),
             ("edge_speed", "%s/edge/skater-skating-speed-detail/8478402/%s/2" % (W, S)), ("edge_shot", "%s/edge/skater-shot-speed-detail/8478402/%s/2" % (W, S)),
             ("edge_distance", "%s/edge/skater-skating-distance-detail/8478402/%s/2" % (W, S)), ("edge_zone", "%s/edge/skater-zone-time/8478402/%s/2" % (W, S)),
             ("edge_goalie", "%s/edge/goalie-detail/8485545/%s/2" % (W, S)), ("edge_landing", "%s/edge/skater-landing/%s/2" % (W, S)),
             ("edge_team", "%s/edge/team-detail/1/%s/2" % (W, S)), ("standings", W + "/standings/now"),
             ("schedule_club", "%s/club-schedule-season/DET/%s" % (W, S)), ("schedule_week", W + "/schedule/now")]:
    save(n, u, cut=["standings", "games", "gameWeek"])
try:
    for name in ["skaters", "goalies", "teams"]:
        txt = get("https://moneypuck.com/moneypuck/playerData/seasonSummary/2026/regular/%s.csv" % name).decode()
        rows = list(csv.reader(io.StringIO(txt)))
        json.dump({"head": rows[0], "row": rows[1]}, open(os.path.join(OUT, "mp_" + name + ".json"), "w"), indent=0)
    z = zipfile.ZipFile(io.BytesIO(get("https://peter-tanner.com/moneypuck/downloads/shots_2026.zip", 180)))
    n = [x for x in z.namelist() if x.endswith(".csv")][0]
    r = csv.reader(io.TextIOWrapper(z.open(n), encoding="utf-8"))
    json.dump({"head": next(r), "row": next(r)}, open(os.path.join(OUT, "mp_shots.json"), "w"), indent=0)
    print("ok mp")
except Exception as e:
    print("ERR mp", e)
