/* V9 enhancements; the player ranking board remains the landing page. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let lastSnapshot = null;
  let privateKey = sessionStorage.getItem('fcc_workspace_key') || '';
  const safeRead = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };
  const nav = document.createElement('button');
  nav.className = 'navBtn'; nav.textContent = 'Decision Lab'; nav.dataset.target = 'decisions';
  nav.onclick = () => switchSection('decisions');
  document.querySelector('.mainNav').append(nav);
  const mobileNav = nav.cloneNode(true); mobileNav.className = '';
  mobileNav.onclick = () => switchSection('decisions');
  document.querySelector('.mobileNav').append(mobileNav);
  const section = document.createElement('section'); section.id = 'decisions'; section.className = 'section';
  section.innerHTML = `<div class="sectionHead"><div><div class="kicker">V9 beta · roster value</div><h2>Decision Lab</h2><p>Compare moves using your manual roster and starting slots from League HQ. Each move is an alternative. Verify league availability and player locks before acting.</p></div></div>
  <div class="v9grid"><div class="hqPanel"><h3>1. Your team & scoring</h3><p id="v9RosterSummary">Set up your team in League HQ first.</p><button class="btn light" id="v9Setup">Open team builder</button>
  <label class="v9label">Passing touchdown points<input id="v9PassTD" type="number" min="0" max="12" value="4"></label>
  <label class="v9label">Extra points per TE reception<input id="v9TE" type="number" min="0" max="3" step="0.25" value="0"></label>
  <p class="muted">Reception scoring follows the page selector. Other offensive scoring uses the displayed standard rules. This beta does not model custom defensive or kicker scoring.</p>
  <h3>2. Protect players from drops</h3><div id="v9Protected"></div><button class="btn" id="v9Evaluate">Evaluate lineup & available players</button></div>
  <div class="hqPanel"><h3>Trade comparison</h3><p>Build the other manager’s complete roster for a meaningful comparison. Equal-size trades are supported.</p>
  <label class="v9label">Find opponent players<input id="v9OpponentSearch" placeholder="Type a player name"></label><div id="v9OpponentSearchResults"></div>
  <div id="v9Opponent"></div><h4>Players you give</h4><div id="v9Give"></div><h4>Players you receive</h4><div id="v9Receive"></div><button class="btn light" id="v9Trade">Compare both teams</button></div></div>
  <div id="v9Status" role="status" aria-live="polite"></div><div id="v9Results"></div>
  <details class="hqPanel"><summary>Private workspace & tester feedback</summary><p>Your recovery key gives access to this workspace. Keep it private. Save before switching devices, then paste the same key and Load on the other device. Storage needs a persistent server disk.</p>
  <label class="v9label">Private recovery key<input id="v9Key" type="password" autocomplete="off" spellcheck="false"></label>
  <button class="btn light" id="v9NewKey">Create key</button> <button class="btn light" id="v9ShowKey">Show / hide key</button> <button class="btn light" id="v9Save">Save</button> <button class="btn light" id="v9Load">Load</button> <button class="btn light" id="v9Delete">Delete cloud copy</button>
  <label class="v9label">What looked wrong?<textarea id="v9Feedback" maxlength="2000" placeholder="Player, action, expected result, and what happened"></textarea></label><p>Submitting includes the last Decision Lab inputs and results, with no provider credentials.</p><button class="btn light" id="v9SendFeedback">Send feedback</button></details>`;
  $('players').parentElement.append(section);
  $('v9Key').value = privateKey;
  let opponent = safeRead('fcc_v9_opponent', []), protectedIds = safeRead('fcc_v9_protected', []);
  function syncSelections() {
    protectedIds = protectedIds.filter(id => manualRosterIds.includes(id));
    opponent = opponent.filter(id => !manualRosterIds.includes(id));
    $('v9RosterSummary').textContent = `${manualRosterIds.length} roster players · ${manualAvailableIds.length} marked available · scoring: ${$('scoring').value}`;
    const checks = (ids, type, selected = []) => ids.map(id => { const p = manualPlayer(id); return p ? `<label class="v9check"><input type="checkbox" data-v9="${type}" value="${esc(id)}" ${selected.includes(id) ? 'checked' : ''}>${esc(p.name)} · ${esc(p.position)}</label>` : ''; }).join('');
    $('v9Protected').innerHTML = checks(manualRosterIds, 'protect', protectedIds);
    $('v9Give').innerHTML = checks(manualRosterIds, 'give');
    $('v9Receive').innerHTML = checks(opponent, 'receive');
    $('v9Opponent').innerHTML = opponent.map(id => `<button class="v9chip" data-remove-opponent="${esc(id)}">${esc(manualPlayer(id)?.name || id)} ×</button>`).join('');
    localStorage.setItem('fcc_v9_opponent', JSON.stringify(opponent));
  }
  section.addEventListener('change', e => { if (e.target.dataset.v9 === 'protect') { protectedIds = [...section.querySelectorAll('[data-v9="protect"]:checked')].map(el => el.value); localStorage.setItem('fcc_v9_protected', JSON.stringify(protectedIds)); } });
  section.addEventListener('click', e => { const id = e.target.dataset.removeOpponent; if (id) { opponent = opponent.filter(p => p !== id); syncSelections(); } });
  $('v9Setup').onclick = async () => { switchSection('league'); if ($('manualBuilder').style.display === 'none') await openManualBuilder(); };
  const previousLists = renderManualLists;
  renderManualLists = function () { previousLists(); syncSelections(); };
  $('v9OpponentSearch').oninput = () => {
    const q = $('v9OpponentSearch').value.trim().toLowerCase();
    $('v9OpponentSearchResults').innerHTML = q.length < 2 ? '' : manualCatalog.filter(p => p.name.toLowerCase().includes(q) && !manualRosterIds.includes(String(p.id)) && !opponent.includes(String(p.id))).slice(0,8).map(p => `<button class="v9chip" data-opponent-add="${esc(p.id)}">+ ${esc(p.name)} · ${esc(p.position)}</button>`).join('');
  };
  $('v9OpponentSearchResults').onclick = e => { if (e.target.dataset.opponentAdd) { opponent.push(e.target.dataset.opponentAdd); syncSelections(); $('v9OpponentSearch').oninput(); } };
  function payload() {
    return { roster: manualRosterIds, available: manualAvailableIds, slots: manualSlots(), scoring: $('scoring').value,
      scoring_rules: { pass_yd: .04, pass_td: Number($('v9PassTD').value), pass_int: -2, rush_yd: .1, rush_td: 6, rec_yd: .1, rec_td: 6, rec: {PPR:1, HALF:.5, STD:0}[$('scoring').value], fum_lost:-2, pass_2pt:2, rush_2pt:2, rec_2pt:2, st_td:6, fgm:3, xpm:1, bonus_rec_te:Number($('v9TE').value) }, protected: protectedIds };
  }
  function lineupView(lineup) { return `<div class="v9lineup">${lineup.lineup.map(s => `<div><span>${esc(s.slot)}</span><b>${esc(s.player?.name || 'Empty slot')}</b><span>${s.player ? s.player.value : '—'}</span></div>`).join('')}</div>`; }
  async function evaluate(trade) {
    $('v9Status').textContent = 'Calculating roster impact…'; $('v9Evaluate').disabled = $('v9Trade').disabled = true;
    try {
      const input = payload();
      if (trade) Object.assign(input, {opponent, give:[...section.querySelectorAll('[data-v9="give"]:checked')].map(el => el.value), receive:[...section.querySelectorAll('[data-v9="receive"]:checked')].map(el => el.value)});
      if (trade && (!input.give.length || !input.receive.length)) throw new Error('Select at least one player on each side of the trade.');
      const d = await apiJSON('/api/v9/decisions', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(input), timeout:150000, retries:0});
      lastSnapshot = {input, result:d};
      $('v9Status').textContent = `Calculated ${new Date(d.generated_at * 1000).toLocaleString()} · historical production basis: ${d.basis_season}`;
      $('v9Results').innerHTML = `<div class="v9evidence"><b>What drives this result</b><p>${esc(d.evidence)}</p><details><summary>Scoring coefficients</summary><pre>${esc(JSON.stringify(d.scoring_rules,null,2))}</pre></details></div><div class="v9grid"><div class="hqPanel"><h3>Best model lineup · ${d.lineup.total} total value</h3>${lineupView(d.lineup)}</div><div class="hqPanel"><h3>Available-player alternatives</h3>${d.waivers.moves.map(m => `<details class="v9move"><summary>Add ${esc(m.add.name)} / drop ${esc(m.drop.name)} · +${m.delta} lineup value</summary><p>Before: ${d.waivers.before.total} → After: ${m.after.total}</p>${lineupView(m.after)}</details>`).join('') || '<p>No eligible move improves the starting lineup. Add known available players, review protected players, or keep your roster.</p>'}<p>${esc(d.waivers.note)}</p></div></div>${d.trade ? `<div class="hqPanel"><h3>Trade impact · model lineup value</h3><div class="v9grid">${[['You',d.trade.you],['Other manager',d.trade.opponent]].map(([title,t]) => `<div><h4>${title}: ${t.before.total} → ${t.after.total} (${t.delta > 0 ? '+' : ''}${t.delta})</h4>${lineupView(t.after)}</div>`).join('')}</div><p>${esc(d.trade.note)}</p></div>` : ''}`;
    } catch (e) { $('v9Status').textContent = e.message; } finally { $('v9Evaluate').disabled = $('v9Trade').disabled = false; }
  }
  $('v9Evaluate').onclick = () => evaluate(false); $('v9Trade').onclick = () => evaluate(true);
  async function workspace(method, state) {
    privateKey = $('v9Key').value.trim(); sessionStorage.setItem('fcc_workspace_key', privateKey);
    return apiJSON('/api/v9/workspace', {method, headers:{'Authorization':`Bearer ${privateKey}`, 'Content-Type':'application/json'}, ...(state ? {body:JSON.stringify(state)} : {}), retries:0});
  }
  const action = fn => async () => { try { await fn(); } catch(e) { $('v9Status').textContent = e.message; } };
  $('v9NewKey').onclick = () => { $('v9Key').value = [...crypto.getRandomValues(new Uint8Array(32))].map(b => b.toString(16).padStart(2,'0')).join(''); $('v9Status').textContent = 'New key created. Save your workspace, then copy the key somewhere private.'; };
  $('v9ShowKey').onclick = () => { $('v9Key').type = $('v9Key').type === 'password' ? 'text' : 'password'; };
  const localPersist = persistManual;
  persistManual = function () { localPersist(); const team = {...safeRead('fcc_manual_team',{}),scoring:$('scoring').value,pass_td:$('v9PassTD').value,te_premium:$('v9TE').value}; localStorage.setItem('fcc_manual_team',JSON.stringify(team)); };
  document.querySelectorAll('.manualSettings input,.manualSettings select').forEach(el => { el.removeEventListener('change',localPersist); el.addEventListener('change',persistManual); });
  $('v9PassTD').onchange = $('v9TE').onchange = persistManual;
  $('v9Save').onclick = action(async () => { persistManual(); await workspace('PUT', {version:9, team:safeRead('fcc_manual_team',{}), watch:watch(), protected:protectedIds, opponent}); $('v9Status').textContent = 'Workspace saved.'; });
  $('v9Load').onclick = action(async () => { const d = await workspace('GET'); if (!d.state) throw new Error('No workspace found for this key.');
    const s = d.state; if (!s.team || !Array.isArray(s.team.roster) || !Array.isArray(s.watch)) throw new Error('Saved workspace format is invalid.');
    localStorage.setItem('fcc_manual_team',JSON.stringify(s.team)); localStorage.setItem('fcc_watch',JSON.stringify(s.watch)); localStorage.setItem('fcc_v9_protected',JSON.stringify(s.protected || [])); localStorage.setItem('fcc_v9_opponent',JSON.stringify(s.opponent || [])); location.reload(); });
  $('v9Delete').onclick = action(async () => { if (!confirm('Delete the saved server workspace and its feedback? Your local roster remains.')) return; await workspace('DELETE'); $('v9Status').textContent = 'Cloud workspace and feedback deleted.'; });
  $('v9SendFeedback').onclick = action(async () => { privateKey = $('v9Key').value.trim(); const d = await apiJSON('/api/v9/feedback', {method:'POST', headers:{Authorization:`Bearer ${privateKey}`,'Content-Type':'application/json'}, body:JSON.stringify({message:$('v9Feedback').value, snapshot:lastSnapshot}), retries:0}); $('v9Status').textContent = `Feedback recorded: ${d.id}`; });
  // League-aware board filtering uses only explicitly supplied roster/availability.
  const filters = document.createElement('div'); filters.className = 'v9filters';
  filters.innerHTML = `<label>Roster view <select id="v9BoardFilter"><option value="all">All ranked players</option><option value="mine">My manual roster</option><option value="available">Marked available</option><option value="watch">Watchlist</option></select></label><span>Roster filters use League HQ’s manual team.</span>`;
  $('board').before(filters); $('v9BoardFilter').onchange = () => renderBoard();
  window.v9BoardMatch = p => { const f = $('v9BoardFilter').value; if(f === 'all') return true; if(f === 'watch') return isWatched(p.name); const ids = f === 'mine' ? manualRosterIds : manualAvailableIds; return ids.some(id => key(manualPlayer(id)?.name || '') === key(p.name)); };
  // Add a history explorer with accessible numeric chart labels.
  const history = document.createElement('details'); history.className = 'hqPanel';
  history.innerHTML = `<summary>Player usage history & comparison</summary><p>Choose two players from the loaded manual catalog. History shows actual regular-season results, with missing weeks left absent.</p><div class="v9filters"><input id="v9HistoryName" list="v9Names" placeholder="Player name"><input id="v9HistoryOther" list="v9Names" placeholder="Optional comparison player"><datalist id="v9Names"></datalist><label>Season <input id="v9HistorySeason" type="number" min="1999" placeholder="Latest available"></label><button class="btn light" id="v9HistoryLoad">Show history</button></div><div id="v9HistoryResult" class="v9grid"></div>`;
  $('players').append(history);
  history.ontoggle = async () => { if (!history.open) return; if (!manualCatalog.length) { try { manualCatalog = (await apiJSON(`/api/player-catalog?scoring=${$('scoring').value}`,{timeout:100000})).items || []; } catch(e) { $('v9HistoryResult').textContent = e.message; } } $('v9Names').innerHTML = manualCatalog.map(p => `<option value="${esc(p.name)}">${esc(p.position)}</option>`).join(''); };
  $('v9HistoryLoad').onclick = async () => {
    $('v9HistoryResult').textContent = 'Loading actual game results…';
    try { const names = [$('v9HistoryName').value, $('v9HistoryOther').value].filter(Boolean); if (!names.length) throw new Error('Choose a player.');
      const results = await Promise.all(names.map(async name => { const p = manualCatalog.find(x => x.name.toLowerCase() === name.toLowerCase()); if (!p) throw new Error(`Choose a catalog player: ${name}`); const q = new URLSearchParams({name:p.name,position:p.position,scoring:$('scoring').value}); if ($('v9HistorySeason').value) q.set('season',$('v9HistorySeason').value); return apiJSON(`/api/v9/profile?${q}`,{timeout:100000,retries:0}); }));
      const max = Math.max(1,...results.flatMap(d => d.weeks.map(w => Math.abs(w.points))));
      $('v9HistoryResult').innerHTML = results.map(d => `<div><h3>${esc(d.name)} · ${d.season}</h3>${d.weeks.length ? d.weeks.map(w => `<div class="v9bar"><span>W${w.week}</span><div style="width:${Math.abs(w.points)/max*55}%;background:${w.points<0?'#be4454':'#187f75'}"></div><b>${w.points} pts</b><small>${esc(w.targets ?? '—')} targets · ${esc(w.carries ?? '—')} carries</small></div>`).join('') : '<p>No regular-season player results available for this selection.</p>'}<p>${esc(d.note)} <a href="${esc(d.source_url)}" target="_blank" rel="noopener">Source data</a></p></div>`).join('');
    } catch(e) { $('v9HistoryResult').textContent = e.message; }
  };
  const savedTeam = safeRead('fcc_manual_team', null);
  if (savedTeam && Array.isArray(savedTeam.roster)) {
    if (['PPR','HALF','STD'].includes(savedTeam.scoring) && $('scoring').value !== savedTeam.scoring) { $('scoring').value = savedTeam.scoring; loadBoard(); }
    if (savedTeam.pass_td != null) $('v9PassTD').value = savedTeam.pass_td;
    if (savedTeam.te_premium != null) $('v9TE').value = savedTeam.te_premium;
    manualRosterIds = savedTeam.roster.map(String);
    manualAvailableIds = Array.isArray(savedTeam.available) ? savedTeam.available.map(String) : [];
    for (const [pos, count] of Object.entries(savedTeam.slots || {})) if ($('slot'+pos)) $('slot'+pos).value = count;
    if (savedTeam.team_name) $('manualTeamName').value = savedTeam.team_name;
    if (savedTeam.league_size) $('manualLeagueSize').value = savedTeam.league_size;
    apiJSON(`/api/player-catalog?scoring=${$('scoring').value}`, {timeout:100000,retries:0}).then(d => {
      manualCatalog = d.items || []; renderManualLists(); renderManualSearch(); renderBoard();
    }).catch(e => { $('v9Status').textContent = `Saved roster loaded; catalog unavailable: ${e.message}`; });
  }
  syncSelections();
})();
