
let current=null;
const status=document.getElementById("status");
const syncBtn=document.getElementById("sync");

function setStatus(text,kind=""){
  status.textContent=text;
  status.className=kind;
}
function parseEspn(urlString){
  const u=new URL(urlString);
  if(u.hostname!=="fantasy.espn.com")throw new Error("Open fantasy.espn.com first.");
  const leagueId=u.searchParams.get("leagueId");
  const teamId=u.searchParams.get("teamId");
  const season=u.searchParams.get("seasonId")||"2026";
  if(!leagueId)throw new Error("Open an ESPN Fantasy Football league/team page containing leagueId.");
  if(!teamId)throw new Error("Open your ESPN team page so the URL contains teamId.");
  return {leagueId,teamId,season};
}
function sendRuntime(message){
  return new Promise((resolve,reject)=>{
    chrome.runtime.sendMessage(message,response=>{
      if(chrome.runtime.lastError){
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response);
    });
  });
}
async function init(){
  try{
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    current={tab,...parseEspn(tab.url)};
    document.getElementById("league").textContent=current.leagueId;
    document.getElementById("team").textContent=current.teamId;
    document.getElementById("season").textContent=current.season;
    syncBtn.disabled=false;
    setStatus("Ready. ESPN team page detected.","good");
  }catch(e){
    setStatus(e.message,"bad");
  }
}
syncBtn.addEventListener("click",async()=>{
  if(!current)return;
  syncBtn.disabled=true;
  setStatus("1/3 Testing ESPN fantasy API connection…");
  try{
    const result=await sendRuntime({
      type:"FCC_SYNC_ESPN",
      leagueId:current.leagueId,
      teamId:current.teamId,
      season:current.season
    });
    if(!result?.ok){
      throw new Error(result?.message||"No response from ESPN sync worker.");
    }
    setStatus(
      `3/3 Sync complete.\nCaptured ${result.teams} teams and ${result.freeAgents} available players.\nOpening Command Center…`,
      "good"
    );
    setTimeout(()=>window.close(),700);
  }catch(e){
    setStatus(e.message||String(e),"bad");
    syncBtn.disabled=false;
  }
});
init();
