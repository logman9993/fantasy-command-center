// Only publish in the tab explicitly opened by the sync action.
if(new URLSearchParams(location.search).get("espn_sync")==="1"){
  const publish=async()=>{
    const data=await chrome.storage.local.get(["espnAnalysis","espnAnalysisUpdated"]);
    const age=Date.now()-Number(data.espnAnalysisUpdated||0);
    if(!data.espnAnalysis?.team || !data.espnAnalysis?.league || age<0 || age>10*60*1000)return;
    window.postMessage({type:"FCC_ESPN_ANALYSIS",payload:data.espnAnalysis,syncedAt:data.espnAnalysisUpdated},location.origin);
  };
  if(document.readyState==="complete")publish();
  else window.addEventListener("load",publish,{once:true});
}
