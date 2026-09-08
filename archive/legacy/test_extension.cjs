const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
(async () => {
  const source = fs.readFileSync(path.join(__dirname,'espn-extension/background.js'),'utf8');
  const requests = [];
  const ctx = {AbortSignal, chrome:{runtime:{onMessage:{addListener(){}}}}, fetch: async url => {
    requests.push(url);
    return {ok:true,text:async()=>JSON.stringify(url.includes('kona_player_info')?{players:[]}:{teams:[{id:1}],scoringPeriodId:1})};
  }};
  vm.createContext(ctx);vm.runInContext(source,ctx);
  const result = await vm.runInContext('collectSnapshot({leagueId:123,teamId:1,season:2026})',ctx);
  assert.equal(requests.length,2);
  assert.equal(result.league.teams.length,1);
  assert(requests.every(url=>url.includes('/leagues/123')));
  await assert.rejects(vm.runInContext('collectSnapshot({leagueId:"bad",teamId:1,season:2026})',ctx),/numeric/);
  const bridge = fs.readFileSync(path.join(__dirname,'espn-extension/command-center-bridge.js'),'utf8');
  const sent=[];
  const context={URLSearchParams,Date,location:{search:'',origin:'https://fantasy-command-center.onrender.com'},document:{readyState:'complete'},window:{postMessage:msg=>sent.push(msg)},chrome:{storage:{local:{get:async()=>({espnAnalysis:{team:{},league:{}},espnAnalysisUpdated:Date.now()})}}}};
  vm.runInNewContext(bridge,context);await new Promise(resolve=>setImmediate(resolve));assert.equal(sent.length,0);
  context.location.search='?espn_sync=1';vm.runInNewContext(bridge,context);await new Promise(resolve=>setImmediate(resolve));assert.equal(sent.length,1);
  context.chrome.storage.local.get=async()=>({espnAnalysis:{team:{},league:{}},espnAnalysisUpdated:Date.now()-3600000});
  vm.runInNewContext(bridge,context);await new Promise(resolve=>setImmediate(resolve));assert.equal(sent.length,1);
  console.log('PASS: ESPN direct league fetch, ID validation, intentional sync only and expired snapshot rejection');
})().catch(error=>{console.error(error);process.exit(1)});
