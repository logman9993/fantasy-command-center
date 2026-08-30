
from flask import Flask, render_template, jsonify, request
import os, json, time, csv, io, math, statistics, re
from pathlib import Path
from difflib import SequenceMatcher
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

BASE = Path(__file__).resolve().parent
if load_dotenv:
    load_dotenv(BASE / ".env")

app = Flask(__name__)
CACHE_DIR = Path(os.getenv("CACHE_DIR", str(BASE / "data")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FANTASYPROS_KEY = os.getenv("FANTASYPROS_API_KEY", "").strip()
SEASON = int(os.getenv("NFL_SEASON", "2026"))
PRIOR_SEASON = SEASON - 1
HISTORY_YEARS = 5
TOP_N = 25
DRAFT_POSITIONS = ("QB","RB","WR","TE")
ALL_POSITIONS = ("QB","RB","WR","TE","K","DST")

SCORING = {
    "PPR":  {"rec":1.0, "rush_yd":0.1, "rec_yd":0.1, "pass_yd":0.04, "pass_td":4, "rush_td":6, "rec_td":6, "int":-2, "fum":-2},
    "HALF": {"rec":0.5, "rush_yd":0.1, "rec_yd":0.1, "pass_yd":0.04, "pass_td":4, "rush_td":6, "rec_td":6, "int":-2, "fum":-2},
    "STD":  {"rec":0.0, "rush_yd":0.1, "rec_yd":0.1, "pass_yd":0.04, "pass_td":4, "rush_td":6, "rec_td":6, "int":-2, "fum":-2},
}

ESPN_TEAMS = {
    "ARI":"22","ATL":"1","BAL":"33","BUF":"2","CAR":"29","CHI":"3","CIN":"4","CLE":"5",
    "DAL":"6","DEN":"7","DET":"8","GB":"9","HOU":"34","IND":"11","JAX":"30","KC":"12",
    "LV":"13","LAC":"24","LAR":"14","MIA":"15","MIN":"16","NE":"17","NO":"18","NYG":"19",
    "NYJ":"20","PHI":"21","PIT":"23","SF":"25","SEA":"26","TB":"27","TEN":"10","WSH":"28"
}

SOURCE_STATE = {}

def source_ok(name, detail):
    SOURCE_STATE[name] = {"ok": True, "detail": detail}

def source_fail(name, detail):
    SOURCE_STATE[name] = {"ok": False, "detail": str(detail)[:220]}

def session():
    s = requests.Session()
    retry = Retry(
        total=1, connect=1, read=1, backoff_factor=0.35,
        status_forcelist=(429,500,502,503,504),
        allowed_methods=frozenset(["GET"])
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent":"FantasyCommandCenter/6.0"})
    return s

HTTP = session()

def http_json(url, headers=None, timeout=12):
    r = HTTP.get(url, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def http_text(url, timeout=15):
    r = HTTP.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content.decode("utf-8-sig", errors="replace")

def cached_json(name, ttl, loader):
    p = CACHE_DIR / f"{name}.json"
    if p.exists() and time.time() - p.stat().st_mtime < ttl:
        return json.loads(p.read_text(encoding="utf-8"))
    data = loader()
    p.write_text(json.dumps(data), encoding="utf-8")
    return data

def cached_csv(name, ttl, urls, must_have):
    p = CACHE_DIR / f"{name}.csv"
    if p.exists() and time.time() - p.stat().st_mtime < ttl:
        text = p.read_text(encoding="utf-8", errors="replace")
        if all(x.lower() in text[:12000].lower() for x in must_have):
            return list(csv.DictReader(io.StringIO(text))), "disk cache"
    last = None
    for url in urls:
        try:
            text = http_text(url)
            if not all(x.lower() in text[:12000].lower() for x in must_have):
                raise ValueError(f"unexpected CSV schema from {url}")
            p.write_text(text, encoding="utf-8")
            return list(csv.DictReader(io.StringIO(text))), url
        except Exception as e:
            last = e
    raise RuntimeError(last or "no source URL succeeded")

def fallback():
    return json.loads((BASE / "data" / "starter.json").read_text(encoding="utf-8"))

def num(row, key, default=0.0):
    try:
        v = row.get(key, default)
        if v in (None,"","NA","NaN","null"):
            return default
        return float(v)
    except Exception:
        return default

def norm_name(s):
    s=(s or "").lower()
    return "".join(c for c in s if c.isalnum())

def player_name(p):
    return p.get("full_name") or " ".join(x for x in [p.get("first_name"),p.get("last_name")] if x)

def nflverse_player_urls(year):
    return [f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_{year}.csv"]

def nflverse_team_week_urls(year):
    return [f"https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{year}.csv"]

def injury_urls(year):
    return [f"https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{year}.csv"]

@lru_cache(maxsize=12)
def load_year_stats(year):
    try:
        rows, src = cached_csv(
            f"stats_player_reg_{year}", 86400*7,
            nflverse_player_urls(year),
            ["player_display_name","position","passing_yards"]
        )
        source_ok(f"player_{year}", f"nflverse {src}")
        return rows
    except Exception as e:
        source_fail(f"player_{year}", e)
        raise

@lru_cache(maxsize=4)
def load_team_weekly_stats(year):
    try:
        rows, src = cached_csv(
            f"stats_team_week_{year}", 86400*7,
            nflverse_team_week_urls(year),
            ["opponent_team","passing_yards","sacks_suffered"]
        )
        source_ok("team_stats", f"nflverse weekly {year}")
        return rows
    except Exception as e:
        source_fail("team_stats", f"nflverse failed: {e}")
        return []

def sleeper_players():
    try:
        data = cached_json(
            "sleeper_players", 86400,
            lambda: http_json("https://api.sleeper.app/v1/players/nfl?active=true")
        )
        source_ok("sleeper_players", f"{len(data):,} active-player records")
        return data
    except Exception as e:
        source_fail("sleeper_players", e)
        return {}

def sleeper_trending():
    try:
        data = cached_json(
            "sleeper_trending", 900,
            lambda: http_json("https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=24&limit=250")
        )
        source_ok("sleeper_trending", f"{len(data)} trending add records")
        return data
    except Exception as e:
        source_fail("sleeper_trending", e)
        return []

def fp(endpoint, params=None):
    if not FANTASYPROS_KEY:
        raise RuntimeError("FantasyPros API key not configured")
    q = "?" + requests.compat.urlencode(params) if params else ""
    return http_json(
        "https://api.fantasypros.com/public/v2/json" + endpoint + q,
        headers={"x-api-key":FANTASYPROS_KEY}
    )

def normalize_fp_players(payload):
    arr = payload.get("players", payload if isinstance(payload, list) else [])
    out=[]
    for p in arr:
        out.append({
            "name":p.get("player_name") or p.get("name") or "",
            "team":p.get("player_team_id") or p.get("team") or "",
            "position":p.get("player_position_id") or p.get("position") or "",
            "rank":p.get("rank_ecr") or p.get("rank") or 999,
            "tier":p.get("tier"), "adp":p.get("rank_adp") or p.get("adp"),
            "best":p.get("rank_min"), "worst":p.get("rank_max"), "sd":p.get("rank_std"),
            "source":"FantasyPros ECR"
        })
    return out

def fantasy_points(row, scoring):
    s=SCORING.get(scoring,SCORING["PPR"])
    fum = num(row,"rushing_fumbles_lost")+num(row,"receiving_fumbles_lost")+num(row,"sack_fumbles_lost")
    base=(
        num(row,"passing_yards")*s["pass_yd"] +
        num(row,"passing_tds")*s["pass_td"] +
        num(row,"passing_interceptions")*s["int"] +
        num(row,"rushing_yards")*s["rush_yd"] +
        num(row,"rushing_tds")*s["rush_td"] +
        num(row,"receiving_yards")*s["rec_yd"] +
        num(row,"receiving_tds")*s["rec_td"] +
        num(row,"receptions")*s["rec"] +
        fum*s["fum"] +
        2*(num(row,"passing_2pt_conversions")+num(row,"rushing_2pt_conversions")+num(row,"receiving_2pt_conversions")) +
        6*num(row,"special_teams_tds")
    )
    pos=(row.get("position") or "").upper()
    if pos in ("K","PK"):
        # Common redraft baseline if a league has not supplied custom kicker scoring.
        base += 3*num(row,"field_goals_made") + num(row,"extra_points_made")
    return base

def games(row):
    return num(row,"games",0) or num(row,"games_played",0) or 17


_ROW_INDEX = {}

def _row_index(rows):
    cache_key=id(rows)
    cached=_ROW_INDEX.get(cache_key)
    if cached is not None:
        return cached
    exact={}
    bypos={}
    for r in rows:
        rn=norm_name(r.get("player_display_name") or r.get("player_name") or r.get("name"))
        if not rn:
            continue
        rp=(r.get("position") or r.get("position_group") or "").upper()
        exact[(rn,rp)]=r
        bypos.setdefault(rp,[]).append((rn,r))
    cached=(exact,bypos)
    _ROW_INDEX[cache_key]=cached
    return cached

def find_row(rows,name,pos=None):
    target=norm_name(name)
    exact,bypos=_row_index(rows)
    wanted=[]
    if pos=="K":
        wanted=["K","PK"]
    elif pos:
        wanted=[pos]
    else:
        wanted=list(bypos)

    for rp in wanted:
        r=exact.get((target,rp))
        if r is not None:
            return r

    # Fuzzy fallback is now restricted to the requested position and is only
    # used when an exact normalized name match fails.
    best=None
    bestscore=0
    for rp in wanted:
        for rn,r in bypos.get(rp,[]):
            score=SequenceMatcher(None,target,rn).ratio()
            if score>bestscore:
                best,bestscore=r,score
    return best if bestscore>=0.93 else None

def projection(history):
    if not history:
        return None
    recent=sorted(history,key=lambda x:x["season"])[-HISTORY_YEARS:]
    weights=list(range(1,len(recent)+1))
    avg=sum(x["ppg"]*w for x,w in zip(recent,weights))/sum(weights)
    trend=0
    if len(recent)>=2:
        xs=list(range(len(recent))); ys=[x["ppg"] for x in recent]
        xb=sum(xs)/len(xs); yb=sum(ys)/len(ys)
        den=sum((x-xb)**2 for x in xs)
        slope=sum((x-xb)*(y-yb) for x,y in zip(xs,ys))/den if den else 0
        trend=max(-2.5,min(2.5,slope))*0.35
    return round(max(0,avg+trend),1)

def history_for(name,pos,scoring,yearly):
    hist=[]; prior=None
    for year,rows in yearly.items():
        r=find_row(rows,name,pos)
        if not r:
            continue
        pts=fantasy_points(r,scoring); g=games(r)
        hist.append({"season":year,"points":round(pts,1),"games":int(round(g)),"ppg":round(pts/g if g else 0,1)})
        if year==PRIOR_SEASON:
            prior=r
    return hist,prior

def sleeper_position_fallback(pos, existing=None, limit=TOP_N):
    existing=existing or []
    seen={norm_name(x.get("name")) for x in existing}
    vals=[]
    for p in sleeper_players().values():
        pp=(p.get("position") or "").upper()
        if pos=="DST":
            continue
        if pos=="K":
            valid=pp in ("K","PK")
        else:
            valid=pp==pos
        if not valid or not p.get("team") or not p.get("active",True):
            continue
        name=player_name(p)
        if not name or norm_name(name) in seen:
            continue
        sr=p.get("search_rank")
        try: sr=float(sr)
        except: sr=999999
        depth=p.get("depth_chart_order")
        try: depth=float(depth)
        except: depth=99
        vals.append((sr,depth,name,p.get("team"),pp))
    vals.sort(key=lambda x:(x[0],x[1],x[2]))
    out=list(existing)
    for sr,depth,name,team,pp in vals:
        out.append({
            "name":name,"team":team,"position":pos,"rank":len(out)+1,
            "tier":None,"adp":None,"source":"Sleeper current-player fallback",
            "starter_basis":"Current rostered player • Sleeper search/depth rank"
        })
        if len(out)>=limit:
            break
    return out[:limit]


def dst_fallback(existing=None,limit=TOP_N):
    existing=existing or []
    seen={str(x.get("team") or x.get("name") or "").upper() for x in existing}
    vals=[]
    players=sleeper_players()
    for pid,p in players.items():
        pp=(p.get("position") or "").upper()
        team=(p.get("team") or pid or "").upper()
        if pp not in ("DEF","DST") and pid.upper() not in ESPN_TEAMS:
            continue
        if team not in ESPN_TEAMS and pid.upper() in ESPN_TEAMS:
            team=pid.upper()
        if team not in ESPN_TEAMS or team in seen:
            continue
        try: sr=float(p.get("search_rank"))
        except: sr=999999
        vals.append((sr,team))
    vals.sort(key=lambda x:(x[0],x[1]))
    out=list(existing)
    for sr,team in vals:
        out.append({"name":team,"team":team,"position":"DST","rank":len(out)+1,
                    "source":"Sleeper DST fallback","starter_basis":"Current team defense • Sleeper rank"})
        seen.add(team)
        if len(out)>=limit: return out[:limit]
    # Absolute last resort: ensure 25 real NFL team defenses exist on the board.
    for team in ESPN_TEAMS:
        if team in seen: continue
        out.append({"name":team,"team":team,"position":"DST","rank":len(out)+1,
                    "source":"NFL team-list fallback","starter_basis":"Rank unavailable • team retained so board stays complete"})
        if len(out)>=limit: break
    return out[:limit]


def build_model_rankings(scoring):
    result={p:[] for p in ALL_POSITIONS}
    try:
        prior_rows=load_year_stats(PRIOR_SEASON)
    except Exception:
        prior_rows=[]
    current=sleeper_players()
    current_by_name={}
    for p in current.values():
        n=norm_name(player_name(p))
        if n and p.get("team") and p.get("active",True):
            current_by_name[n]=p

    # Rank prior-season producers, then restrict to current rostered players.
    if prior_rows:
        for pos in ("QB","RB","WR","TE","K"):
            candidates=[]
            for r in prior_rows:
                rp=(r.get("position") or r.get("position_group") or "").upper()
                valid=(rp in ("K","PK")) if pos=="K" else (rp==pos)
                if not valid:
                    continue
                name=r.get("player_display_name") or r.get("player_name") or r.get("name")
                cur=current_by_name.get(norm_name(name))
                if not name or not cur:
                    continue
                pts=fantasy_points(r,scoring)
                g=games(r)
                ppg=pts/g if g else 0
                candidates.append((ppg,pts,name,cur.get("team")))
            candidates.sort(key=lambda x:(x[0],x[1]),reverse=True)
            for i,(ppg,pts,name,team) in enumerate(candidates[:TOP_N],1):
                result[pos].append({
                    "name":name,"team":team,"position":pos,"rank":i,
                    "tier":None,"adp":None,
                    "source":f"{PRIOR_SEASON} production fallback",
                    "starter_basis":f"{ppg:.1f} prior-year PPG"
                })
            result[pos]=sleeper_position_fallback(pos,result[pos],TOP_N)
    else:
        for pos in ("QB","RB","WR","TE","K"):
            result[pos]=sleeper_position_fallback(pos,[],TOP_N)

    # Do not make the initial page wait on team-stat downloads.
    result["DST"]=dst_fallback([],TOP_N)
    return result

def rankings(scoring):
    result={}
    model=None
    for pos in ALL_POSITIONS:
        live=[]
        if FANTASYPROS_KEY:
            try:
                data=cached_json(
                    f"fp_rank_{SEASON}_{pos}_{scoring}",1800,
                    lambda pos=pos:fp(f"/nfl/{SEASON}/consensus-rankings",{"position":pos,"scoring":scoring,"type":"redraft"})
                )
                live=normalize_fp_players(data)[:TOP_N]
                if live:
                    source_ok(f"rank_{pos}",f"FantasyPros ECR ({len(live)})")
            except Exception as e:
                source_fail(f"rank_{pos}",e)
        if len(live)<TOP_N:
            if model is None:
                model=build_model_rankings(scoring)
            seen={norm_name(x["name"]) for x in live}
            for p in model.get(pos,[]):
                if norm_name(p["name"]) not in seen:
                    live.append(p); seen.add(norm_name(p["name"]))
                if len(live)>=TOP_N:
                    break
        # Final starter fallback only after model + Sleeper fallback.
        if len(live)<TOP_N:
            seen={norm_name(x["name"]) for x in live}
            for p in fallback().get("rankings",{}).get(pos,[]):
                if norm_name(p.get("name")) not in seen:
                    q=dict(p); q.setdefault("source","bundled fallback")
                    live.append(q); seen.add(norm_name(q.get("name")))
                if len(live)>=TOP_N: break
        result[pos]=live[:TOP_N]
        if len(result[pos])>=TOP_N and f"rank_{pos}" not in SOURCE_STATE:
            source_ok(f"rank_{pos}",f"{result[pos][0].get('source','model')} ({len(result[pos])})")
    return result

def metric_rank(rows,pos,key,higher=True):
    vals=[]
    for r in rows:
        rp=(r.get("position") or r.get("position_group") or "").upper()
        if pos=="K":
            ok=rp in ("K","PK")
        else:
            ok=rp==pos
        if not ok: continue
        v=num(r,key,None)
        if v is not None:
            vals.append(v)
    vals.sort(reverse=higher)
    return vals

def rank_of(value,vals,higher=True):
    if value is None or not vals: return None
    if higher:
        return 1+sum(1 for x in vals if x>value)
    return 1+sum(1 for x in vals if x<value)

def player_kpis(row,pos,position_rows):
    if not row: return []
    if pos=="QB":
        att=num(row,"attempts"); comp=num(row,"completions")
        spec=[("Pass Yds","passing_yards",num(row,"passing_yards"),True),
              ("Pass TD","passing_tds",num(row,"passing_tds"),True),
              ("Rush Yds","rushing_yards",num(row,"rushing_yards"),True),
              ("Rush TD","rushing_tds",num(row,"rushing_tds"),True),
              ("Comp %",None,(comp/att*100 if att else 0),True),
              ("INT","passing_interceptions",num(row,"passing_interceptions"),False)]
    elif pos=="RB":
        spec=[("Rush Yds","rushing_yards",num(row,"rushing_yards"),True),
              ("Rush TD","rushing_tds",num(row,"rushing_tds"),True),
              ("Receptions","receptions",num(row,"receptions"),True),
              ("Rec Yds","receiving_yards",num(row,"receiving_yards"),True),
              ("Targets","targets",num(row,"targets"),True),
              ("Touches",None,num(row,"carries")+num(row,"receptions"),True)]
    elif pos in ("WR","TE"):
        spec=[("Targets","targets",num(row,"targets"),True),
              ("Receptions","receptions",num(row,"receptions"),True),
              ("Rec Yds","receiving_yards",num(row,"receiving_yards"),True),
              ("Rec TD","receiving_tds",num(row,"receiving_tds"),True),
              ("Target Share","target_share",num(row,"target_share")*100,True),
              ("Air Yds Share","air_yards_share",num(row,"air_yards_share")*100,True)]
    else:
        spec=[("FG Made","field_goals_made",num(row,"field_goals_made"),True),
              ("XP Made","extra_points_made",num(row,"extra_points_made"),True)]
    out=[]
    for label,key,value,higher in spec:
        vals=metric_rank(position_rows,pos,key,higher) if key else []
        rank=rank_of(value if key not in ("target_share","air_yards_share") else value/100,vals,higher) if key else None
        if "Share" in label or label.endswith("%"):
            disp=f"{value:.1f}%"
        else:
            disp=f"{int(round(value)):,}"
        out.append({"label":label,"value":disp,"raw":round(value,2),"rank":rank,"pool":len(vals) if vals else None})
    return out

def analysis_text(name,pos,last,proj,kpis,history):
    notes=[]
    if last is not None and proj is not None:
        delta=round(proj-last,1)
        if delta>=2:
            notes.append(f"The model flags a breakout trajectory: {proj} projected PPG is {delta} above last season.")
        elif delta>=0.5:
            notes.append(f"Production is trending upward, with a modest rise from {last} to {proj} projected PPG.")
        elif delta<=-2:
            notes.append(f"There is regression risk: the model falls from {last} last year to {proj} projected PPG.")
        else:
            notes.append(f"The model sees a stable profile around {proj} PPG rather than a major breakout or collapse.")
    ranked=[k for k in kpis if k.get("rank") and k.get("pool")]
    ranked.sort(key=lambda x:x["rank"])
    for k in ranked[:2]:
        notes.append(f"{k['label']} ranked #{k['rank']} among {pos}s in {PRIOR_SEASON}.")
    if len(history)<=2:
        notes.append("The forecast has a smaller NFL sample, so the uncertainty band is wider than for veterans.")
    elif len(history)>=4:
        vals=[x["ppg"] for x in sorted(history,key=lambda x:x["season"])]
        if max(vals)-min(vals)<=3:
            notes.append("Multi-year scoring has been relatively consistent, which improves floor confidence.")
    return " ".join(notes)


@lru_cache(maxsize=512)
def player_analysis_one(name,pos,scoring):
    yearly={}
    for y in range(SEASON-HISTORY_YEARS,SEASON):
        try:
            yearly[y]=load_year_stats(y)
        except Exception:
            continue
    if not yearly:
        return None
    prior_rows=yearly.get(PRIOR_SEASON,[])
    hist,prior=history_for(name,pos,scoring,yearly)
    prev=next((x for x in hist if x["season"]==PRIOR_SEASON),None)
    kpis=player_kpis(prior,pos,prior_rows) if prior else []
    proj=projection(hist)
    return {
        "name":name,"position":pos,
        "last_year_ppg":prev["ppg"] if prev else None,
        "last_year_total":prev["points"] if prev else None,
        "last_year_games":prev["games"] if prev else None,
        "projected_ppg":proj,
        "history":sorted(hist,key=lambda x:x["season"],reverse=True),
        "kpis":kpis,"model_years":len(hist),
        "analysis":analysis_text(name,pos,prev["ppg"] if prev else None,proj,kpis,hist)
    }

def analytics_for_rankings(rankings_data,scoring):
    try:
        yearly={y:load_year_stats(y) for y in range(SEASON-HISTORY_YEARS,SEASON)}
        prior_rows=yearly.get(PRIOR_SEASON,[])
    except Exception as e:
        return {},str(e)
    result={}
    for pos in ("QB","RB","WR","TE","K"):
        for player in rankings_data.get(pos,[])[:TOP_N]:
            name=player.get("name")
            hist,prior=history_for(name,pos,scoring,yearly)
            prev=next((x for x in hist if x["season"]==PRIOR_SEASON),None)
            kpis=player_kpis(prior,pos,prior_rows) if prior else []
            proj=projection(hist)
            result[norm_name(name)]={
                "name":name,"position":pos,
                "last_year_ppg":prev["ppg"] if prev else None,
                "last_year_total":prev["points"] if prev else None,
                "last_year_games":prev["games"] if prev else None,
                "projected_ppg":proj,
                "history":sorted(hist,key=lambda x:x["season"],reverse=True),
                "kpis":kpis,"model_years":len(hist),
                "analysis":analysis_text(name,pos,prev["ppg"] if prev else None,proj,kpis,hist)
            }
    return result,None

@lru_cache(maxsize=8)
def load_injury_year(year):
    try:
        rows,src=cached_csv(f"injuries_{year}",86400*30,injury_urls(year),["full_name","report_status"])
        return rows
    except Exception:
        return []


@lru_cache(maxsize=1)
def injury_history_index():
    index={}
    years=list(range(max(2009,SEASON-6),min(SEASON,2025)))
    # Download/parse the independent season files concurrently.
    with ThreadPoolExecutor(max_workers=min(5,len(years))) as ex:
        futures={ex.submit(load_injury_year,y):y for y in years}
        for fut in as_completed(futures):
            try:
                season_rows=fut.result()
            except Exception:
                season_rows=[]
            for r in season_rows:
                name=norm_name(r.get("full_name"))
                if not name:
                    continue
                injury=(r.get("report_primary_injury") or r.get("practice_primary_injury") or "").strip()
                if not injury:
                    continue
                try: week=int(float(r.get("week") or 0))
                except: week=0
                try: season=int(float(r.get("season") or futures[fut]))
                except: season=futures[fut]
                index.setdefault(name,[]).append({
                    "season":season,"week":week,"injury":injury,
                    "status":(r.get("report_status") or "").strip()
                })
    for rows in index.values():
        rows.sort(key=lambda x:(x["season"],x["week"]))
    return index

@lru_cache(maxsize=256)
def injury_episodes_cached(name):
    rows=list(injury_history_index().get(norm_name(name),[]))
    eps=[]
    for r in rows:
        same=eps and eps[-1]["season"]==r["season"] and eps[-1]["injury"].lower()==r["injury"].lower() and r["week"]<=eps[-1]["last_week"]+1
        if same:
            ep=eps[-1]
            ep["last_week"]=max(ep["last_week"],r["week"])
            ep["weeks_reported"]+=1
            if r["status"].lower()=="out": ep["weeks_out"]+=1
            if r["status"]: ep["statuses"].add(r["status"])
        else:
            eps.append({
                "season":r["season"],"first_week":r["week"],"last_week":r["week"],
                "injury":r["injury"],"weeks_reported":1,
                "weeks_out":1 if r["status"].lower()=="out" else 0,
                "statuses":set([r["status"]]) if r["status"] else set()
            })
    out=[]
    for ep in reversed(eps[-2:]):
        out.append({
            "season":ep["season"],"injury":ep["injury"],
            "weeks_reported":ep["weeks_reported"],"weeks_out":ep["weeks_out"],
            "week_range":f"Wk {ep['first_week']}" if ep["first_week"]==ep["last_week"] else f"Wks {ep['first_week']}-{ep['last_week']}",
            "statuses":", ".join(sorted(ep["statuses"]))
        })
    return out

def draftable_names(rankings_data):
    return {norm_name(p["name"]) for pos in DRAFT_POSITIONS for p in rankings_data.get(pos,[])[:TOP_N]}

def injury_risk(rankings_data):
    players=sleeper_players()
    draftable=draftable_names(rankings_data)
    candidates=[]
    for p in players.values():
        pos=(p.get("position") or "").upper()
        if pos not in DRAFT_POSITIONS or not p.get("team") or not p.get("active",True): continue
        name=player_name(p)
        if norm_name(name) not in draftable: continue
        episodes=injury_episodes_cached(name)
        status=str(p.get("injury_status") or "").strip()
        age=num(p,"age",0); score=0; reasons=[]
        if status:
            score+=45; reasons.append(f"current: {status}")
        if episodes:
            outweeks=sum(x["weeks_out"] for x in episodes)
            repweeks=sum(x["weeks_reported"] for x in episodes)
            score+=min(35,outweeks*7+repweeks*2)
            reasons.append(f"{len(episodes)} recent documented episode(s)")
        if age>=30:
            score+=min(15,(age-29)*3)
            reasons.append(f"age {int(age)}")
        analysis = (
            f"{name} has {sum(x['weeks_out'] for x in episodes)} documented week(s) listed Out across the two most recent "
            f"available injury episodes." if episodes else
            f"No matching historical nflverse injury episode was found; the score is driven by current designation/age."
        )
        if status:
            analysis += f" Current Sleeper designation: {status}."
        elif not episodes:
            analysis += " No current Sleeper injury designation is present, so this is a comparatively low-risk profile."
        candidates.append({"name":name,"team":p.get("team"),"position":pos,"risk":round(min(score,100)),
                           "reason":", ".join(reasons),"recent_injuries":episodes,"analysis":analysis})
    candidates.sort(key=lambda x:x["risk"],reverse=True)
    # If fewer than 25 have meaningful risk, show only meaningful risks rather than manufacturing risk scores.
    return candidates[:TOP_N]

def sleeper_candidates(rankings_data):
    players=sleeper_players(); trend=sleeper_trending()
    drafted=draftable_names(rankings_data)
    result=[]; seen=set()
    for t in trend:
        p=players.get(str(t.get("player_id")),{})
        pos=(p.get("position") or "").upper()
        name=player_name(p)
        if pos not in DRAFT_POSITIONS or not p.get("team") or not name: continue
        n=norm_name(name)
        # A sleeper board is more useful when it excludes obvious Top-25 positional names.
        if n in drafted or n in seen: continue
        seen.add(n)
        result.append({"name":name,"team":p.get("team"),"position":pos,"adds":int(t.get("count") or 0),
                       "search_rank":p.get("search_rank"),"reason":"Trending on Sleeper"})
        if len(result)>=TOP_N: break
    # Fill with current rostered players by Sleeper search rank if trend data is short.
    if len(result)<TOP_N:
        vals=[]
        for p in players.values():
            pos=(p.get("position") or "").upper(); name=player_name(p); n=norm_name(name)
            if pos not in DRAFT_POSITIONS or not p.get("team") or not name or n in drafted or n in seen: continue
            try: sr=float(p.get("search_rank"))
            except: sr=999999
            vals.append((sr,name,p))
        vals.sort(key=lambda x:x[0])
        for sr,name,p in vals:
            seen.add(norm_name(name))
            result.append({"name":name,"team":p.get("team"),"position":p.get("position"),"adds":0,
                           "search_rank":sr,"reason":"Current rostered upside candidate"})
            if len(result)>=TOP_N: break
    return result[:TOP_N]

def sleeper_breakout(player,analytics=None):
    pos=player.get("position"); adds=player.get("adds",0); a=analytics or {}
    proj=a.get("projected_ppg"); last=a.get("last_year_ppg")
    why=[]
    if adds>=500: why.append("Heavy add momentum says the market is starting to notice him.")
    elif adds>=100: why.append("He has meaningful Sleeper add momentum but is not yet an obvious early-round name.")
    elif adds>0: why.append("He is beginning to draw waiver/draft attention while still sitting outside the Top-25 positional board.")
    else: why.append("He remains outside the Top-25 positional board, which keeps the acquisition cost low.")
    if proj is not None and last is not None:
        delta=round(proj-last,1)
        if delta>=1: why.append(f"The production model rises from {last} to {proj} PPG.")
        elif delta<=-1: why.append(f"The historical model is cautious ({proj} PPG), so this is a role/price sleeper rather than a pure projection breakout.")
        else: why.append(f"The model is stable around {proj} PPG, making price and role the main upside levers.")
    if a.get("analysis"): why.append(a["analysis"])
    upside_map={
        "RB":"A jump in touches, goal-line work or receiving usage can move him quickly into RB2/FLEX territory.",
        "WR":"A target-share increase can create weekly FLEX/WR2 value, especially if route participation rises.",
        "TE":"TE is shallow enough that a moderate target and red-zone jump can create a weekly positional advantage.",
        "QB":"Rushing volume or a touchdown-rate jump can turn a late QB into a weekly starter."
    }
    try: sr=float(player.get("search_rank") or 9999)
    except: sr=9999
    if sr<=100: acquire="Draft: roughly Rounds 9-11 if the room is getting aggressive; do not count on waivers."
    elif sr<=180: acquire="Draft: roughly Rounds 12-15 as an upside bench stash."
    else: acquire="Waivers: leave him on the watch list in shallow leagues and react to Week 1 usage."
    return {"why":" ".join(why),"upside":upside_map.get(pos,"Role growth creates the upside case."),"acquisition":acquire}

def enrich_sleepers(items,analytics):
    out=[]
    for p in items[:TOP_N]:
        q=dict(p); q.update(sleeper_breakout(q,analytics.get(norm_name(q["name"]))))
        out.append(q)
    return out

def rank_metric(rows,key,higher=True):
    vals=[(r["team"],r[key]) for r in rows if r.get(key) is not None]
    distinct=sorted({v for _,v in vals}, reverse=higher)
    value_rank={v:i+1 for i,v in enumerate(distinct)}
    return {team:value_rank[value] for team,value in vals}

def team_points_estimate(r):
    tds=num(r,"passing_tds")+num(r,"rushing_tds")+num(r,"special_teams_tds")
    xp=num(r,"extra_points_made")
    fg=num(r,"field_goals_made")
    two=num(r,"passing_2pt_conversions")+num(r,"rushing_2pt_conversions")
    return 6*tds+xp+3*fg+2*two

def aggregate_nflverse_team_rows(rows):
    offenses={}; defenses={}
    for r in rows:
        if (r.get("season_type") or "REG")!="REG": continue
        team=(r.get("team") or "").strip(); opp=(r.get("opponent_team") or "").strip()
        if not team or not opp: continue
        o=offenses.setdefault(team,{"team":team,"games":0,"yards":0.0,"tds":0.0,"epa":0.0,"turnovers":0.0,"points":0.0})
        yards=num(r,"passing_yards")+num(r,"rushing_yards")
        tds=num(r,"passing_tds")+num(r,"rushing_tds")+num(r,"special_teams_tds")
        epa=num(r,"passing_epa")+num(r,"rushing_epa")
        tos=num(r,"passing_interceptions")+num(r,"rushing_fumbles_lost")+num(r,"receiving_fumbles_lost")+num(r,"sack_fumbles_lost")
        pts=team_points_estimate(r)
        o["games"]+=1; o["yards"]+=yards; o["tds"]+=tds; o["epa"]+=epa; o["turnovers"]+=tos; o["points"]+=pts
        d=defenses.setdefault(opp,{"team":opp,"games":0,"yards_allowed":0.0,"tds_allowed":0.0,"epa_allowed":0.0,"sacks":0.0,"takeaways":0.0,"points_allowed":0.0})
        d["games"]+=1; d["yards_allowed"]+=yards; d["tds_allowed"]+=tds; d["epa_allowed"]+=epa
        d["sacks"]+=num(r,"sacks_suffered"); d["takeaways"]+=tos; d["points_allowed"]+=pts
    return list(offenses.values()),list(defenses.values())

def espn_flat_stats(team_id):
    url=f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{PRIOR_SEASON}/types/2/teams/{team_id}/statistics"
    d=http_json(url)
    flat={}
    for cat in ((d.get("splits") or {}).get("categories") or []):
        for s in cat.get("stats") or []:
            name=s.get("name")
            if name:
                flat[name]=s.get("value")
                flat[name.lower()]=s.get("value")
    return flat

def pickstat(flat,*names):
    for n in names:
        if n in flat and flat[n] is not None:
            try:return float(flat[n])
            except: pass
        if n.lower() in flat and flat[n.lower()] is not None:
            try:return float(flat[n.lower()])
            except: pass
    return None


def espn_team_fallback():
    rows=[]
    errors=0
    def one(item):
        abbr,tid=item
        flat=cached_json(
            f"espn_team_{PRIOR_SEASON}_{tid}",86400*7,
            lambda tid=tid:espn_flat_stats(tid)
        )
        return {
            "team":abbr,
            "points":pickstat(flat,"totalPoints","pointsFor","points"),
            "yards":pickstat(flat,"netYards","totalYards","yards"),
            "turnovers":pickstat(flat,"totalGiveaways","turnovers","giveaways"),
            "points_allowed":pickstat(flat,"pointsAllowed","totalPointsAllowed"),
            "yards_allowed":pickstat(flat,"netYardsAllowed","totalYardsAllowed","yardsAllowed"),
            "sacks":pickstat(flat,"sacks","defensiveSacks"),
            "takeaways":pickstat(flat,"totalTakeaways","takeaways"),
        }
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures=[ex.submit(one,item) for item in ESPN_TEAMS.items()]
        for fut in as_completed(futures):
            try:
                rows.append(fut.result())
            except Exception:
                errors+=1
    if rows:
        source_ok("team_stats_espn",f"ESPN fallback: {len(rows)} teams ({errors} errors)")
    else:
        source_fail("team_stats_espn","No ESPN team statistics returned")
    return rows

def team_analysis_cards(offenses,defenses,source):
    off_cards=[]; def_cards=[]
    if offenses:
        for r in offenses:
            gp=max(1,r.get("games",17))
            r["ppg"]=r["points"]/gp if r.get("points") is not None else None
            r["ypg"]=r["yards"]/gp if r.get("yards") is not None else None
        off_metrics=[
            ("points",True,"points"),
            ("yards",True,"yards"),
            ("epa",True,"EPA"),
            ("tds",True,"TDs"),
            ("turnovers",False,"turnovers")
        ]
        active=[m for m in off_metrics if any(r.get(m[0]) not in (None,0) for r in offenses)]
        ranks={key:rank_metric(offenses,key,higher) for key,higher,_ in active}
        for r in offenses:
            available=[ranks[key][r["team"]] for key,_,_ in active if r["team"] in ranks[key]]
            r["score"]=sum(available)/len(available) if available else 999
        offenses.sort(key=lambda r:r["score"])
        for i,r in enumerate(offenses[:10],1):
            pieces=[f"#{ranks[k][r['team']]} {label}" for k,_,label in active if r["team"] in ranks[k]]
            analysis=f"{r['team']} grades as the #{i} composite offense using " + ", ".join(pieces) + "."
            stats=[]
            if "points" in ranks:
                stats += [{"label":"Est. Points","value":f"{int(r['points']):,}","league_rank":ranks["points"][r["team"]]},
                          {"label":"Points/Game","value":f"{r['ppg']:.1f}","league_rank":ranks["points"][r["team"]]}]
            if "yards" in ranks:
                stats += [{"label":"Total Yards","value":f"{int(r['yards']):,}","league_rank":ranks["yards"][r["team"]]},
                          {"label":"Yards/Game","value":f"{r['ypg']:.1f}","league_rank":ranks["yards"][r["team"]]}]
            if "epa" in ranks:
                stats.append({"label":"Offensive EPA","value":f"{r['epa']:.1f}","league_rank":ranks["epa"][r["team"]]})
            if "tds" in ranks:
                stats.append({"label":"Touchdowns","value":f"{int(r['tds'])}","league_rank":ranks["tds"][r["team"]]})
            if "turnovers" in ranks:
                stats.append({"label":"Turnovers","value":f"{int(r['turnovers'])}","league_rank":ranks["turnovers"][r["team"]]})
            off_cards.append({"name":r["team"],"team":r["team"],"rank":i,"source":source,"analysis":analysis,
                              "summary":" • ".join(pieces[:4]),"stats":stats})
    if defenses:
        for r in defenses:
            gp=max(1,r.get("games",17))
            r["papg"]=r["points_allowed"]/gp if r.get("points_allowed") is not None else None
            r["yapg"]=r["yards_allowed"]/gp if r.get("yards_allowed") is not None else None
        def_metrics=[
            ("points_allowed",False,"points allowed"),
            ("yards_allowed",False,"yards allowed"),
            ("epa_allowed",False,"EPA allowed"),
            ("sacks",True,"sacks"),
            ("takeaways",True,"takeaways")
        ]
        active=[m for m in def_metrics if any(r.get(m[0]) not in (None,0) for r in defenses)]
        ranks={key:rank_metric(defenses,key,higher) for key,higher,_ in active}
        for r in defenses:
            available=[ranks[key][r["team"]] for key,_,_ in active if r["team"] in ranks[key]]
            r["score"]=sum(available)/len(available) if available else 999
        defenses.sort(key=lambda r:r["score"])
        for i,r in enumerate(defenses[:10],1):
            pieces=[f"#{ranks[k][r['team']]} {label}" for k,_,label in active if r["team"] in ranks[k]]
            analysis=f"{r['team']} grades as the #{i} composite defense using " + ", ".join(pieces) + "."
            stats=[]
            if "points_allowed" in ranks:
                stats += [{"label":"Est. Points Allowed","value":f"{int(r['points_allowed']):,}","league_rank":ranks["points_allowed"][r["team"]]},
                          {"label":"Points Allowed/G","value":f"{r['papg']:.1f}","league_rank":ranks["points_allowed"][r["team"]]}]
            if "yards_allowed" in ranks:
                stats += [{"label":"Yards Allowed","value":f"{int(r['yards_allowed']):,}","league_rank":ranks["yards_allowed"][r["team"]]},
                          {"label":"Yards Allowed/G","value":f"{r['yapg']:.1f}","league_rank":ranks["yards_allowed"][r["team"]]}]
            if "sacks" in ranks:
                stats.append({"label":"Sacks","value":f"{int(r['sacks'])}","league_rank":ranks["sacks"][r["team"]]})
            if "takeaways" in ranks:
                stats.append({"label":"Takeaways","value":f"{int(r['takeaways'])}","league_rank":ranks["takeaways"][r["team"]]})
            if "epa_allowed" in ranks:
                stats.append({"label":"EPA Allowed","value":f"{r['epa_allowed']:.1f}","league_rank":ranks["epa_allowed"][r["team"]]})
            def_cards.append({"name":r["team"],"team":r["team"],"position":"DST","rank":i,"source":source,"analysis":analysis,
                              "summary":" • ".join(pieces[:4]),"stats":stats})
    return off_cards,def_cards

@lru_cache(maxsize=2)
def team_power():
    rows=load_team_weekly_stats(PRIOR_SEASON)
    if rows:
        off,defs=aggregate_nflverse_team_rows(rows)
        if len(off)>=30 and len(defs)>=30:
            return team_analysis_cards(off,defs,"nflverse weekly team stats")
    # Secondary network path for environments that block GitHub release assets.
    espn=espn_team_fallback()
    # ESPN fallback is used only if it exposes enough paired offense/defense fields to rank honestly.
    off=[]; defs=[]
    for r in espn:
        if None not in (r.get("points"),r.get("yards"),r.get("turnovers")):
            off.append({"team":r["team"],"games":17,"points":r["points"],"yards":r["yards"],"turnovers":r["turnovers"],"tds":0,"epa":0})
        if None not in (r.get("points_allowed"),r.get("yards_allowed"),r.get("sacks"),r.get("takeaways")):
            defs.append({"team":r["team"],"games":17,"points_allowed":r["points_allowed"],"yards_allowed":r["yards_allowed"],"sacks":r["sacks"],"takeaways":r["takeaways"],"epa_allowed":0})
    if len(off)>=20 and len(defs)>=20:
        cards=team_analysis_cards(off,defs,"ESPN team-stat fallback")
        return cards
    # Last-resort cards are explicit, never blank.
    fb=fallback()
    offcards=[]
    for i,p in enumerate(fb.get("offenses",[])[:10],1):
        q=dict(p); q["rank"]=i; q["source"]="bundled fallback"; q["analysis"]="Live team-stat sources were unavailable. This is a bundled ordering only and should not be treated as the full statistical model."; q.setdefault("stats",[])
        offcards.append(q)
    defcards=[]
    for i,p in enumerate(fb.get("defenses",[])[:10],1):
        q=dict(p); q["rank"]=i; q["source"]="bundled fallback"; q["analysis"]="Live team-stat sources were unavailable. This is a bundled ordering only and should not be treated as the full statistical model."; q.setdefault("stats",[])
        defcards.append(q)
    return offcards,defcards


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "app": "Fantasy Command Center",
        "version": "6.2-cloud",
        "season": SEASON,
        "time": int(time.time())
    })


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "internal_server_error",
        "message": "Fantasy Command Center hit an unexpected server error. Check /api/diagnostics for source status."
    }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "not_found",
        "message": "That route does not exist."
    }), 404

@app.route("/")
def index():
    return render_template("index.html",live=bool(FANTASYPROS_KEY),season=SEASON)

@app.get("/api/dashboard")
def dashboard():
    SOURCE_STATE.clear()
    scoring=request.args.get("scoring","PPR").upper()
    if scoring not in SCORING: scoring="PPR"
    data=fallback()
    ranks=rankings(scoring)
    # Keep first paint fast. Heavy analytics, injury files, and team data are lazy.
    sleepers=enrich_sleepers(sleeper_candidates(ranks),{})
    data.update({
        "rankings":ranks,
        "analytics":{},
        "sleepers":sleepers,
        "injury_risk":[],
        "offenses":[],
        "defenses":[],
        "meta":{
            "season":SEASON,"prior_season":PRIOR_SEASON,"scoring":scoring,
            "fantasypros_live":bool(FANTASYPROS_KEY),
            "analytics_live":True,
            "projection_model":"5-season recency-weighted PPG + capped trend adjustment",
            "injury_history_through":2024,
            "progressive_loading":True,
            "source_status":dict(SOURCE_STATE),
            "counts":{p:len(ranks.get(p,[])) for p in ALL_POSITIONS},
            "updated":int(time.time())
        }
    })
    return jsonify(data)

@app.get("/api/player-analysis")
def player_analysis_api():
    name=request.args.get("name","").strip()
    pos=request.args.get("position","").strip().upper()
    scoring=request.args.get("scoring","PPR").upper()
    if not name or pos not in ("QB","RB","WR","TE","K"):
        return jsonify({"error":"name and valid position required"}),400
    if scoring not in SCORING: scoring="PPR"
    result=player_analysis_one(name,pos,scoring)
    if result is None:
        return jsonify({"error":"Historical production data unavailable for this player"}),404
    return jsonify(result)

@app.get("/api/injury-risk")
def injury_risk_api():
    scoring=request.args.get("scoring","PPR").upper()
    if scoring not in SCORING: scoring="PPR"
    ranks=rankings(scoring)
    return jsonify({
        "items":injury_risk(ranks),
        "injury_history_through":2024,
        "sources":dict(SOURCE_STATE)
    })

@app.get("/api/team-power")
def team_power_api():
    offenses,defenses=team_power()
    return jsonify({
        "offenses":offenses,
        "defenses":defenses,
        "sources":dict(SOURCE_STATE)
    })

@app.get("/api/diagnostics")
def diagnostics():
    scoring=request.args.get("scoring","PPR").upper()
    if scoring not in SCORING: scoring="PPR"
    ranks=rankings(scoring)
    return jsonify({
        "status":"ok",
        "counts":{p:len(ranks.get(p,[])) for p in ALL_POSITIONS},
        "sources":dict(SOURCE_STATE),
        "progressive_loading":True,
        "note":"Player analytics, injury history, and team power load on demand."
    })

@app.get("/api/sleeper/leagues")
def leagues():
    username=request.args.get("username","").strip(); season=request.args.get("season",str(SEASON))
    if not username:return jsonify({"error":"username required"}),400
    user=http_json(f"https://api.sleeper.app/v1/user/{requests.utils.quote(username)}")
    uid=user.get("user_id")
    if not uid:return jsonify({"error":"Sleeper user not found"}),404
    ls=http_json(f"https://api.sleeper.app/v1/user/{uid}/leagues/nfl/{season}")
    return jsonify({"user":user,"leagues":ls})

@app.get("/api/sleeper/roster/<league_id>")
def roster(league_id):
    username=request.args.get("username","").strip()
    user=http_json(f"https://api.sleeper.app/v1/user/{requests.utils.quote(username)}"); uid=user.get("user_id")
    rosters=http_json(f"https://api.sleeper.app/v1/league/{league_id}/rosters")
    target=next((r for r in rosters if r.get("owner_id")==uid),None)
    if not target:return jsonify({"error":"No roster found for this user in league"}),404
    players=sleeper_players()
    def mp(pid):
        p=players.get(str(pid),{})
        return {"id":pid,"name":p.get("full_name") or p.get("team") or str(pid),
                "position":p.get("position") or ("DST" if len(str(pid))<=3 else ""),
                "team":p.get("team") or (str(pid) if len(str(pid))<=3 else "")}
    return jsonify({"roster_id":target.get("roster_id"),
                    "starters":[mp(x) for x in target.get("starters",[])],
                    "players":[mp(x) for x in target.get("players",[])],
                    "settings":target.get("settings",{})})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","5050")),debug=False)
