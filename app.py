
from flask import Flask, render_template, jsonify, request
import os, json, time, csv, io, math, statistics, re, html as html_lib
from pathlib import Path
from difflib import SequenceMatcher
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET
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

def stale_cached_json(name, ttl, stale_ttl, loader, force=False):
    """
    Return (data, metadata). Fresh cache is preferred. If refresh fails, a
    previously successful cache can still be served until stale_ttl.
    """
    p = CACHE_DIR / f"{name}.json"
    now = time.time()
    existing = None
    age = None
    if p.exists():
        try:
            age = max(0, now - p.stat().st_mtime)
            existing = json.loads(p.read_text(encoding="utf-8"))
            if not force and age < ttl:
                return existing, {"cached": True, "stale": False, "age_seconds": int(age)}
        except Exception:
            existing = None
            age = None
    try:
        data = loader()
        p.write_text(json.dumps(data), encoding="utf-8")
        return data, {"cached": False, "stale": False, "age_seconds": 0}
    except Exception as e:
        if existing is not None and age is not None and age < stale_ttl:
            return existing, {
                "cached": True, "stale": True, "age_seconds": int(age),
                "refresh_error": str(e)[:180]
            }
        raise

def espn_cache_ttl(season):
    # In-season ESPN information should turn over quickly; completed seasons do not.
    return 21600 if int(season) >= SEASON else 2592000  # 6h vs 30d

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

def nflverse_player_week_urls(year):
    return [f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{year}.csv"]

@lru_cache(maxsize=8)
def load_player_weekly_stats(year):
    try:
        rows,src=cached_csv(
            f"stats_player_week_{year}",86400*14,
            nflverse_player_week_urls(year),
            ["player_display_name","position","week"]
        )
        source_ok(f"player_week_{year}",f"nflverse weekly {src}")
        return rows
    except Exception as e:
        source_fail(f"player_week_{year}",e)
        return []

@lru_cache(maxsize=8)
def weekly_participation_index(year):
    idx={}
    for r in load_player_weekly_stats(year):
        name=norm_name(r.get("player_display_name") or r.get("player_name") or "")
        if not name:continue
        try:w=int(float(r.get("week") or 0))
        except:w=0
        if w:
            idx.setdefault(name,set()).add(w)
    return idx

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

@lru_cache(maxsize=1)
def sleeper_players():
    try:
        data,meta = stale_cached_json(
            "sleeper_players", 86400, 86400*7,
            lambda: http_json("https://api.sleeper.app/v1/players/nfl?active=true",timeout=20)
        )
        source_ok("sleeper_players", f"{len(data):,} active-player records" + (" • stale-safe cache" if meta.get("stale") else ""))
        return data
    except Exception as e:
        source_fail("sleeper_players", e)
        return {}

def sleeper_trending():
    try:
        data,meta = stale_cached_json(
            "sleeper_trending", 900, 86400,
            lambda: http_json("https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=24&limit=250",timeout=15)
        )
        source_ok("sleeper_trending", f"{len(data)} trending add records" + (" • stale-safe cache" if meta.get("stale") else ""))
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

@lru_cache(maxsize=3)
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



INJURY_INFO={
    "acl":("ACL injury","Involves the anterior cruciate ligament that stabilizes the knee. Complete tears commonly require reconstruction and a long rehabilitation; the feed does not identify tear grade unless reporting says so."),
    "mcl":("MCL injury","Involves the medial collateral ligament on the inside of the knee. Return varies substantially with sprain grade and associated damage."),
    "achilles":("Achilles injury","Involves the tendon connecting the calf to the heel. A rupture is a major injury; a generic Achilles label does not prove rupture."),
    "high ankle":("High-ankle sprain","A syndesmotic ankle injury above the traditional ankle joint. These often recover more slowly than routine lateral ankle sprains."),
    "ankle":("Ankle injury","An ankle injury can range from a mild sprain to a higher-grade ligament or bone injury. The historical report label alone does not establish severity."),
    "hamstring":("Hamstring injury","Involves the posterior-thigh muscle/tendon complex. Recurrence risk and return timing depend heavily on strain location and grade."),
    "groin":("Groin injury","Usually involves the adductor/hip-groin complex. Cutting and acceleration can remain limited until strength and pain normalize."),
    "calf":("Calf injury","Involves the calf muscle/tendon complex. Explosive acceleration can be affected and recurrence is possible if return is rushed."),
    "quad":("Quadriceps injury","Involves the anterior-thigh muscle group. Severity ranges from soreness/contusion to a muscle strain."),
    "concussion":("Concussion","A brain injury managed through the NFL concussion protocol. Return is based on symptom resolution and completion of protocol stages, not a fixed timetable."),
    "shoulder":("Shoulder injury","A broad shoulder designation can involve joint, labrum, AC joint or surrounding soft tissue. The generic report label does not establish the exact structure."),
    "knee":("Knee injury","A broad knee designation. It can involve ligament, meniscus, tendon, bone or inflammation; the weekly injury report does not provide enough detail to infer severity."),
    "foot":("Foot injury","A broad foot designation that can involve bone, ligament or soft tissue. Weight-bearing tolerance and the exact diagnosis drive return."),
    "toe":("Toe injury","Toe injuries can materially affect push-off and change of direction. The generic report does not identify whether this is a sprain, fracture or turf-toe pattern."),
    "wrist":("Wrist injury","A wrist injury can affect ball security, catching and blocking. Exact return depends on structure and severity."),
    "hand":("Hand injury","A hand injury can affect grip, catching and ball security. The historical label does not identify fracture versus soft-tissue injury."),
    "rib":("Rib/chest injury","Rib and chest-wall injuries can be painful with contact and breathing. Return often depends on pain control and protection."),
    "back":("Back injury","A broad back designation. Muscle, disc, nerve and joint causes have very different recovery paths, so a generic label should not be treated as a specific diagnosis."),
    "hip":("Hip injury","A broad hip designation that can involve flexor/adductor muscle, joint or surrounding structures. Exact recovery depends on diagnosis and severity.")
}

def injury_description(label):
    text=(label or "").lower()
    for key,(diagnosis,desc) in INJURY_INFO.items():
        if key in text:
            return diagnosis,desc
    clean=(label or "Unspecified injury").strip()
    return clean, f"The historical report identifies this as {clean.lower()}, but does not provide enough detail to determine structure, grade or severity."

def extract_specific_injury(text,fallback=""):
    blob=(text or "").lower()
    ordered=[
        ("high ankle sprain","High-ankle sprain"),("torn acl","ACL tear"),("acl tear","ACL tear"),
        ("torn mcl","MCL tear"),("mcl sprain","MCL sprain"),("achilles rupture","Achilles rupture"),
        ("torn achilles","Achilles rupture"),("concussion","Concussion"),("hamstring strain","Hamstring strain"),
        ("hamstring","Hamstring injury"),("groin strain","Groin strain"),("groin","Groin injury"),
        ("ankle sprain","Ankle sprain"),("ankle","Ankle injury"),("knee","Knee injury"),
        ("calf","Calf injury"),("quadriceps","Quadriceps injury"),("quad","Quadriceps injury"),
        ("shoulder","Shoulder injury"),("foot","Foot injury"),("toe","Toe injury"),
        ("wrist","Wrist injury"),("hand","Hand injury"),("rib","Rib/chest injury"),
        ("back","Back injury"),("hip","Hip injury")
    ]
    for key,label in ordered:
        if key in blob:return label
    return fallback or "No specific diagnosis identified"

def extract_timeline_signal(text):
    blob=re.sub(r"\s+"," ",text or "").strip()
    low=blob.lower()
    patterns=[
        (r"(?:out|miss(?:ing)?|sidelined for)\s+(?:approximately\s+|about\s+)?(\d+)\s*[-–to]+\s*(\d+)\s+weeks",lambda m:f"Reported timetable: {m.group(1)}–{m.group(2)} weeks."),
        (r"(?:out|miss(?:ing)?|sidelined for)\s+(?:approximately\s+|about\s+)?(\d+)\s+weeks",lambda m:f"Reported timetable: about {m.group(1)} weeks."),
        (r"week[- ]to[- ]week",lambda m:"Latest reporting describes the player as week-to-week."),
        (r"day[- ]to[- ]day",lambda m:"Latest reporting describes the player as day-to-day."),
        (r"season[- ]ending|out for the season",lambda m:"Latest reporting indicates a season-ending absence."),
        (r"placed on (?:injured reserve|ir)",lambda m:"Latest reporting says the player was placed on injured reserve; monitor eligibility and team updates for the return window."),
        (r"(?:expected|targeting|on track) to return[^.]{0,80}",lambda m:"Latest reporting includes a stated return target; open the linked report for the exact wording.")
    ]
    for pat,fn in patterns:
        m=re.search(pat,low,re.I)
        if m:return fn(m)
    return ""

def fantasypros_player_news(name,category=None,limit=6):
    if not FANTASYPROS_KEY:return []
    try:
        players=cached_json("fp_players_current",86400,lambda:fp("/nfl/players"))
        arr=players.get("players") or []
        target=next((p for p in arr if norm_name(p.get("player_name") or p.get("name"))==norm_name(name)),None)
        if not target:return []
        pid=target.get("player_id") or target.get("id")
        params={"fpid":pid,"limit":limit}
        if category:params["category"]=category
        payload=fp("/nfl/news",params)
        out=[]
        for x in payload.get("items") or []:
            out.append({
                "title":strip_markup(x.get("title") or ""),
                "summary":strip_markup(x.get("desc") or x.get("description") or "")[:300],
                "url":x.get("link") or "",
                "source":"FantasyPros",
                "published_ts":parse_pubdate(x.get("created_formated") or "") or 0
            })
        return [x for x in out if x["title"]]
    except Exception as e:
        source_fail("fantasypros_player_news",e)
        return []

def player_news_context(name,purpose="fantasy",limit=5):
    cache_key=f"player_context_{purpose}_{norm_name(name)}"
    def loader():
        fp_items=fantasypros_player_news(name,"injury" if purpose=="injury" else None,limit)
        query=f'"{name}" NFL injury fantasy' if purpose=="injury" else f'"{name}" NFL fantasy football'
        web_items=[]
        try:web_items=google_news_rss(query,"News",limit)
        except Exception:web_items=[]
        items=fp_items+web_items
        dedup={}
        for a in items:
            k=re.sub(r"[^a-z0-9]+"," ",a.get("title","").lower()).strip()
            if k and k not in dedup:dedup[k]=a
        return sorted(dedup.values(),key=lambda x:x.get("published_ts") or 0,reverse=True)[:limit]
    try:
        data,_=stale_cached_json(cache_key,1800,43200,loader)
        return data
    except Exception:
        return []

def recent_news_summary(items):
    if not items:return None
    a=items[0]
    return {
        "title":a.get("title") or "",
        "summary":a.get("summary") or "",
        "source":a.get("source") or "News",
        "url":a.get("url") or "",
        "published_ts":a.get("published_ts") or 0
    }

def news_signal(items):
    blob=" ".join((a.get("title","")+" "+a.get("summary","")) for a in (items or [])[:4]).lower()
    negative=[
        "released", "waived", "injury settlement", "out for the season", "season-ending",
        "season ending", "placed on injured reserve", "retired", "suspended indefinitely"
    ]
    positive=[
        "named starter", "will start", "expected to start", "starting role", "first-team",
        "first team", "expanded role", "larger role", "more touches", "more targets",
        "increased workload", "promoted", "takes over", "lead back", "starting running back"
    ]
    return {
        "negative":next((x for x in negative if x in blob),None),
        "positive":next((x for x in positive if x in blob),None),
        "blob":blob
    }

def peer_role_context(player,players):
    team=player.get("team");pos=(player.get("position") or "").upper()
    try:order=int(float(player.get("depth_chart_order") or 99))
    except:order=99
    peers=[]
    for q in players.values():
        if q is player or q.get("team")!=team or (q.get("position") or "").upper()!=pos:continue
        try:qo=int(float(q.get("depth_chart_order") or 99))
        except:qo=99
        peers.append((qo,q))
    def peer_search_rank(item):
        try:return float(item[1].get("search_rank") or 999999)
        except:return 999999
    peers.sort(key=lambda x:(x[0],peer_search_rank(x)))
    ahead=[q for qo,q in peers if qo<order]
    injured_ahead=[
        q for q in ahead
        if (q.get("injury_status") or str(q.get("status") or "").lower() not in ("active",""))
    ]
    return order,ahead,injured_ahead

@lru_cache(maxsize=16)
def team_game_weeks(year,team):
    out=set()
    for r in load_team_weekly_stats(year):
        if (r.get("team") or "").upper()!=(team or "").upper():continue
        try:w=int(float(r.get("week") or 0))
        except:w=0
        if w:out.add(w)
    return out

def historical_participation(name,season,first_week,last_week,team=""):
    weeks=weekly_participation_index(season).get(norm_name(name),set())
    if not weeks:
        return {
            "games_missed_estimate":None,"return_week":None,
            "participation_note":"Weekly participation could not be matched for this player/season."
        }
    # Count only weeks in which the player's team actually played, so a bye
    # inside an injury-report window is not mislabeled as a missed game.
    scheduled=team_game_weeks(season,team) if team else set()
    candidate_window=list(range(max(1,first_week),min(18,last_week)+1))
    window=[w for w in candidate_window if not scheduled or w in scheduled]
    missed=sum(1 for w in window if w not in weeks)
    after=sorted(w for w in weeks if w>last_week and (not scheduled or w in scheduled))
    return_week=after[0] if after else None
    return {
        "games_missed_estimate":missed,
        "return_week":return_week,
        "participation_note":(
            f"Recorded weekly player-stat participation again in Week {return_week}."
            if return_week else
            "No later weekly player-stat row was found in that season, so a return week could not be verified."
        )
    }

@lru_cache(maxsize=1)
def injury_history_index():
    index={}
    years=list(range(max(2009,SEASON-6),min(SEASON,2025)))
    with ThreadPoolExecutor(max_workers=min(5,len(years))) as ex:
        futures={ex.submit(load_injury_year,y):y for y in years}
        for fut in as_completed(futures):
            try:season_rows=fut.result()
            except Exception:season_rows=[]
            for r in season_rows:
                name=norm_name(r.get("full_name"))
                if not name:continue
                injury=(r.get("report_primary_injury") or r.get("practice_primary_injury") or "").strip()
                if not injury:continue
                try:week=int(float(r.get("week") or 0))
                except:week=0
                try:season=int(float(r.get("season") or futures[fut]))
                except:season=futures[fut]
                index.setdefault(name,[]).append({
                    "season":season,"week":week,"injury":injury,
                    "team":(r.get("team") or "").strip(),
                    "report_status":(r.get("report_status") or "").strip(),
                    "practice_status":(r.get("practice_status") or "").strip()
                })
    for rows in index.values():
        rows.sort(key=lambda x:(x["season"],x["week"]))
    return index

@lru_cache(maxsize=256)
def injury_episodes_basic_cached(name):
    """
    Lightweight historical reconstruction from injury-report rows only.
    No weekly player-stat files and no player-specific news are loaded here.
    """
    rows=list(injury_history_index().get(norm_name(name),[]))
    eps=[]
    for r in rows:
        same=(
            eps and eps[-1]["season"]==r["season"]
            and eps[-1]["injury"].lower()==r["injury"].lower()
            and r["week"]<=eps[-1]["last_week"]+1
        )
        if same:
            ep=eps[-1]
            ep["last_week"]=max(ep["last_week"],r["week"])
            ep["weeks_reported"]+=1
            if r["report_status"]:ep["report_statuses"].add(r["report_status"])
            if r["practice_status"]:ep["practice_statuses"].add(r["practice_status"])
            if str(r["report_status"]).strip().lower()=="out":
                ep["out_designated_weeks"]+=1
        else:
            eps.append({
                "season":r["season"],"first_week":r["week"],"last_week":r["week"],
                "injury":r["injury"],"team":r.get("team") or "","weeks_reported":1,
                "out_designated_weeks":1 if str(r["report_status"]).strip().lower()=="out" else 0,
                "report_statuses":set([r["report_status"]]) if r["report_status"] else set(),
                "practice_statuses":set([r["practice_status"]]) if r["practice_status"] else set()
            })

    out=[]
    for ep in reversed(eps[-2:]):
        diagnosis,desc=injury_description(ep["injury"])
        out.append({
            "season":ep["season"],
            "team":ep.get("team") or "",
            "injury":ep["injury"],
            "diagnosis":diagnosis,
            "description":desc,
            "first_week":ep["first_week"],
            "last_week":ep["last_week"],
            "weeks_reported":ep["weeks_reported"],
            "report_duration_weeks":max(1,ep["last_week"]-ep["first_week"]+1),
            "out_designated_weeks":ep["out_designated_weeks"],
            "week_range":f"Wk {ep['first_week']}" if ep["first_week"]==ep["last_week"] else f"Wks {ep['first_week']}-{ep['last_week']}",
            "report_statuses":", ".join(sorted(ep["report_statuses"])),
            "practice_statuses":", ".join(sorted(ep["practice_statuses"]))
        })
    return out

def current_injury_outlook(player,news):
    status=str(player.get("injury_status") or "").strip()
    practice=str(player.get("practice_participation") or "").strip()
    start=str(player.get("injury_start_date") or "").strip()
    blob=" ".join((a.get("title","")+" "+a.get("summary","")) for a in news[:3])
    timeline=extract_timeline_signal(blob)
    specific=extract_specific_injury(blob,player.get("injury_body_part") or "")
    diagnosis,description=injury_description(specific)

    if timeline:
        outlook=timeline
    elif status.lower() in ("ir","injured reserve","injury_reserve"):
        outlook="Currently designated for injured reserve. I would not assume an exact return week until the team or a reliable reporter gives a timetable."
    elif status.lower()=="out":
        outlook="Currently listed Out. The near-term availability signal is negative until practice participation or team reporting improves."
    elif status.lower()=="doubtful":
        outlook="Currently Doubtful; I would plan as if he will miss the upcoming game unless the designation materially improves."
    elif status.lower()=="questionable":
        outlook="Currently Questionable. The next meaningful signals are practice participation and the final game-status report."
    elif status:
        outlook=f"Current Sleeper designation is {status}. No trustworthy return timetable was found, so the app does not invent one."
    else:
        outlook="No current Sleeper injury designation is present; historical injuries are background risk rather than evidence he is currently unavailable."

    if practice:
        outlook+=f" Latest practice participation: {practice}."
    if start:
        outlook+=f" Sleeper injury start date: {start}."

    low=status.lower()
    if low in ("ir","injured reserve","injury_reserve","out"):
        fantasy_impact="My fantasy read: downgrade him until there is a verified return window. Replacement-level production and roster flexibility matter more than name value while he is unavailable."
    elif low in ("doubtful","questionable"):
        fantasy_impact="My fantasy read: keep a contingency plan ready. If practice participation improves, the risk can fall quickly; if he remains limited or absent, I would lower weekly expectations."
    elif status:
        fantasy_impact="My fantasy read: treat the designation as a real risk flag, but let practice trend and role reports determine how aggressively to downgrade him."
    else:
        fantasy_impact="My fantasy read: there is no current designation, so I would not penalize him heavily for old injuries alone; use the history mainly to understand recurrence and availability risk."

    return diagnosis,description,outlook,fantasy_impact

def draftable_names(rankings_data):
    return {norm_name(p["name"]) for pos in DRAFT_POSITIONS for p in rankings_data.get(pos,[])[:TOP_N]}

def injury_risk_summary(rankings_data):
    """
    Fast Injury-board response:
    Sleeper current status + small nflverse injury-report files only.
    No weekly participation files and no news fan-out.
    """
    players=sleeper_players()
    draftable=draftable_names(rankings_data)
    candidates=[]

    for p in players.values():
        pos=(p.get("position") or "").upper()
        if pos not in DRAFT_POSITIONS or not p.get("team") or not p.get("active",True):
            continue
        name=player_name(p)
        if norm_name(name) not in draftable:
            continue

        episodes=injury_episodes_basic_cached(name)
        status=str(p.get("injury_status") or "").strip()
        age=num(p,"age",0)
        score=0
        reasons=[]

        if status:
            score+=45
            reasons.append(f"current: {status}")

        if episodes:
            duration=sum(x["report_duration_weeks"] for x in episodes)
            out_weeks=sum(x["out_designated_weeks"] for x in episodes)
            score+=min(35,duration*3+out_weeks*5)
            reasons.append(f"{len(episodes)} recent historical episode(s)")

        if age>=30:
            score+=min(15,(age-29)*3)
            reasons.append(f"age {int(age)}")

        # Current label without a news request.
        diagnosis,description,outlook,fantasy_impact=current_injury_outlook(p,[])

        candidates.append({
            "name":name,
            "team":p.get("team"),
            "position":p.get("position"),
            "risk":round(min(score,100)),
            "reason":", ".join(reasons),
            "current_status":p.get("injury_status") or "",
            "practice_participation":p.get("practice_participation") or "",
            "injury_start_date":p.get("injury_start_date"),
            "current_diagnosis":diagnosis,
            "current_description":description,
            "return_outlook":outlook,
            "fantasy_impact":fantasy_impact,
            "recent_injuries":episodes,
            "detail_loaded":False
        })

    candidates.sort(key=lambda x:x["risk"],reverse=True)
    return candidates[:TOP_N]

def _injury_detail_uncached(name):
    players=sleeper_players()
    player=next(
        (p for p in players.values() if norm_name(player_name(p))==norm_name(name)),
        None
    )
    if not player:
        raise ValueError("Player not found in current Sleeper player universe.")

    basic=injury_episodes_basic_cached(name)

    # Only load weekly stats for the seasons this player actually needs.
    detailed=[]
    for ep in basic:
        part=historical_participation(
            name,
            ep["season"],
            ep["first_week"],
            ep["last_week"],
            ep.get("team") or ""
        )
        x=dict(ep)
        x.update({
            "games_missed_estimate":part["games_missed_estimate"],
            "return_week":part["return_week"],
            "return_evidence":part["participation_note"]
        })
        detailed.append(x)

    # One player's current reporting, not 25 simultaneous searches.
    news=player_news_context(name,"injury",5)
    diagnosis,description,outlook,fantasy_impact=current_injury_outlook(player,news)
    latest=recent_news_summary(news)

    verified=[
        x["games_missed_estimate"]
        for x in detailed
        if x.get("games_missed_estimate") is not None
    ]
    total_missed=sum(verified) if verified else None

    analysis=[]
    if detailed and total_missed is not None:
        analysis.append(
            f"Across the two most recent matched injury-report episodes, the weekly-stat participation reconstruction estimates {total_missed} missed game(s) during the relevant report windows."
        )
    elif detailed:
        analysis.append(
            "Historical injury-report episodes were found, but weekly participation could not be matched reliably enough to estimate games missed."
        )
    else:
        analysis.append(
            "No matching historical nflverse injury-report episode was found in the available window."
        )

    if player.get("injury_status"):
        analysis.append(f"Current Sleeper designation: {player.get('injury_status')}.")

    if latest:
        analysis.append(f"Latest matched injury report: {latest['title']} ({latest['source']}).")

    return {
        "name":name,
        "team":player.get("team"),
        "position":player.get("position"),
        "current_status":player.get("injury_status") or "",
        "practice_participation":player.get("practice_participation") or "",
        "injury_start_date":player.get("injury_start_date"),
        "current_diagnosis":diagnosis,
        "current_description":description,
        "return_outlook":outlook,
        "fantasy_impact":fantasy_impact,
        "latest_news":latest,
        "recent_injuries":detailed,
        "analysis":" ".join(analysis),
        "missed_games_method":"Estimated from absence/presence in nflverse weekly player-stat rows during the injury-report window, with team bye weeks excluded. This is a participation proxy, not an official inactive-list count."
    }

def injury_detail(name):
    cache_key=f"injury_detail_{norm_name(name)}"
    data,meta=stale_cached_json(
        cache_key,
        1800,       # refresh after 30 minutes
        86400,      # serve a last-good detail for 24h if an upstream source fails
        lambda:_injury_detail_uncached(name)
    )
    data=dict(data)
    data["cache"]=meta
    return data


def sleeper_candidates(rankings_data,limit=60):
    players=sleeper_players();trend=sleeper_trending()
    drafted=draftable_names(rankings_data)
    result=[];seen=set()
    for t in trend:
        p=players.get(str(t.get("player_id")),{})
        pos=(p.get("position") or "").upper();name=player_name(p)
        if pos not in DRAFT_POSITIONS or not p.get("team") or not name:continue
        n=norm_name(name)
        if n in drafted or n in seen:continue
        seen.add(n)
        result.append({
            "player_id":str(t.get("player_id")),"name":name,"team":p.get("team"),"position":pos,
            "adds":int(t.get("count") or 0),"search_rank":p.get("search_rank"),
            "depth_chart_order":p.get("depth_chart_order"),
            "depth_chart_position":p.get("depth_chart_position"),
            "injury_status":p.get("injury_status"),"reason":"Trending on Sleeper"
        })
        if len(result)>=limit:break
    if len(result)<limit:
        vals=[]
        for pid,p in players.items():
            pos=(p.get("position") or "").upper();name=player_name(p);n=norm_name(name)
            if pos not in DRAFT_POSITIONS or not p.get("team") or not name or n in drafted or n in seen:continue
            try:sr=float(p.get("search_rank"))
            except:sr=999999
            vals.append((sr,name,pid,p))
        vals.sort(key=lambda x:x[0])
        for sr,name,pid,p in vals:
            seen.add(norm_name(name))
            result.append({
                "player_id":str(pid),"name":name,"team":p.get("team"),"position":p.get("position"),
                "adds":0,"search_rank":sr,"depth_chart_order":p.get("depth_chart_order"),
                "depth_chart_position":p.get("depth_chart_position"),
                "injury_status":p.get("injury_status"),"reason":"Current rostered upside candidate"
            })
            if len(result)>=limit:break
    return result[:limit]

def sleeper_breakout(player,analytics=None,news=None,players=None):
    players=players or sleeper_players()
    news=news or []
    p=players.get(str(player.get("player_id")),{})
    if not p:
        p=next((x for x in players.values() if norm_name(player_name(x))==norm_name(player.get("name"))),{})
    name=player.get("name") or player_name(p)
    team=player.get("team") or p.get("team") or ""
    pos=(player.get("position") or p.get("position") or "").upper()
    adds=int(player.get("adds") or 0)
    order,ahead,injured_ahead=peer_role_context(p,players) if p else (99,[],[])
    latest=recent_news_summary(news)
    sig=news_signal(news)
    own_status=str(p.get("injury_status") or "").strip()
    roster_status=str(p.get("status") or "").strip()
    news_blob=sig.get("blob") or ""
    return_signal=any(x in news_blob for x in ("activated", "cleared to return", "expected to return", "returns to practice", "designated to return"))
    own_severe=own_status.lower() in ("ir","injured reserve","injury_reserve","out")

    score=44.0
    evidence=[]
    if order==1:
        score+=18;evidence.append("Listed first on depth chart")
    elif order==2:
        score+=9;evidence.append("No. 2 on depth chart")
    elif order<99:
        score+=max(0,6-(order-2)*2);evidence.append(f"Depth chart No. {order}")
    if injured_ahead:
        score+=22;evidence.append("Injury-created opportunity")
    if adds>=1000:score+=11
    elif adds>=500:score+=8
    elif adds>=100:score+=5
    elif adds>0:score+=2
    if adds:evidence.append(f"{adds:,} recent Sleeper adds")
    if sig["positive"]:
        score+=12;evidence.append("Positive role report")
    if own_status.lower() in ("ir","injured reserve","injury_reserve","out"):
        score-=30;evidence.append(f"Own status: {own_status}")
    elif own_status:
        score-=8;evidence.append(f"Own status: {own_status}")
    if sig["negative"]:
        score-=45;evidence.append(f"Negative news: {sig['negative']}")
    if roster_status and roster_status.lower() not in ("active",""):
        score-=20;evidence.append(f"Roster status: {roster_status}")
    score=max(0,min(100,round(score,1)))

    self_disqualify=("own severe injury without a verified return signal" if own_severe and not return_signal else None)
    if sig["negative"] or self_disqualify or score<35:
        verdict="FADE"
    elif score>=82:
        verdict="STRONG TARGET"
    elif score>=70:
        verdict="TARGET"
    elif score>=58:
        verdict="STASH"
    else:
        verdict="WATCH"

    # Sports-analyst style thesis: lead with the actual football reason, then
    # market confirmation, then explicitly state what could invalidate it.
    if injured_ahead:
        lead=injured_ahead[0]
        lead_name=player_name(lead)
        lead_status=lead.get("injury_status") or lead.get("status") or "unavailable"
        thesis=(
            f"I like {name} because there is a concrete path to more {('touches' if pos=='RB' else 'routes/targets' if pos in ('WR','TE') else 'snaps')}: "
            f"{lead_name}, who is ahead of him for {team}, is currently flagged {lead_status}. "
        )
        if order==2:
            thesis+=f"{name} is already listed No. 2 on the depth chart, so he is the most direct beneficiary if that absence carries into games. "
        else:
            thesis+=f"He is listed No. {order if order<99 else '?'} on the depth chart, so the injury helps but does not guarantee he inherits the full job. "
    elif order==1:
        thesis=(
            f"My interest in {name} is role-driven: Sleeper currently lists him first at {p.get('depth_chart_position') or pos} for {team}. "
            "That is more important to me than the trending count because starting position creates the clearest path to repeatable fantasy volume. "
        )
    elif order<99:
        lead=player_name(ahead[0]) if ahead else "the current starter"
        thesis=(
            f"I view {name} as a speculative upside play, not a confirmed starter. He sits No. {order} on the {team} depth chart behind {lead}. "
            "The bet is that his role expands through performance, packages or an injury ahead of him. "
        )
    else:
        thesis=(
            f"I do not have a verified starting-role signal for {name} yet. The case is based on market movement and recent reporting, so I would treat him as a watch-list player until usage confirms the thesis. "
        )

    if sig["positive"]:
        thesis+=f"Recent reporting contains a positive role signal ({sig['positive']}), which strengthens the case. "
    if latest:
        thesis+=f"The latest matched report is “{latest['title']}” ({latest['source']}). "
    if adds>=500:
        thesis+=f"The {adds:,} recent Sleeper adds tell me other managers are reacting too, but I use that as confirmation—not the reason to buy. "
    elif adds>0:
        thesis+=f"Sleeper has logged {adds:,} recent adds, which is modest market confirmation. "
    if own_status:
        thesis+=f"The main caution is his own {own_status} designation. "
    if sig["negative"]:
        thesis+=f"More importantly, current reporting contains a negative roster/availability signal ({sig['negative']}), so I would not chase the trend. "

    if pos=="RB":
        upside="For this RB thesis to pay off, I want to see him earn meaningful early-down touches plus either passing-down or goal-line work; pure backup snaps are not enough."
    elif pos=="WR":
        upside="For this WR thesis to pay off, I want route participation in two- and three-WR sets and a real target share; camp buzz without routes is not enough."
    elif pos=="TE":
        upside="For this TE thesis to pay off, I want a strong route rate and red-zone involvement; blocking-only snaps do not create reliable fantasy value."
    else:
        upside="For this QB thesis to pay off, he needs a confirmed starting job and either rushing production or enough passing volume to create weekly ceiling."

    if injured_ahead:
        risk=f"The biggest risk is that {player_name(injured_ahead[0])} returns quickly or the team uses a committee instead of giving {name} the vacated work."
    elif order>1 and order<99:
        risk=f"The biggest risk is simple: {name} is still behind {player_name(ahead[0]) if ahead else 'another player'} and may never earn enough weekly volume."
    elif sig["negative"]:
        risk="The current news signal undermines the roster opportunity entirely; the trend may be stale or reactionary rather than actionable."
    else:
        risk="The biggest risk is that the projected role never shows up in actual snaps, routes, targets or touches."

    if verdict in ("STRONG TARGET","TARGET"):
        acquisition="My move: actively target him at a reasonable late-round/bench price before the role is fully reflected in ADP or waivers."
    elif verdict=="STASH":
        acquisition="My move: stash him if your bench has a low-ceiling player, but do not cut a proven weekly contributor for him yet."
    elif verdict=="WATCH":
        acquisition="My move: watch the next depth-chart, practice and game-usage update before spending meaningful draft capital or FAAB."
    else:
        acquisition="My move: fade the current trend until a new roster/health development changes the evidence."

    role_read=(
        f"{name} is listed No. {order} at {p.get('depth_chart_position') or pos} for {team}."
        if order<99 else
        f"No reliable current Sleeper depth-chart order is available for {name}."
    )

    return {
        "why":thesis.strip(),"role_read":role_read,"upside":upside,
        "risk_to_thesis":risk,"acquisition":acquisition,"evidence":evidence,
        "catalyst_type":"Injury opportunity" if injured_ahead else "Starting role" if order==1 else "Role/news",
        "latest_news":latest,"analyst_score":score,"verdict":verdict,
        "confidence":"High" if score>=82 and (injured_ahead or sig["positive"]) else "Medium" if score>=58 else "Low",
        "players_ahead":[{"name":player_name(q),"status":q.get("injury_status") or q.get("status") or ""} for q in ahead[:3]],
        "injured_ahead":[{"name":player_name(q),"status":q.get("injury_status") or q.get("status") or ""} for q in injured_ahead[:3]],
        "disqualifying_signal":sig["negative"] or self_disqualify
    }

def enrich_sleepers(items,analytics,with_news=False):
    players=sleeper_players()
    # Always dedupe again at the final presentation grain. This protects the UI
    # from provider ID aliases and stale duplicate records.
    dedup=[];seen=set()
    for p in items:
        n=norm_name(p.get("name"))
        if not n or n in seen:continue
        seen.add(n);dedup.append(p)

    news_by_name={}
    targets=dedup[:50] if with_news else []
    if targets:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures={ex.submit(player_news_context,p["name"],"fantasy",5):p["name"] for p in targets}
            for fut in as_completed(futures):
                try:news_by_name[futures[fut]]=fut.result()
                except Exception:news_by_name[futures[fut]]=[]

    out=[]
    for p in dedup:
        q=dict(p)
        q.update(sleeper_breakout(q,analytics.get(norm_name(q["name"])),news_by_name.get(q["name"],[]),players))
        # A player who is released/waived/season-ending or whose model verdict is
        # FADE should not occupy a "best sleeper" slot merely because an old
        # trending record is still present.
        if q.get("disqualifying_signal") or q.get("verdict")=="FADE":
            continue
        out.append(q)
    out.sort(key=lambda x:(x.get("analyst_score",0),x.get("adds",0)),reverse=True)
    return out[:TOP_N]

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

def espn_flat_stats(team_id, season):
    url=f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{season}/types/2/teams/{team_id}/statistics"
    d=http_json(url)
    flat={}
    for cat in ((d.get("splits") or {}).get("categories") or []):
        for s in cat.get("stats") or []:
            name=s.get("name")
            if name:
                flat[name]=s.get("value")
                flat[name.lower()]=s.get("value")
    return flat

def espn_cached_stats(team_id, season):
    ttl=espn_cache_ttl(season)
    # Completed-season caches can survive a long provider outage; current-season
    # caches have a much shorter stale allowance.
    stale_ttl = 15552000 if int(season) < SEASON else 604800  # 180d / 7d
    return stale_cached_json(
        f"espn_team_{season}_{team_id}", ttl, stale_ttl,
        lambda: espn_flat_stats(team_id, season)
    )

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
    stale_count=0
    cache_hits=0
    def one(item):
        abbr,tid=item
        flat,meta=espn_cached_stats(tid,PRIOR_SEASON)
        return {
            "team":abbr,
            "points":pickstat(flat,"totalPoints","pointsFor","points"),
            "yards":pickstat(flat,"netYards","totalYards","yards"),
            "turnovers":pickstat(flat,"totalGiveaways","turnovers","giveaways"),
            "points_allowed":pickstat(flat,"pointsAllowed","totalPointsAllowed"),
            "yards_allowed":pickstat(flat,"netYardsAllowed","totalYardsAllowed","yardsAllowed"),
            "sacks":pickstat(flat,"sacks","defensiveSacks"),
            "takeaways":pickstat(flat,"totalTakeaways","takeaways"),
            "_cache_meta":meta
        }
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures=[ex.submit(one,item) for item in ESPN_TEAMS.items()]
        for fut in as_completed(futures):
            try:
                row=fut.result()
                meta=row.pop("_cache_meta",{})
                if meta.get("cached"): cache_hits+=1
                if meta.get("stale"): stale_count+=1
                rows.append(row)
            except Exception:
                errors+=1
    if rows:
        source_ok(
            "team_stats_espn",
            f"ESPN cache: {len(rows)} teams • {cache_hits} cache hits • {stale_count} stale-served • {errors} errors"
        )
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
        "version": "8.5-analyst-stability",
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


def sleeper_state():
    try:
        return cached_json(
            "sleeper_nfl_state",900,
            lambda:http_json("https://api.sleeper.app/v1/state/nfl")
        )
    except Exception:
        return {"week":1,"season":str(SEASON),"season_type":"pre"}

def league_scoring_mode(league):
    rec=num(league.get("scoring_settings") or {},"rec",0)
    if rec>=0.75:return "PPR"
    if rec>=0.25:return "HALF"
    return "STD"

def grade_letter(score):
    if score>=93:return "A+"
    if score>=88:return "A"
    if score>=84:return "A-"
    if score>=80:return "B+"
    if score>=75:return "B"
    if score>=71:return "B-"
    if score>=67:return "C+"
    if score>=62:return "C"
    if score>=58:return "C-"
    if score>=53:return "D+"
    if score>=48:return "D"
    return "F"

def percentile_rank(value,values):
    vals=[v for v in values if v is not None]
    if not vals:return 50.0
    below=sum(1 for v in vals if v<value)
    equal=sum(1 for v in vals if v==value)
    return round(100*(below+0.5*equal)/len(vals),1)

@lru_cache(maxsize=3)
def league_value_map(scoring):
    players=sleeper_players()
    try:
        prior=load_year_stats(PRIOR_SEASON)
    except Exception:
        prior=[]
    exact,_=_row_index(prior) if prior else ({},{})
    ranks=rankings(scoring)
    rank_by_name={}
    for pos,arr in ranks.items():
        for i,p in enumerate(arr,1):
            rank_by_name[norm_name(p.get("name"))]=(pos,i)

    # Prior-season PPG distributions by position turn raw fantasy scoring into
    # within-position percentiles.
    ppg_by_pos={p:[] for p in ("QB","RB","WR","TE","K")}
    raw_ppg={}
    if prior:
        for r in prior:
            pos=(r.get("position") or r.get("position_group") or "").upper()
            if pos=="PK":pos="K"
            if pos not in ppg_by_pos:continue
            name=r.get("player_display_name") or r.get("player_name") or r.get("name")
            if not name:continue
            g=games(r); ppg=fantasy_points(r,scoring)/g if g else 0
            ppg_by_pos[pos].append(ppg)
            raw_ppg[norm_name(name)]=(pos,ppg)

    out={}
    for pid,p in players.items():
        pos=(p.get("position") or "").upper()
        if pos=="PK":pos="K"
        if pos=="DEF":pos="DST"
        if pos not in ALL_POSITIONS:continue
        name=player_name(p) or p.get("team") or str(pid)
        n=norm_name(name)
        prior_ppg=0.0
        prod_pct=25.0
        if n in raw_ppg:
            _,prior_ppg=raw_ppg[n]
            prod_pct=percentile_rank(prior_ppg,ppg_by_pos.get(pos,[]))
        try:sr=float(p.get("search_rank"))
        except:sr=9999
        search_score=max(12,min(100,104-math.log10(max(1,sr))*27))
        rank_info=rank_by_name.get(n)
        board_score=20
        board_rank=None
        if rank_info:
            board_rank=rank_info[1]
            board_score=max(45,102-board_rank*2.25)
        injury=(p.get("injury_status") or "").lower()
        penalty=0
        if "ir" in injury or "out" in injury:penalty=12
        elif "doubt" in injury:penalty=7
        elif "question" in injury:penalty=3
        value=max(1,min(100,0.58*prod_pct+0.27*search_score+0.15*board_score-penalty))
        out[str(pid)]={
            "id":str(pid),"name":name,"team":p.get("team") or "",
            "position":pos,"value":round(value,1),"prior_ppg":round(prior_ppg,1),
            "board_rank":board_rank,"injury_status":p.get("injury_status") or "",
            "search_rank":None if sr==9999 else int(sr)
        }
    # Sleeper DST ids are often team abbreviations and may not appear in the player map.
    for team in ESPN_TEAMS:
        if team not in out:
            out[team]={"id":team,"name":team,"team":team,"position":"DST","value":50.0,
                       "prior_ppg":0,"board_rank":None,"injury_status":"","search_rank":None}
    return out

def top_for_position(player_ids,values,pos,count=1):
    items=[values.get(str(pid)) for pid in player_ids]
    items=[x for x in items if x and x.get("position")==pos]
    items.sort(key=lambda x:x["value"],reverse=True)
    return items[:max(1,count)]

def position_slot_counts(roster_positions):
    counts={p:0 for p in ("QB","RB","WR","TE","K","DST")}
    for slot in roster_positions or []:
        s=str(slot).upper()
        if s in counts:counts[s]+=1
    for p in counts:
        if counts[p]==0 and p in ("QB","RB","WR","TE"):
            counts[p]=1
    return counts

def roster_strength(roster,values,slot_counts):
    ids=[str(x) for x in roster.get("players",[]) or []]
    starters=[str(x) for x in roster.get("starters",[]) or [] if str(x)!="0"]
    if starters:
        starter_vals=[values[x]["value"] for x in starters if x in values]
    else:
        starter_vals=[]
        for pos,count in slot_counts.items():
            starter_vals += [x["value"] for x in top_for_position(ids,values,pos,count)]
    starter_avg=statistics.mean(starter_vals) if starter_vals else 0
    bench=[x for x in ids if x not in starters and x in values]
    bench_vals=sorted([values[x]["value"] for x in bench],reverse=True)[:5]
    bench_avg=statistics.mean(bench_vals) if bench_vals else starter_avg
    return round(starter_avg*.82+bench_avg*.18,2),round(starter_avg,2),round(bench_avg,2)

def roster_team_name(roster,users):
    owner=str(roster.get("owner_id") or "")
    u=next((x for x in users if str(x.get("user_id"))==owner),{})
    return ((u.get("metadata") or {}).get("team_name") or u.get("display_name") or u.get("username") or f"Team {roster.get('roster_id')}")

def league_team_analysis(league_id,username):
    user=http_json(f"https://api.sleeper.app/v1/user/{requests.utils.quote(username)}")
    uid=str(user.get("user_id") or "")
    if not uid:raise ValueError("Sleeper user not found")

    # These calls are independent and noticeably faster in parallel on Render.
    urls={
        "league":f"https://api.sleeper.app/v1/league/{league_id}",
        "rosters":f"https://api.sleeper.app/v1/league/{league_id}/rosters",
        "users":f"https://api.sleeper.app/v1/league/{league_id}/users",
        "state":"https://api.sleeper.app/v1/state/nfl",
    }
    responses={}
    with ThreadPoolExecutor(max_workers=4) as ex:
        fut={ex.submit(http_json,url):name for name,url in urls.items()}
        for f in as_completed(fut):
            responses[fut[f]]=f.result()
    league=responses["league"]; rosters=responses["rosters"]; users=responses["users"]; state=responses["state"]
    target=next(
        (r for r in rosters
         if str(r.get("owner_id"))==uid or uid in {str(x) for x in (r.get("co_owners") or [])}),
        None
    )
    if not target:raise ValueError("No roster found for this user in that league")

    scoring=league_scoring_mode(league)
    values=league_value_map(scoring)
    slots=position_slot_counts(league.get("roster_positions"))
    strengths=[]
    for r in rosters:
        total,starter,bench=roster_strength(r,values,slots)
        strengths.append({"roster_id":r.get("roster_id"),"total":total,"starter":starter,"bench":bench})
    target_strength=next(x for x in strengths if x["roster_id"]==target.get("roster_id"))
    sorted_strength=sorted(strengths,key=lambda x:x["total"],reverse=True)
    league_rank=1+next(i for i,x in enumerate(sorted_strength) if x["roster_id"]==target.get("roster_id"))
    pct=percentile_rank(target_strength["total"],[x["total"] for x in strengths])
    grade_score=round(54+pct*.42,1)

    # Position grades are league-relative using each team's top required players.
    pos_grades={}
    for pos,count in slots.items():
        if count<=0:continue
        all_scores=[]
        by_roster={}
        for r in rosters:
            vals=top_for_position(r.get("players",[]) or [],values,pos,count)
            score=statistics.mean([x["value"] for x in vals]) if vals else 0
            by_roster[r.get("roster_id")]=score;all_scores.append(score)
        mine=by_roster.get(target.get("roster_id"),0)
        pp=percentile_rank(mine,all_scores)
        score=round(52+pp*.44,1)
        pos_grades[pos]={
            "score":score,"grade":grade_letter(score),
            "league_rank":1+sum(1 for x in all_scores if x>mine),
            "league_size":len(all_scores),"strength":round(mine,1)
        }

    owned={str(pid) for r in rosters for pid in (r.get("players") or [])}
    trend={str(x.get("player_id")):int(x.get("count") or 0) for x in sleeper_trending()}
    available=[]
    for pid,v in values.items():
        if pid in owned:continue
        if v["position"] not in ALL_POSITIONS:continue
        if not v.get("team") and v["position"]!="DST":continue
        boost=min(8,math.log10(1+trend.get(pid,0))*2.4) if trend.get(pid) else 0
        item=dict(v);item["trend_adds"]=trend.get(pid,0)
        weakness=pos_grades.get(v["position"],{}).get("score",75)
        need_boost=max(0,(75-weakness)*.18)
        item["pickup_score"]=round(min(100,v["value"]+boost+need_boost),1)
        available.append(item)
    available.sort(key=lambda x:x["pickup_score"],reverse=True)

    my_ids=[str(x) for x in target.get("players",[]) or []]
    starters={str(x) for x in target.get("starters",[]) or [] if str(x)!="0"}
    bench_ids=[x for x in my_ids if x not in starters]
    droppable=[dict(values[x]) for x in bench_ids if x in values]
    droppable.sort(key=lambda x:x["value"])

    pickups=[]
    for p in available[:15]:
        reason=[]
        pg=pos_grades.get(p["position"])
        if pg and pg["score"]<72:reason.append(f"{p['position']} is a roster weakness ({pg['grade']})")
        if p.get("trend_adds"):reason.append(f"{p['trend_adds']} recent Sleeper adds")
        if p.get("prior_ppg"):reason.append(f"{p['prior_ppg']} prior-year PPG")
        if p.get("board_rank"):reason.append(f"{p['position']}#{p['board_rank']} on our board")
        if not reason:reason.append("best available value in your free-agent pool")
        q=dict(p);q["reason"]=" • ".join(reason)
        pickups.append(q)

    drops=[]
    for p in droppable[:8]:
        reason=[f"bench value score {p['value']}"]
        if p.get("injury_status"):reason.append(p["injury_status"])
        if p.get("prior_ppg",0)<5:reason.append("limited prior-year production")
        q=dict(p);q["reason"]=" • ".join(reason)
        drops.append(q)

    swaps=[]
    for add in pickups[:8]:
        candidates=[d for d in drops if d["id"]!=add["id"]]
        if not candidates:continue
        # Prefer dropping same-position bench depth, otherwise weakest bench asset.
        same=[d for d in candidates if d["position"]==add["position"]]
        drop=(same or candidates)[0]
        delta=round(add["pickup_score"]-drop["value"],1)
        if delta<4:continue
        swaps.append({
            "add":add,"drop":drop,"delta":delta,
            "reason":f"Adds {delta} points of model value; {add['position']} need and market momentum are factored in."
        })
        if len(swaps)>=6:break

    # Roster diagnosis.
    notes=[]
    weak=sorted(pos_grades.items(),key=lambda kv:kv[1]["score"])
    strong=sorted(pos_grades.items(),key=lambda kv:kv[1]["score"],reverse=True)
    if strong:notes.append(f"Best unit: {strong[0][0]} ({strong[0][1]['grade']}, league rank {strong[0][1]['league_rank']}).")
    if weak:notes.append(f"Priority weakness: {weak[0][0]} ({weak[0][1]['grade']}, league rank {weak[0][1]['league_rank']}/{weak[0][1]['league_size']}).")
    injured=[values[x] for x in my_ids if x in values and values[x].get("injury_status")]
    if injured:notes.append(f"{len(injured)} rostered player(s) currently carry a Sleeper injury designation.")
    if target_strength["bench"]<target_strength["starter"]-12:notes.append("Starter quality is materially ahead of bench depth; prioritize high-upside depth rather than redundant floor.")
    elif target_strength["bench"]>=target_strength["starter"]-5:notes.append("Bench depth is a relative strength; consider packaging depth in a trade for a stronger starter.")

    # Matchup / opponent context if the league has a current matchup.
    matchup=None
    week=int(state.get("week") or state.get("display_week") or 1)
    try:
        matches=http_json(f"https://api.sleeper.app/v1/league/{league_id}/matchups/{week}")
        mine=next((m for m in matches if m.get("roster_id")==target.get("roster_id")),None)
        if mine and mine.get("matchup_id") is not None:
            opp=next((m for m in matches if m.get("matchup_id")==mine.get("matchup_id") and m.get("roster_id")!=target.get("roster_id")),None)
            opp_roster=next((r for r in rosters if opp and r.get("roster_id")==opp.get("roster_id")),None)
            matchup={
                "week":week,"my_points":mine.get("points"),"opponent_points":opp.get("points") if opp else None,
                "opponent":roster_team_name(opp_roster,users) if opp_roster else None
            }
    except Exception:
        matchup=None

    # Recent transactions involving the user's roster.
    moves=[]
    try:
        tx=http_json(f"https://api.sleeper.app/v1/league/{league_id}/transactions/{week}")
        for t in tx:
            if target.get("roster_id") not in (t.get("roster_ids") or []):continue
            adds=[values.get(str(pid),{"name":str(pid)})["name"] for pid,rid in (t.get("adds") or {}).items() if rid==target.get("roster_id")]
            dropsx=[values.get(str(pid),{"name":str(pid)})["name"] for pid,rid in (t.get("drops") or {}).items() if rid==target.get("roster_id")]
            moves.append({"type":t.get("type"),"status":t.get("status"),"adds":adds,"drops":dropsx,"created":t.get("created")})
        moves=sorted(moves,key=lambda x:x.get("created") or 0,reverse=True)[:5]
    except Exception:
        pass

    def player_out(pid):
        v=dict(values.get(str(pid),{"id":str(pid),"name":str(pid),"team":"","position":"","value":0,"prior_ppg":0,"injury_status":""}))
        v["starter"]=str(pid) in starters
        return v

    starters_out=[player_out(x) for x in target.get("starters",[]) or [] if str(x)!="0"]
    bench_out=[player_out(x) for x in my_ids if x not in starters]

    return {
        "provider":"Sleeper",
        "user":{"username":user.get("username"),"display_name":user.get("display_name")},
        "league":{
            "league_id":league_id,"name":league.get("name"),"season":league.get("season"),
            "status":league.get("status"),"teams":league.get("total_rosters"),
            "scoring":scoring,"roster_positions":league.get("roster_positions") or []
        },
        "team":{
            "name":roster_team_name(target,users),"roster_id":target.get("roster_id"),
            "record":{"wins":(target.get("settings") or {}).get("wins",0),"losses":(target.get("settings") or {}).get("losses",0),"ties":(target.get("settings") or {}).get("ties",0)},
            "waiver_position":(target.get("settings") or {}).get("waiver_position"),
            "waiver_budget_used":(target.get("settings") or {}).get("waiver_budget_used"),
            "grade":{"score":grade_score,"letter":grade_letter(grade_score),"league_rank":league_rank,"league_size":len(rosters)},
            "position_grades":pos_grades,
            "strength":{"overall":target_strength["total"],"starters":target_strength["starter"],"bench":target_strength["bench"]},
            "starters":starters_out,"bench":bench_out
        },
        "matchup":matchup,
        "diagnosis":notes,
        "pickups":pickups[:10],
        "drops":drops[:6],
        "swaps":swaps,
        "recent_moves":moves,
        "methodology":"Roster grade is league-relative. Player values combine prior-season fantasy production, current draft-board rank, Sleeper market/search rank and current injury status. Pickup suggestions use the actual unrostered player pool in this Sleeper league."
    }



ESPN_POSITIONS={1:"QB",2:"RB",3:"WR",4:"TE",5:"K",16:"DST"}
ESPN_PRO_TEAMS={
    1:"ATL",2:"BUF",3:"CHI",4:"CIN",5:"CLE",6:"DAL",7:"DEN",8:"DET",9:"GB",
    10:"TEN",11:"IND",12:"KC",13:"LV",14:"LAR",15:"MIA",16:"MIN",17:"NE",
    18:"NO",19:"NYG",20:"NYJ",21:"PHI",22:"ARI",23:"PIT",24:"LAC",25:"SF",
    26:"SEA",27:"TB",28:"WSH",29:"CAR",30:"JAX",33:"BAL",34:"HOU"
}

def espn_scoring_mode(league):
    items=(((league.get("settings") or {}).get("scoringSettings") or {}).get("scoringItems") or [])
    rec=0
    for item in items:
        try:
            stat_id=int(item.get("statId"))
            points=float(item.get("points") or 0)
        except Exception:
            continue
        if stat_id in (41,53):
            rec=max(rec,points)
    if rec>=0.75:return "PPR"
    if rec>=0.25:return "HALF"
    return "STD"

def espn_team_name(team,members):
    location=(team.get("location") or "").strip()
    nickname=(team.get("nickname") or "").strip()
    explicit=(team.get("name") or "").strip()
    if explicit:return explicit
    if location or nickname:return (location+" "+nickname).strip()
    owners={str(x) for x in (team.get("owners") or [])}
    member=next((m for m in members if str(m.get("id")) in owners),{})
    return member.get("displayName") or f"Team {team.get('id')}"

def espn_player_obj(entry):
    if not isinstance(entry,dict):return {}
    pool=entry.get("playerPoolEntry") or entry
    player=pool.get("player") or entry.get("player") or {}
    pid=entry.get("playerId") or pool.get("id") or player.get("id") or entry.get("id")
    return {"entry":entry,"pool":pool,"player":player,"id":str(pid) if pid is not None else ""}

def espn_value_indexes(scoring):
    sleeper_values=league_value_map(scoring)
    by_name={norm_name(v.get("name")):dict(v) for v in sleeper_values.values() if v.get("name")}
    trending_by_name={}
    sp=sleeper_players()
    for tr in sleeper_trending():
        pid=str(tr.get("player_id"))
        p=sp.get(pid,{})
        n=norm_name(player_name(p))
        if n:trending_by_name[n]=int(tr.get("count") or 0)
    return by_name,trending_by_name

def espn_normalize_player(entry,by_name,trending_by_name):
    obj=espn_player_obj(entry);p=obj["player"];pid=obj["id"]
    name=(p.get("fullName") or " ".join(x for x in [p.get("firstName"),p.get("lastName")] if x) or str(pid)).strip()
    n=norm_name(name)
    base=dict(by_name.get(n,{}) or {})
    try:position_id=int(p.get("defaultPositionId"))
    except Exception:position_id=0
    pos=base.get("position") or ESPN_POSITIONS.get(position_id,"")
    try:pro_team=int(p.get("proTeamId"))
    except Exception:pro_team=0
    team=base.get("team") or ESPN_PRO_TEAMS.get(pro_team,"")
    injury=p.get("injuryStatus") or base.get("injury_status") or ""
    ownership=p.get("ownership") or {}
    try:owned=float(ownership.get("percentOwned") or 0)
    except Exception:owned=0
    value=base.get("value")
    if value is None:
        value=max(18,min(82,24+owned*.58))
        if str(injury).upper() in ("OUT","INJURY_RESERVE","IR"):
            value-=10
    return {
        "id":pid,"name":name,"team":team,"position":pos,
        "value":round(float(value),1),
        "prior_ppg":base.get("prior_ppg",0),
        "board_rank":base.get("board_rank"),
        "injury_status":injury,
        "percent_owned":round(owned,1),
        "trend_adds":trending_by_name.get(n,0)
    }

def espn_roster_entries(team):
    return (((team.get("roster") or {}).get("entries")) or [])

def espn_slot_counts(league):
    counts={p:0 for p in ("QB","RB","WR","TE","K","DST")}
    raw=((((league.get("settings") or {}).get("rosterSettings") or {}).get("lineupSlotCounts")) or {})
    slot_to_pos={0:"QB",2:"RB",4:"WR",6:"TE",16:"DST",17:"K"}
    for slot,count in raw.items():
        try:s=int(slot);c=int(count or 0)
        except Exception:continue
        pos=slot_to_pos.get(s)
        if pos:counts[pos]+=c
    for p in ("QB","RB","WR","TE"):
        if counts[p]<=0:counts[p]=1
    return counts

def espn_roster_strength(players,slot_counts):
    by_pos={p:[] for p in slot_counts}
    for x in players:
        if x.get("position") in by_pos:
            by_pos[x["position"]].append(x)
    starters=[];chosen=set()
    for pos,count in slot_counts.items():
        arr=sorted(by_pos.get(pos,[]),key=lambda x:x.get("value",0),reverse=True)
        for x in arr[:count]:
            starters.append(x);chosen.add(x["id"])
    bench=[x for x in players if x["id"] not in chosen]
    starter_vals=[x["value"] for x in starters]
    bench_vals=sorted([x["value"] for x in bench],reverse=True)[:5]
    starter_avg=statistics.mean(starter_vals) if starter_vals else 0
    bench_avg=statistics.mean(bench_vals) if bench_vals else starter_avg
    return round(starter_avg*.82+bench_avg*.18,2),round(starter_avg,2),round(bench_avg,2),starters,bench

def espn_analyze_snapshot(snapshot):
    league=snapshot.get("league") or {}
    free_entries=snapshot.get("freeAgents") or []
    members=league.get("members") or []
    teams=league.get("teams") or []
    if not teams:raise ValueError("ESPN sync returned no fantasy teams")
    try:my_team_id=int(snapshot.get("teamId"))
    except Exception:raise ValueError("Open your ESPN team page so the extension can identify teamId")
    my_team=next((t for t in teams if int(t.get("id") or -1)==my_team_id),None)
    if not my_team:raise ValueError("Could not match the ESPN teamId to this league")

    scoring=espn_scoring_mode(league)
    by_name,trending_by_name=espn_value_indexes(scoring)
    slots=espn_slot_counts(league)

    normalized={};strengths=[]
    for team in teams:
        ps=[espn_normalize_player(e,by_name,trending_by_name) for e in espn_roster_entries(team)]
        ps=[x for x in ps if x.get("position") in ALL_POSITIONS]
        total,starter,bench,starters,bench_players=espn_roster_strength(ps,slots)
        tid=int(team.get("id"))
        normalized[tid]={"players":ps,"starters":starters,"bench_players":bench_players,"total":total,"starter":starter,"bench":bench}
        strengths.append({"team_id":tid,"total":total,"starter":starter,"bench":bench})

    mine=normalized[my_team_id]
    sorted_strength=sorted(strengths,key=lambda x:x["total"],reverse=True)
    league_rank=1+next(i for i,x in enumerate(sorted_strength) if x["team_id"]==my_team_id)
    pct=percentile_rank(mine["total"],[x["total"] for x in strengths])
    grade_score=round(54+pct*.42,1)

    pos_grades={}
    for pos,count in slots.items():
        if count<=0:continue
        scores={}
        for tid,data in normalized.items():
            vals=sorted([x["value"] for x in data["players"] if x["position"]==pos],reverse=True)[:count]
            scores[tid]=statistics.mean(vals) if vals else 0
        my_score=scores.get(my_team_id,0)
        pp=percentile_rank(my_score,list(scores.values()))
        score=round(52+pp*.44,1)
        pos_grades[pos]={"score":score,"grade":grade_letter(score),"league_rank":1+sum(1 for x in scores.values() if x>my_score),"league_size":len(scores),"strength":round(my_score,1)}

    free_agents=[]
    for e in free_entries:
        x=espn_normalize_player(e,by_name,trending_by_name)
        if x.get("position") not in ALL_POSITIONS:continue
        weakness=pos_grades.get(x["position"],{}).get("score",75)
        trend_boost=min(8,math.log10(1+x.get("trend_adds",0))*2.4) if x.get("trend_adds") else 0
        own_boost=min(5,(x.get("percent_owned") or 0)/20)
        need_boost=max(0,(75-weakness)*.18)
        x["pickup_score"]=round(min(100,x["value"]+trend_boost+own_boost+need_boost),1)
        reason=[]
        pg=pos_grades.get(x["position"])
        if pg and pg["score"]<72:reason.append(f"{x['position']} is a roster weakness ({pg['grade']})")
        if x.get("trend_adds"):reason.append(f"{x['trend_adds']} recent Sleeper adds")
        if x.get("percent_owned"):reason.append(f"{x['percent_owned']}% ESPN rostered")
        if x.get("prior_ppg"):reason.append(f"{x['prior_ppg']} prior-year PPG")
        if x.get("board_rank"):reason.append(f"{x['position']}#{x['board_rank']} Command Center board")
        if not reason:reason.append("best available model value in the synced ESPN pool")
        x["reason"]=" • ".join(reason)
        free_agents.append(x)
    free_agents.sort(key=lambda x:x["pickup_score"],reverse=True)

    starters_ids={x["id"] for x in mine["starters"]}
    droppable=[dict(x) for x in mine["players"] if x["id"] not in starters_ids]
    droppable.sort(key=lambda x:x["value"])
    drops=[]
    for p in droppable[:8]:
        q=dict(p);reason=[f"bench value {p['value']}"]
        if p.get("injury_status"):reason.append(str(p["injury_status"]))
        if p.get("prior_ppg",0)<5:reason.append("limited prior-year production")
        q["reason"]=" • ".join(reason);drops.append(q)

    swaps=[]
    for add in free_agents[:10]:
        if not drops:break
        same=[d for d in drops if d["position"]==add["position"]]
        drop=(same or drops)[0]
        delta=round(add["pickup_score"]-drop["value"],1)
        if delta<4:continue
        swaps.append({"add":add,"drop":drop,"delta":delta,"reason":f"{add['position']} need, ESPN availability and current market value produce a {delta}-point modeled upgrade."})
        if len(swaps)>=6:break

    weak=sorted(pos_grades.items(),key=lambda kv:kv[1]["score"])
    strong=sorted(pos_grades.items(),key=lambda kv:kv[1]["score"],reverse=True)
    notes=[]
    if strong:notes.append(f"Best unit: {strong[0][0]} ({strong[0][1]['grade']}, league rank {strong[0][1]['league_rank']}).")
    if weak:notes.append(f"Priority weakness: {weak[0][0]} ({weak[0][1]['grade']}, league rank {weak[0][1]['league_rank']}/{weak[0][1]['league_size']}).")
    injured=[x for x in mine["players"] if x.get("injury_status") and str(x.get("injury_status")).upper()!="ACTIVE"]
    if injured:notes.append(f"{len(injured)} rostered player(s) currently carry an ESPN injury designation.")
    if mine["bench"]<mine["starter"]-12:notes.append("Starter quality is materially ahead of bench depth; prioritize high-upside depth.")
    elif mine["bench"]>=mine["starter"]-5:notes.append("Bench depth is strong enough to consider a 2-for-1 consolidation trade.")

    record=my_team.get("record") or {}
    overall=record.get("overall") or record
    transaction_counter=my_team.get("transactionCounter") or {}
    scoring_period=league.get("scoringPeriodId") or ((league.get("status") or {}).get("currentMatchupPeriod"))
    matchup=None
    try:sp=int(scoring_period or 0)
    except:sp=0
    for m in league.get("schedule") or []:
        if int(m.get("matchupPeriodId") or -1)!=sp:continue
        home=m.get("home") or {};away=m.get("away") or {}
        if int(home.get("teamId") or -1)==my_team_id or int(away.get("teamId") or -1)==my_team_id:
            mine_side=home if int(home.get("teamId") or -1)==my_team_id else away
            opp_side=away if mine_side is home else home
            opp_id=int(opp_side.get("teamId") or -1)
            opp_team=next((t for t in teams if int(t.get("id") or -1)==opp_id),None)
            matchup={"week":sp,"my_points":mine_side.get("totalPoints"),"opponent_points":opp_side.get("totalPoints"),"opponent":espn_team_name(opp_team or {},members)}
            break

    def out_player(x):
        q=dict(x);q["starter"]=x["id"] in starters_ids;return q

    return {
        "provider":"ESPN","synced_at":snapshot.get("syncedAt"),
        "league":{"league_id":str(snapshot.get("leagueId") or league.get("id") or ""),"name":((league.get("settings") or {}).get("name") or league.get("name") or "ESPN League"),"season":snapshot.get("season") or SEASON,"status":((league.get("status") or {}).get("type") or "synced"),"teams":len(teams),"scoring":scoring,"roster_positions":[k for k,v in slots.items() for _ in range(max(0,v))]},
        "team":{"name":espn_team_name(my_team,members),"roster_id":my_team_id,"record":{"wins":overall.get("wins",0),"losses":overall.get("losses",0),"ties":overall.get("ties",0)},"waiver_position":my_team.get("waiverRank"),"waiver_budget_used":transaction_counter.get("acquisitionBudgetSpent"),"grade":{"score":grade_score,"letter":grade_letter(grade_score),"league_rank":league_rank,"league_size":len(teams)},"position_grades":pos_grades,"strength":{"overall":mine["total"],"starters":mine["starter"],"bench":mine["bench"]},"starters":[out_player(x) for x in mine["starters"]],"bench":[out_player(x) for x in mine["bench_players"]]},
        "matchup":matchup,"diagnosis":notes,"pickups":free_agents[:10],"drops":drops[:6],"swaps":swaps,"recent_moves":[],
        "methodology":"ESPN private sync is analyzed without storing ESPN authentication cookies. Roster grade is league-relative. Player values combine prior-season production, Command Center board rank, ESPN ownership, Sleeper market movement and injury status. Pickup suggestions come from the ESPN FREEAGENT/WAIVERS pool captured during this sync."
    }


@app.route("/")
def index():
    return render_template("index.html",live=bool(FANTASYPROS_KEY),season=SEASON)

@app.get("/api/dashboard")
def dashboard():
    SOURCE_STATE.clear()
    scoring=request.args.get("scoring","PPR").upper()
    if scoring not in SCORING: scoring="PPR"
    try:
        data=fallback()
        ranks=rankings(scoring)
        data.update({
            "rankings":ranks,"analytics":{},"sleepers":[],
            "injury_risk":[],"offenses":[],"defenses":[],
            "meta":{
                "season":SEASON,"prior_season":PRIOR_SEASON,"scoring":scoring,
                "fantasypros_live":bool(FANTASYPROS_KEY),"analytics_live":True,
                "projection_model":"5-season recency-weighted PPG + capped trend adjustment",
                "injury_history_through":2024,"progressive_loading":True,
                "source_status":dict(SOURCE_STATE),
                "counts":{p:len(ranks.get(p,[])) for p in ALL_POSITIONS},
                "updated":int(time.time()),"degraded":False
            }
        })
        return jsonify(data)
    except Exception as e:
        source_fail("dashboard",e)
        data=fallback()
        ranks=data.get("rankings",{})
        data.update({
            "analytics":{},"sleepers":data.get("sleepers",[]),
            "injury_risk":[],"offenses":[],"defenses":[],
            "meta":{
                "season":SEASON,"prior_season":PRIOR_SEASON,"scoring":scoring,
                "fantasypros_live":False,"analytics_live":False,
                "progressive_loading":True,"source_status":dict(SOURCE_STATE),
                "counts":{p:len(ranks.get(p,[])) for p in ALL_POSITIONS},
                "updated":int(time.time()),"degraded":True,
                "degraded_reason":str(e)[:220]
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

@app.get("/api/sleeper-radar")
def sleeper_radar_api():
    scoring=request.args.get("scoring","PPR").upper()
    if scoring not in SCORING:scoring="PPR"
    try:
        ranks=rankings(scoring)
        items=sleeper_candidates(ranks,limit=60)
        enriched=enrich_sleepers(items,{},with_news=True)
        return jsonify({
            "items":enriched,"sources":dict(SOURCE_STATE),
            "analysis_note":"Each sleeper is ranked by role evidence, depth-chart opportunity, teammate availability, recent news and market confirmation. Duplicate/stale negative records are removed."
        })
    except Exception as e:
        source_fail("sleeper_radar",e)
        return jsonify({"items":[],"error":"sleeper_radar_unavailable","message":str(e),"sources":dict(SOURCE_STATE)}),503

@app.get("/api/injury-risk")
def injury_risk_api():
    scoring=request.args.get("scoring","PPR").upper()
    if scoring not in SCORING: scoring="PPR"
    try:
        ranks=rankings(scoring)
        return jsonify({
            "items":injury_risk_summary(ranks),
            "injury_history_through":2024,
            "progressive_detail":True,
            "sources":dict(SOURCE_STATE)
        })
    except Exception as e:
        source_fail("injury_risk",e)
        # Return a valid JSON response even when upstream injury history is unavailable.
        return jsonify({
            "items":[],
            "injury_history_through":2024,
            "progressive_detail":True,
            "error":"injury_summary_unavailable",
            "message":str(e),
            "sources":dict(SOURCE_STATE)
        }), 200

@app.get("/api/injury-detail")
def injury_detail_api():
    name=request.args.get("name","").strip()
    if not name:
        return jsonify({"error":"name required","message":"Player name is required."}),400
    try:
        return jsonify(injury_detail(name))
    except ValueError as e:
        return jsonify({"error":"player_not_found","message":str(e)}),404
    except Exception as e:
        source_fail("injury_detail",e)
        return jsonify({
            "error":"injury_detail_unavailable",
            "message":str(e)
        }),503


NEWS_CACHE_TTL = 1800       # 30 minutes
NEWS_STALE_TTL = 86400      # serve last-good feed for up to 24 hours
FANTASY_TERMS = (
    "fantasy","draft","sleeper","waiver","breakout","rankings","adp","injury",
    "rookie","start/sit","start sit","depth chart","target share","touches",
    "league winner","riskiest","value","overvalued","undervalued"
)

def strip_markup(value):
    text=re.sub(r"<[^>]+>"," ",value or "")
    text=html_lib.unescape(text)
    text=re.sub(r"\s+"," ",text).strip()
    return text

def parse_pubdate(value):
    if not value:
        return 0
    try:
        dt=parsedate_to_datetime(value)
        return int(dt.timestamp())
    except Exception:
        return 0

def rss_articles(url, source, limit=20):
    text=http_text(url,timeout=12)
    root=ET.fromstring(text)
    out=[]
    for item in root.findall(".//item")[:limit]:
        title=strip_markup(item.findtext("title") or "")
        link=(item.findtext("link") or "").strip()
        desc=strip_markup(item.findtext("description") or "")
        published=parse_pubdate(item.findtext("pubDate") or item.findtext("date") or "")
        if not title or not link:
            continue
        out.append({
            "title":title,
            "url":link,
            "summary":desc[:260],
            "source":source,
            "published_ts":published,
        })
    return out

def google_news_rss(query, source, limit=15):
    url=(
        "https://news.google.com/rss/search?q="+quote_plus(query)+
        "&hl=en-US&gl=US&ceid=US:en"
    )
    return rss_articles(url,source,limit)

def fantasypros_news_api(limit=20):
    if not FANTASYPROS_KEY:
        return []
    try:
        payload=fp("/nfl/news",{"limit":limit,"order_by":"created"})
        arr=payload.get("items") or payload.get("news") or payload.get("player_news") or []
        out=[]
        for x in arr:
            title=x.get("title") or x.get("headline") or ""
            link=x.get("url") or x.get("link") or x.get("source_url") or ""
            summary=x.get("description") or x.get("summary") or x.get("analysis") or ""
            created=x.get("created") or x.get("created_at") or x.get("updated") or ""
            published=0
            if isinstance(created,(int,float)):
                published=int(created)
            elif created:
                try:
                    published=int(parsedate_to_datetime(created).timestamp())
                except Exception:
                    try:
                        published=int(__import__("datetime").datetime.fromisoformat(created.replace("Z","+00:00")).timestamp())
                    except Exception:
                        published=0
            if title and link:
                out.append({
                    "title":strip_markup(title),"url":link,"summary":strip_markup(summary)[:260],
                    "source":"FantasyPros","published_ts":published
                })
        return out
    except Exception as e:
        source_fail("news_fantasypros_api",e)
        return []

def article_relevance(article):
    blob=(article.get("title","")+" "+article.get("summary","")).lower()
    hits=sum(1 for term in FANTASY_TERMS if term in blob)
    age_hours=max(0,(time.time()-(article.get("published_ts") or 0))/3600) if article.get("published_ts") else 240
    freshness=max(0,100-age_hours*2.2)
    source_bonus={"NFL.com":10,"FantasyPros":10,"ESPN":8,"CBS Sports":6,"Yahoo Sports":5}.get(article.get("source"),0)
    return round(freshness + hits*16 + source_bonus,2)

def build_news_feed():
    jobs=[
        ("ESPN",lambda:rss_articles("https://www.espn.com/espn/rss/nfl/news","ESPN",25)),
        ("CBS Sports",lambda:rss_articles("https://www.cbssports.com/rss/headlines/nfl","CBS Sports",25)),
        ("NFL.com",lambda:google_news_rss('fantasy football site:nfl.com/news',"NFL.com",20)),
        ("FantasyPros",lambda:(fantasypros_news_api(20) or google_news_rss('fantasy football site:fantasypros.com',"FantasyPros",20))),
        ("Yahoo Sports",lambda:google_news_rss('fantasy football site:sports.yahoo.com',"Yahoo Sports",15)),
    ]
    articles=[]
    source_results={}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures={ex.submit(fn):name for name,fn in jobs}
        for fut in as_completed(futures):
            name=futures[fut]
            try:
                items=fut.result()
                source_results[name]={"ok":True,"count":len(items)}
                articles.extend(items)
            except Exception as e:
                source_results[name]={"ok":False,"count":0,"error":str(e)[:160]}

    # Deduplicate syndicated/repeated headlines.
    dedup={}
    for a in articles:
        k=re.sub(r"[^a-z0-9]+"," ",a["title"].lower()).strip()
        if not k:
            continue
        a["trend_score"]=article_relevance(a)
        current=dedup.get(k)
        if current is None or (a.get("published_ts") or 0) > (current.get("published_ts") or 0):
            dedup[k]=a

    ordered=sorted(
        dedup.values(),
        key=lambda a:(a.get("trend_score",0),a.get("published_ts",0)),
        reverse=True
    )
    # Keep enough stories to make source filters useful while bounding payload.
    return {
        "generated_at":int(time.time()),
        "items":ordered[:60],
        "source_results":source_results,
        "ranking_note":"Ordered by freshness and fantasy relevance; not publisher view counts."
    }

def cached_news_feed(force=False):
    return stale_cached_json(
        "fantasy_news_feed",NEWS_CACHE_TTL,NEWS_STALE_TTL,
        build_news_feed,force=force
    )


@app.get("/api/team-power")
def team_power_api():
    try:
        offenses,defenses=team_power()
        return jsonify({"offenses":offenses,"defenses":defenses,"sources":dict(SOURCE_STATE),"degraded":False})
    except Exception as e:
        source_fail("team_power",e)
        fb=fallback()
        offenses=[];defenses=[]
        for i,x in enumerate(fb.get("offenses",[])[:10],1):
            q=dict(x);q.setdefault("name",q.get("team",""));q["rank"]=i;q["source"]="bundled emergency fallback";q.setdefault("analysis","Live team sources failed; this is a temporary fallback ordering.");q.setdefault("stats",[]);offenses.append(q)
        for i,x in enumerate(fb.get("defenses",[])[:10],1):
            q=dict(x);q.setdefault("name",q.get("team",""));q["rank"]=i;q["source"]="bundled emergency fallback";q.setdefault("analysis","Live team sources failed; this is a temporary fallback ordering.");q.setdefault("stats",[]);defenses.append(q)
        return jsonify({"offenses":offenses,"defenses":defenses,"sources":dict(SOURCE_STATE),"degraded":True,"message":str(e)[:220]})

@app.get("/api/news")
def news_api():
    force=request.args.get("force","0")=="1"
    # Avoid turning a public refresh button into an upstream hammer: a forced
    # refresh is honored only if the existing cache is at least 5 minutes old.
    p=CACHE_DIR/"fantasy_news_feed.json"
    if force and p.exists() and time.time()-p.stat().st_mtime < 300:
        force=False
    try:
        data,meta=cached_news_feed(force=force)
        source_ok(
            "news_feed",
            f"{len(data.get('items',[]))} articles • {'stale cache' if meta.get('stale') else 'fresh/cache'}"
        )
        return jsonify({
            **data,
            "cache":meta,
            "sources":dict(SOURCE_STATE)
        })
    except Exception as e:
        source_fail("news_feed",e)
        return jsonify({"error":"news_unavailable","message":str(e),"items":[],"sources":dict(SOURCE_STATE)}),503

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
        "note":"Player analytics, injury history, team power, and News Radar load on demand. ESPN and news feeds use disk caches."
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



@app.post("/api/espn/analyze")
def espn_analyze_api():
    snapshot=request.get_json(silent=True) or {}
    if str(snapshot.get("provider") or "").upper()!="ESPN":
        return jsonify({"error":"invalid_provider","message":"Expected ESPN sync payload"}),400
    forbidden=("espn_s2","swid","password","cookie","authorization")
    flat_keys=" ".join(str(k).lower() for k in snapshot.keys())
    if any(x in flat_keys for x in forbidden):
        return jsonify({"error":"credentials_not_accepted","message":"Do not send ESPN cookies, passwords, or authorization headers."}),400
    try:
        return jsonify(espn_analyze_snapshot(snapshot))
    except ValueError as e:
        return jsonify({"error":"espn_sync_invalid","message":str(e)}),400
    except Exception as e:
        return jsonify({"error":"espn_analysis_failed","message":str(e)}),500

@app.get("/api/sleeper/team-analysis/<league_id>")
def sleeper_team_analysis_api(league_id):
    username=request.args.get("username","").strip()
    if not username:return jsonify({"error":"username required"}),400
    try:
        return jsonify(league_team_analysis(league_id,username))
    except ValueError as e:
        return jsonify({"error":str(e)}),404
    except Exception as e:
        return jsonify({"error":"team_analysis_failed","message":str(e)}),500

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
