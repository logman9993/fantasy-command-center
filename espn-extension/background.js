
const ESPN_READ="https://lm-api-reads.fantasy.espn.com";
const APP_URL="https://fantasy-command-center.onrender.com";

async function getJson(url,options={}){
  const response=await fetch(url,{
    ...options,
    credentials:"include",
    cache:"no-store",
    headers:{
      "Accept":"application/json",
      ...(options.headers||{})
    }
  });

  let text="";
  try{text=await response.text()}catch{}

  if(!response.ok){
    throw new Error(
      `ESPN HTTP ${response.status}${text?` — ${text.slice(0,220)}`:""}`
    );
  }

  try{
    return JSON.parse(text);
  }catch{
    throw new Error(
      "ESPN returned a non-JSON response. The request may have been redirected to a login page."
    );
  }
}

async function testEspn(){
  const d=await getJson(`${ESPN_READ}/apis/v3/games/ffl`);
  if(!d || String(d.abbrev||"").toUpperCase()!=="FFL"){
    throw new Error("ESPN fantasy API test returned an unexpected response.");
  }
  return d;
}

async function collectSnapshot({leagueId,teamId,season}){
  await testEspn();

  const base=
    `${ESPN_READ}/apis/v3/games/ffl/seasons/${encodeURIComponent(season)}`+
    `/segments/0/leagues/${encodeURIComponent(leagueId)}`;

  const league=await getJson(
    base+"?view=mSettings&view=mTeam&view=mRoster&view=mMatchup&view=mStandings&view=mStatus"
  );

  if(!Array.isArray(league.teams) || !league.teams.length){
    throw new Error(
      "ESPN league request succeeded but returned no teams. If this is a private league, the ESPN session was probably not attached to the API request."
    );
  }

  const scoringPeriodId=
    league.scoringPeriodId||
    league.status?.currentMatchupPeriod||
    1;

  const filter={
    players:{
      filterStatus:{value:["FREEAGENT","WAIVERS"]},
      filterSlotIds:{value:[0,2,4,6,17,16]},
      limit:250,
      sortPercOwned:{sortPriority:1,sortAsc:false}
    }
  };

  const free=await getJson(
    `${base}?view=kona_player_info&scoringPeriodId=${encodeURIComponent(scoringPeriodId)}`,
    {
      headers:{
        "X-Fantasy-Filter":JSON.stringify(filter)
      }
    }
  );

  return {
    provider:"ESPN",
    syncedAt:Date.now(),
    leagueId:String(leagueId),
    teamId:String(teamId),
    season:Number(season),
    league,
    freeAgents:Array.isArray(free.players)?free.players:[]
  };
}

async function analyze(snapshot){
  const response=await fetch(APP_URL+"/api/espn/analyze",{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(snapshot)
  });

  let data;
  try{data=await response.json()}catch{
    throw new Error(`Command Center returned HTTP ${response.status} with non-JSON content.`);
  }

  if(!response.ok){
    throw new Error(
      data.message||data.error||`Command Center returned HTTP ${response.status}`
    );
  }

  await chrome.storage.local.set({
    espnAnalysis:data,
    espnAnalysisUpdated:Date.now()
  });

  return data;
}

chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{
  if(message?.type!=="FCC_SYNC_ESPN")return;

  (async()=>{
    try{
      const snapshot=await collectSnapshot({
        leagueId:message.leagueId,
        teamId:message.teamId,
        season:message.season
      });

      const analysis=await analyze(snapshot);

      await chrome.tabs.create({
        url:APP_URL+"/?espn_sync=1"
      });

      sendResponse({
        ok:true,
        teams:Array.isArray(snapshot.league?.teams)?snapshot.league.teams.length:0,
        freeAgents:snapshot.freeAgents.length,
        grade:analysis?.team?.grade?.letter||"",
        team:analysis?.team?.name||""
      });
    }catch(e){
      let msg=e?.message||String(e);

      if(/HTTP (401|403)/.test(msg)){
        msg +=
          "\n\nESPN's current API host is reachable, but your private-league session was not accepted. "+
          "Refresh ESPN, confirm you are signed in, and retry.";
      }

      sendResponse({ok:false,message:msg});
    }
  })();

  return true;
});
