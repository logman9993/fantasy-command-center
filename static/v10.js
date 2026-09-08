/* V10: roster capture and player comparisons. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const read = (k,f) => {try{return JSON.parse(localStorage.getItem(k))??f}catch{return f}};
  let catalogPromise=null, compareRun=0, ocrWorker=null, ocrRun=0, matchRun=0, defaultWeekSet=false;
  const initials = p => (p.name||p.team||'?').split(' ').map(w=>w[0]).slice(0,2).join('');
  window.playerPhoto = (p,large=false) => {const fb=`<span class="portraitFallback">${esc(initials(p))}</span>`;if(!p.photo)return `<span class="portrait ${large?'large':''}" aria-hidden="true">${fb}</span>`;return `<span class="portrait ${large?'large':''}" aria-hidden="true"><img src="${esc(p.photo)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.style.display='none';this.nextElementSibling.style.display='grid'"><span class="portraitFallback" style="display:none">${esc(initials(p))}</span></span>`};
  async function ensureCatalog() {
    if (!catalogPromise) catalogPromise=apiJSON(`/api/v10/catalog?scoring=${$('scoring').value}`,{timeout:120000,retries:0}).then(d=>{manualCatalog=d.items||[];if(!defaultWeekSet&&d.week){$('compareWeek').value=d.week;defaultWeekSet=true}return manualCatalog}).catch(e=>{catalogPromise=null;throw e});
    return catalogPromise;
  }
  const compareNav=document.createElement('button'); compareNav.className='navBtn';compareNav.dataset.target='compare';compareNav.textContent='Who Should I Start?';compareNav.onclick=()=>{switchSection('compare');prepareCompare()};document.querySelector('.mainNav').append(compareNav);
  const mobile=compareNav.cloneNode(true);mobile.className='';mobile.textContent='Compare';mobile.onclick=compareNav.onclick;document.querySelector('.mobileNav').append(mobile);
  const compare=document.createElement('section');compare.id='compare';compare.className='section';
  compare.innerHTML=`<div class="comparisonShell"><div class="compareHeader"><div><span class="eyebrow">PLAYER COMPARISON</span><h1>Who should I start?</h1><p>Two players. One lineup decision.</p></div><div class="compareOptions"><label>Scoring<select id="compareScoring"><option value="PPR">PPR</option><option value="HALF">Half PPR</option><option value="STD">Standard</option></select></label><label>Week<select id="compareWeek">${Array.from({length:18},(_,i)=>`<option>${i+1}</option>`).join('')}</select></label></div></div>
  <div class="comparePicker"><label>First player<input id="compareA" list="compareNames" placeholder="Search a player" autocomplete="off"></label><span class="vs">VS</span><label>Second player<input id="compareB" list="compareNames" placeholder="Search a player" autocomplete="off"></label><datalist id="compareNames"></datalist><button id="compareGo" class="btn orange">Compare players</button></div>
  <div id="compareMessage" class="compareMessage" role="status" aria-live="polite">Choose two players to compare stats and a start lean.</div><div id="compareHero" class="compareHero"></div>
  <div id="compareContent" hidden><div class="compareSubnav"><button data-view="overview" class="active">Overview</button><button data-view="stats">Stats</button><button data-view="logs">Game log</button><label>Historical season<select id="compareSeason"><option value="">Latest available</option></select></label></div><div id="compareAdvice" class="compareView"></div><div id="compareStats" class="compareView" hidden></div><div id="compareLogs" class="compareView" hidden></div></div></div>`;
  $('players').parentElement.append(compare);
  let selectedView='overview';
  function showView(view){selectedView=view;$('compareAdvice').hidden=view!=='overview';$('compareStats').hidden=view!=='stats';$('compareLogs').hidden=view!=='logs';compare.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view))}
  compare.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>showView(b.dataset.view));
  const playerLabel=p=>`${p.name} · ${p.team||'FA'} · ${p.position}`;
  async function prepareCompare(){
    $('compareScoring').value=$('scoring').value;
    try{const players=await ensureCatalog();$('compareNames').innerHTML=players.map(p=>`<option value="${esc(playerLabel(p))}"></option>`).join('');
      const old=$('compareSeason').value;const years=board?.meta?.stat_seasons||[];$('compareSeason').innerHTML='<option value="">Latest available</option>'+years.map(y=>`<option>${y}</option>`).join('');$('compareSeason').value=old;
    }catch(e){$('compareMessage').textContent=e.message}
  }
  const lookup=input=>manualCatalog.find(p=>playerLabel(p)===input)||manualCatalog.find(p=>p.name.toLowerCase()===input.toLowerCase());
  const fmt=n=>n==null?'—':Number(n).toLocaleString(undefined,{maximumFractionDigits:2});
  function statTable(title,fields,players){return `<div class="statGroup"><h3>${title}</h3><table><thead><tr><th>${esc(players[0].name)}</th><th scope="col">Statistic</th><th>${esc(players[1].name)}</th></tr></thead><tbody>${fields.map(([label,key,lower])=>{const a=key.startsWith('@')?players[0][key.slice(1)]:players[0].totals[key],b=key.startsWith('@')?players[1][key.slice(1)]:players[1].totals[key];return `<tr><td class="${a!=null&&b!=null&&(lower?a<b:a>b)?'better':''}">${fmt(a)}</td><th scope="row">${label}</th><td class="${a!=null&&b!=null&&(lower?b<a:b>a)?'better':''}">${fmt(b)}</td></tr>`}).join('')}</tbody></table></div>`}
  async function runComparison(){
    const run=++compareRun;$('compareMessage').textContent='Loading player history and checking the selected week…';$('compareGo').disabled=true;$('compareContent').hidden=true;$('compareHero').innerHTML='';
    try{await ensureCatalog();const a=lookup($('compareA').value.trim()),b=lookup($('compareB').value.trim());if(!a||!b)throw Error('Choose both names from the player list.');if(a.id===b.id)throw Error('Choose two different players.');
      const q=new URLSearchParams({a:a.id,b:b.id,scoring:$('compareScoring').value,week:$('compareWeek').value});if($('compareSeason').value)q.set('season',$('compareSeason').value);
      const d=await apiJSON(`/api/v10/compare?${q}`,{timeout:150000,retries:0});if(run!==compareRun)return;
      const players=d.players,rec=d.recommendation;
      $('compareMessage').textContent=`${d.season} · Week ${d.week} · ${d.scoring} · Start lean uses latest available games (${d.latest_stats_season}); historical stats shown: ${d.stats_season}. Checked ${new Date(d.checked_at*1000).toLocaleString()}`;
      $('compareHero').innerHTML=players.map(p=>`<article class="comparePlayer ${rec.player_id===p.id?'recommended':''}">${playerPhoto(p,true)}<div><span class="pickTag">${rec.player_id===p.id?'START LEAN':'COMPARE'}</span><h2>${esc(p.name)}</h2><p>${esc(p.position)} · ${esc(p.team)}</p><p>${esc(p.matchup.label)}</p>${p.injury_status?`<span class="injuryTag">${esc(p.injury_status)}</span>`:''}</div><div class="pointCircle"><b>${fmt(p.ppg)}</b><span>${d.stats_season}<br>actual PPG</span></div></article>`).join('');
      const winner=players.find(p=>p.id===rec.player_id);
      $('compareAdvice').innerHTML=`<div class="startAdvice"><span class="eyebrow">${esc(rec.label)}</span><h2>${winner?esc(winner.name):'Review the matchup before choosing'}</h2><ul>${rec.reasons.map(r=>`<li>${esc(r)}</li>`).join('')}</ul><p>${esc(rec.basis)}</p><div class="sourceLinks">${players.map(p=>`<a href="${esc(p.source_url)}" target="_blank" rel="noopener">${esc(p.name)} game data</a>`).join('')}<a href="https://github.com/nflverse/nfldata/blob/master/data/games.csv" target="_blank" rel="noopener">Schedule</a></div></div>`;
      const positions=players.map(p=>p.position);let groups=statTable(`${d.stats_season} regular season`,[['Fantasy points','@points'],['Points / game','@ppg'],['Games in dataset','@games'],['Last 4 available games PPG','@recent_ppg']],players);
      if(positions.includes('QB'))groups+=statTable('Passing',[['Completions','completions'],['Attempts','attempts'],['Completion %','completion_pct'],['Yards','passing_yards'],['Yards / attempt','yards_per_attempt'],['Touchdowns','passing_tds'],['Interceptions','passing_interceptions',true],['Sacks taken','sacks_suffered',true]],players);
      groups+=statTable('Rushing',[['Carries','carries'],['Yards','rushing_yards'],['Yards / carry','yards_per_carry'],['Touchdowns','rushing_tds']],players);
      if(positions.some(p=>['RB','WR','TE'].includes(p)))groups+=statTable('Receiving',[['Targets','targets'],['Receptions','receptions'],['Yards','receiving_yards'],['Touchdowns','receiving_tds']],players);
      if(positions.includes('K'))groups+=statTable('Kicking',[['Field goals made','field_goals_made'],['Extra points made','extra_points_made']],players);
      $('compareStats').innerHTML=groups+'<p class="tableNote">A dash means unavailable. Green marks the better historical total, not a forecast.</p>';
      const weeks=[...new Set(players.flatMap(p=>p.weeks.map(w=>w.week)))].sort((a,b)=>a-b);
      $('compareLogs').innerHTML=`<div class="statGroup"><h3>${d.stats_season} game log · actual fantasy points</h3><table><thead><tr><th>${esc(players[0].name)}</th><th>Week</th><th>${esc(players[1].name)}</th></tr></thead><tbody>${weeks.map(w=>`<tr><td>${fmt(players[0].weeks.find(r=>r.week===w)?.points)}</td><th>${w}</th><td>${fmt(players[1].weeks.find(r=>r.week===w)?.points)}</td></tr>`).join('')}</tbody></table>${weeks.length?'':'<p>No game rows were available for this selection.</p>'}</div><p class="tableNote">Missing weeks are not zero-point games.</p>`;
      $('compareContent').hidden=false;showView(selectedView);
    }catch(e){if(run===compareRun)$('compareMessage').textContent=e.message}finally{if(run===compareRun)$('compareGo').disabled=false}
  }
  $('compareGo').onclick=runComparison;$('compareSeason').onchange=runComparison;
  for(const id of ['compareA','compareB','compareWeek','compareScoring'])$(id).addEventListener('change',()=>{++compareRun;$('compareContent').hidden=true;$('compareHero').innerHTML='';$('compareGo').disabled=false;$('compareMessage').textContent='Selection changed. Compare again to update the recommendation.'});

  // Screenshot recognition stays in the browser; only recognized text is sent for matching.
  const upload=document.createElement('div');upload.className='screenshotImport';
  upload.innerHTML=`<div><span class="eyebrow">FAST TEAM SETUP</span><h3>Build your team from a screenshot</h3><p>Upload a clear roster screenshot, including bench and IR. Review the names, then add them to your team. Your image stays in this browser.</p></div><label class="uploadButton">Choose screenshot<input id="rosterImage" type="file" accept="image/png,image/jpeg,image/webp"></label><button id="ocrCancel" class="btn light" hidden>Cancel reading</button><div id="ocrStatus" role="status" aria-live="polite"></div><div id="ocrPreview"></div><details><summary>Review or paste recognized text</summary><textarea id="rosterText" maxlength="20000" placeholder="One player per line"></textarea><button id="matchRosterText" class="btn light">Match these names</button></details><div id="rosterMatches"></div><button id="applyRosterImage" class="btn orange" hidden>Add selected players to my team</button>`;
  $('manualBuilder').prepend(upload);
  let importChoices=[];
  function showMatches(data){
    importChoices=data.matches||[];
    $('rosterMatches').innerHTML=`<h4>Review detected players</h4><p>${esc(data.note)}</p>${importChoices.map(p=>`<label class="importChoice"><input type="checkbox" data-import-player value="${esc(p.id)}" checked>${playerPhoto(p)}<span><b>${esc(p.name)}</b> · ${esc(p.team)} · ${esc(p.position)}<small>${esc(p.recognized_line)}</small></span></label>`).join('')}${(data.review||[]).map((r,i)=>`<label class="reviewChoice"><span>${esc(r.line)}</span><select data-import-review><option value="">Skip / choose correct player</option>${r.choices.map(p=>`<option value="${esc(p.id)}">${esc(playerLabel(p))}</option>`).join('')}</select></label>`).join('')}`;
    $('applyRosterImage').hidden=!(data.matches?.length||data.review?.length);
    $('ocrStatus').textContent=`${data.matches?.length||0} full-name matches · ${data.review?.length||0} lines need review. Check every selection before adding.`;
  }
  async function matchText(){
    const ticket=++matchRun;
    const text=$('rosterText').value.trim();if(!text){$('ocrStatus').textContent='No text found. Try a sharper screenshot or type player names.';return}
    $('ocrStatus').textContent='Matching recognized names to the player catalog…';
    try{await ensureCatalog();const d=await apiJSON('/api/v10/roster-match',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text}),timeout:120000,retries:0});if(ticket===matchRun)showMatches(d)}catch(e){if(ticket===matchRun)$('ocrStatus').textContent=e.message}
  }
  $('matchRosterText').onclick=matchText;
  const originalOpen=openManualBuilder;
  $('manualOpen').removeEventListener('click',originalOpen);
  openManualBuilder=async()=>{
    const box=$('manualBuilder');box.style.display=box.style.display==='none'?'block':'none';if(box.style.display==='none')return;
    try{await ensureCatalog();renderManualLists();renderManualSearch()}catch(e){$('manualSearchResults').textContent=e.message}
  };
  $('manualOpen').addEventListener('click',openManualBuilder);
  async function loadOCR(){if(window.Tesseract)return;await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/static/ocr/tesseract.min.js';script.onload=resolve;script.onerror=()=>reject(Error('Image reader could not load. Paste roster text below to continue.'));document.head.append(script)})}
  $('rosterImage').onchange=async()=>{
    const run=++ocrRun,file=$('rosterImage').files[0];if(!file)return;
    $('rosterMatches').innerHTML='';$('applyRosterImage').hidden=true;$('rosterText').value='';
    if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>12*1024*1024){$('ocrStatus').textContent='Choose a PNG, JPEG or WebP image smaller than 12 MB.';return}
    let previewURL,worker;try{
      const bitmap=await createImageBitmap(file);if(bitmap.width*bitmap.height>24000000){bitmap.close();throw Error('Image is too large. Crop to the roster and try again.')};bitmap.close();
      previewURL=URL.createObjectURL(file);$('ocrPreview').innerHTML=`<img alt="Your roster screenshot preview">`;$('ocrPreview img')?.setAttribute('src',previewURL);
      $('ocrStatus').textContent='Loading the screenshot reader…';$('rosterImage').disabled=true;$('ocrCancel').hidden=false;await loadOCR();
      worker=await Tesseract.createWorker('eng',1,{workerPath:'/static/ocr/worker.min.js',corePath:'/static/ocr/core',langPath:'/static/ocr/lang',logger:m=>{if(run===ocrRun)$('ocrStatus').textContent=`Reading screenshot: ${m.status} ${Math.round((m.progress||0)*100)}%`}});
      if(run!==ocrRun)return;ocrWorker=worker;
      await worker.setParameters({tessedit_pageseg_mode:'11'});
      const result=await worker.recognize(file);if(run!==ocrRun)return;
      $('rosterText').value=result.data.text.slice(0,20000);await matchText();
    }catch(e){if(run===ocrRun)$('ocrStatus').textContent=`Could not read this image: ${e.message}. You can paste roster text below.`}finally{if(worker)await worker.terminate();if(ocrWorker===worker)ocrWorker=null;if(previewURL)URL.revokeObjectURL(previewURL);if(run===ocrRun){$('rosterImage').disabled=false;$('ocrCancel').hidden=true}}
  };
  $('ocrCancel').onclick=async()=>{++ocrRun;++matchRun;if(ocrWorker){await ocrWorker.terminate();ocrWorker=null}$('ocrStatus').textContent='Reading canceled. Your roster was not changed.';$('ocrCancel').hidden=true;$('rosterImage').disabled=false};
  $('rosterText').oninput=()=>{++matchRun;$('rosterMatches').innerHTML='';$('applyRosterImage').hidden=true};
  $('applyRosterImage').onclick=()=>{
    const ids=[...$('rosterMatches').querySelectorAll('[data-import-player]:checked,[data-import-review]')].map(el=>el.value).filter(Boolean);
    const valid=new Set(manualCatalog.map(p=>String(p.id)));const merged=[...new Set([...manualRosterIds,...ids.filter(id=>valid.has(id))])];
    if(merged.length>30){$('ocrStatus').textContent='This would exceed 30 players. Uncheck players who are not on your team.';return}
    manualRosterIds=merged;manualAvailableIds=manualAvailableIds.filter(id=>!merged.includes(id));persistManual();renderManualLists();renderManualSearch();
    $('ocrStatus').textContent=`Team now contains ${merged.length} players. Check starting slots and scoring, then click Grade this team.`;$('applyRosterImage').hidden=true;
  };
  window.renderTeamPriorities=d=>{
    const box=document.createElement('div');box.className='teamPriorities';
    box.innerHTML=`<div class="sectionHead"><div><span class="eyebrow">YOUR NEXT MOVES</span><h2>How to improve this team</h2><p>${esc(d.report_note||'')}</p></div></div><div class="priorityGrid">${(d.priorities||[]).map((p,i)=>`<article><span class="priorityNumber">${i+1}</span><h3>${esc(p.title)}</h3><p>${esc(p.why)}</p><div class="nextAction">${esc(p.action)}</div></article>`).join('')}</div>`;
    $('leagueAnalysis').prepend(box);
  };
  // Keep useful personal state in League HQ, without the former Decision Lab UI.
  const oldPersist=persistManual;
  persistManual=()=>{oldPersist();const team=read('fcc_manual_team',{});team.scoring=$('scoring').value;localStorage.setItem('fcc_manual_team',JSON.stringify(team))};
  document.querySelectorAll('.manualSettings input,.manualSettings select').forEach(el=>{el.removeEventListener('change',oldPersist);el.addEventListener('change',persistManual)});
  const saved=read('fcc_manual_team',null);if(saved&&Array.isArray(saved.roster)){
    if(['PPR','HALF','STD'].includes(saved.scoring)&&$('scoring').value!==saved.scoring){$('scoring').value=saved.scoring;loadBoard()}
    manualRosterIds=saved.roster.map(String);manualAvailableIds=(saved.available||[]).map(String);
    for(const [pos,count]of Object.entries(saved.slots||{}))if($('slot'+pos))$('slot'+pos).value=count;
    if(saved.team_name)$('manualTeamName').value=saved.team_name;if(saved.league_size)$('manualLeagueSize').value=saved.league_size;
    ensureCatalog().then(()=>{renderManualLists();renderManualSearch();renderBoard()}).catch(()=>{});
  }
  const filters=document.createElement('div');filters.className='v9filters';filters.innerHTML='<label>Roster view <select id="v10BoardFilter"><option value="all">All ranked players</option><option value="mine">My roster</option><option value="available">Marked available</option><option value="watch">Watchlist</option></select></label><span>All positions: top 25 each. Select a position: up to 100 real players.</span>';$('board').before(filters);$('v10BoardFilter').onchange=async()=>{try{await ensureCatalog();renderBoard()}catch(e){$('notice').textContent=e.message}};
  window.v9BoardMatch=p=>{const f=$('v10BoardFilter').value;if(f==='all')return true;if(f==='watch')return isWatched(p.name);return(f==='mine'?manualRosterIds:manualAvailableIds).some(id=>key(manualPlayer(id)?.name||'')===key(p.name))};
  $('scoring').addEventListener('change',()=>{catalogPromise=null;$('compareScoring').value=$('scoring').value;ensureCatalog().then(()=>{renderManualLists();renderManualSearch()}).catch(()=>{})});
})();
