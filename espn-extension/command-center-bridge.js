
function publish(){
  chrome.storage.local.get(["espnAnalysis","espnAnalysisUpdated"]).then(data=>{
    if(!data.espnAnalysis)return;
    const age=Date.now()-(data.espnAnalysisUpdated||0);
    if(age>7*24*60*60*1000)return;
    window.postMessage({
      type:"FCC_ESPN_ANALYSIS",
      payload:data.espnAnalysis
    },"*");
  });
}
publish();
setTimeout(publish,600);
setTimeout(publish,1600);
