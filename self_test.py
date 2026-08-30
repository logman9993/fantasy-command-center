
import sys, types

flask=types.ModuleType("flask")
class DummyResponse:
    def __init__(self,obj=None): self.obj=obj
    def get_json(self): return self.obj
class DummyFlask:
    def __init__(self,*a,**k): pass
    def route(self,*a,**k): return lambda f:f
    def get(self,*a,**k): return lambda f:f
    def run(self,*a,**k): pass
flask.Flask=DummyFlask
flask.render_template=lambda *a,**k:""
flask.jsonify=lambda obj=None,**k:DummyResponse(obj if obj is not None else k)
flask.request=types.SimpleNamespace(args={})
sys.modules["flask"]=flask

from app import fantasy_points, aggregate_nflverse_team_rows, team_analysis_cards, dst_fallback

def test_interception_field():
    row={"position":"QB","passing_yards":"250","passing_tds":"2","passing_interceptions":"2","games":"1"}
    # 250*.04 + 2*4 - 2*2 = 14.
    assert abs(fantasy_points(row,"PPR")-14.0)<0.001

def synthetic_team_rows():
    teams=[f"T{i:02d}" for i in range(32)]
    rows=[]
    for week in range(1,18):
        for i,t in enumerate(teams):
            rows.append({
                "season_type":"REG","team":t,"opponent_team":teams[(i+1)%32],
                "passing_yards":str(180+i*2),"rushing_yards":str(90+i),
                "passing_tds":str(1+(i%3)),"rushing_tds":str(i%2),"special_teams_tds":"0",
                "passing_epa":str(5+i*.3),"rushing_epa":str(1+i*.1),
                "passing_interceptions":str(i%2),"rushing_fumbles_lost":"0","receiving_fumbles_lost":"0","sack_fumbles_lost":"0",
                "sacks_suffered":str(1+(i%4)),"field_goals_made":"2","extra_points_made":"2",
                "passing_2pt_conversions":"0","rushing_2pt_conversions":"0","receiving_2pt_conversions":"0"
            })
    return rows

def test_team_model():
    off,defs=aggregate_nflverse_team_rows(synthetic_team_rows())
    assert len(off)==32 and len(defs)==32
    oc,dc=team_analysis_cards(off,defs,"test")
    assert len(oc)==10 and len(dc)==10
    assert len(dc[0]["stats"])>=6
    assert all(isinstance(s["league_rank"],int) for s in dc[0]["stats"])

if __name__=="__main__":
    test_interception_field()
    test_team_model()
    print("SELF TEST PASS")
