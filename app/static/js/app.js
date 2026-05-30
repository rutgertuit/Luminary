const App = (function() {
  /* ── State ── */
  let currentView = 'home';
  let selectedDepth = 'STANDARD';
  let activeJobs = {};       // {jobId: {query, depth, startTime, estimatedSeconds, phase, status, phaseTimings, researchStats}}
  let viewingJobId = null;   // Which job is shown in progress view
  let pollTimer = null;
  let elapsedTimer = null;
  let lastQuery = '';
  let lastDocId = '';
  let lastDocName = '';
  let agentsData = [];
  let activePrepJobId = '';   // job_id whose briefing is injected into calls (in-car prep)
  let historicalTimings = null;
  let pipelineRendered = false;
  let lastRenderedStats = {};

  const PHASE_ORDER = ['analysis', 'planning', 'studies', 'synthesis', 'claim_validation', 'evaluation', 'refinement', 'verification', 'strategic_analysis', 'qa', 'upload'];
  const PIPELINE_STEPS = [
    {id:'analysis', label:'Analyzing query', icon:'search'},
    {id:'planning', label:'Planning studies', icon:'psychology'},
    {id:'studies', label:'Researching studies', icon:'science'},
    {id:'synthesis', label:'Master synthesis', icon:'auto_awesome'},
    {id:'claim_validation', label:'Validating claims', icon:'gavel'},
    {id:'evaluation', label:'Quality evaluation', icon:'fact_check'},
    {id:'refinement', label:'Refining synthesis', icon:'refresh'},
    {id:'verification', label:'Verifying facts', icon:'verified'},
    {id:'strategic_analysis', label:'Strategic frameworks', icon:'analytics'},
    {id:'qa', label:'Anticipated Q&A', icon:'forum'},
  ];

  /* ── Helpers ── */
  function esc(s) { const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }
  function escAttr(s) { return (s||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function fmtTime(secs) {
    if (secs < 0) secs = 0;
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return m + ':' + String(s).padStart(2, '0');
  }
  function hasActiveJobs() { return Object.keys(activeJobs).length > 0; }

  /* ── View Navigation ── */
  function showView(name) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const el = document.getElementById('view-' + name);
    if (el) el.classList.add('active');
    currentView = name;

    document.querySelectorAll('.nav-btn').forEach(b => {
      const icon = b.querySelector('.material-icons');
      if (icon) { icon.classList.remove('text-primary'); icon.classList.add('text-slate-400'); }
    });
    const navBtn = document.querySelector(`.nav-btn[data-view="${name}"]`);
    if (navBtn) {
      const icon = navBtn.querySelector('.material-icons');
      if (icon) { icon.classList.remove('text-slate-400'); icon.classList.add('text-primary'); }
    }

    if (name === 'archive') loadArchive();
    if (name === 'chat') loadChatAgents();
    if (name === 'graph') loadGraph();
    if (name === 'watches') loadWatches();
    if (name === 'home') { loadStats(); renderBanners(); setHomeMode(homeMode); }
    renderActiveJobChip();
  }

  /* ── Bottom nav ── */
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => showView(btn.dataset.view));
  });

  /* ── Global Escape: close the topmost overlay ── */
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const active = (id) => document.getElementById(id).classList.contains('active');
    if (active('confirm-overlay')) return;                 // confirm handles its own Escape
    if (active('research-picker-overlay')) { closeResearchPicker(); return; }
    if (active('call-overlay')) { endCall(); return; }
  });

  /* ── Depth selector ── */
  document.querySelectorAll('.depth-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.depth-btn').forEach(b => {
        b.classList.remove('border-primary','text-primary','bg-primary/10');
        b.classList.add('border-slate-200','text-slate-400');
      });
      btn.classList.remove('border-slate-200','text-slate-400');
      btn.classList.add('border-primary','text-primary','bg-primary/10');
      selectedDepth = btn.dataset.depth;
      // Show/hide business context for STANDARD and DEEP
      const bcSection = document.getElementById('business-context-section');
      if (selectedDepth === 'QUICK') {
        bcSection.classList.add('hidden');
      } else {
        bcSection.classList.remove('hidden');
      }
    });
  });

  // Business context toggle
  document.getElementById('bc-toggle').addEventListener('click', () => {
    const fields = document.getElementById('bc-fields');
    fields.classList.toggle('hidden');
  });

  function getBusinessContext() {
    const role = document.getElementById('bc-role').value;
    const decision = document.getElementById('bc-decision').value;
    const industry = document.getElementById('bc-industry').value.trim();
    const stakeholders = document.getElementById('bc-stakeholders').value.trim();
    if (!role && !decision && !industry && !stakeholders) return null;
    return { user_role: role, decision_type: decision, industry, stakeholders };
  }

  /* ── ACTIVATE ── */
  const activateBtn = document.getElementById('activate-btn');
  const queryInput = document.getElementById('query-input');
  let suggestedQuery = '';
  let currentPlan = null;  // Holds the current research plan for review

  activateBtn.addEventListener('click', async () => {
    const query = queryInput.value.trim();
    if (!query) { queryInput.focus(); return; }

    activateBtn.disabled = true;
    lastQuery = query;

    try {
      // Generate a research plan first
      const bc = getBusinessContext();
      const payload = { query };
      if (selectedDepth) payload.preferred_depth = selectedDepth;
      if (bc) payload.business_context = bc;

      const planRes = await fetch('/api/research/plan', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      const plan = await planRes.json();
      if (!planRes.ok) throw new Error(plan.error || 'Failed to generate plan');

      currentPlan = plan;

      // Auto-proceed if the plan says so (typically QUICK research)
      if (plan.auto_proceed) {
        await executePlanDirect(plan);
      } else {
        renderPlan(plan);
        showView('plan');
      }
    } catch(e) {
      showToast('Failed to start: ' + e.message);
    } finally {
      activateBtn.disabled = false;
    }
  });

  function renderPlan(plan) {
    // Interpreted query
    document.getElementById('plan-query').value = plan.interpreted_query || plan.original_query;

    // Depth selector
    document.querySelectorAll('.plan-depth-btn').forEach(btn => {
      btn.classList.remove('border-primary','text-primary','bg-primary/10');
      btn.classList.add('border-slate-200','text-slate-400');
      if (btn.dataset.depth === plan.recommended_depth) {
        btn.classList.remove('border-slate-200','text-slate-400');
        btn.classList.add('border-primary','text-primary','bg-primary/10');
      }
    });
    document.getElementById('plan-depth-reason').textContent = plan.depth_reasoning || '';

    const estMins = Math.ceil((plan.estimated_duration || 300) / 60);
    document.getElementById('plan-estimate').textContent = `Estimated: ~${estMins} min`;

    // Clarifying questions
    const cqSection = document.getElementById('plan-clarifying-section');
    const cqList = document.getElementById('plan-clarifying-list');
    cqList.innerHTML = '';
    if (plan.clarifying_questions && plan.clarifying_questions.length > 0) {
      cqSection.classList.remove('hidden');
      plan.clarifying_questions.forEach((q, i) => {
        cqList.innerHTML += `
          <div class="flex flex-col gap-1">
            <div class="text-xs text-slate-600">${esc(q)}</div>
            <input type="text" class="plan-cq-answer text-xs rounded-lg border border-slate-200 bg-white/50 px-3 py-1.5 text-slate-600 placeholder-slate-300 focus:border-primary focus:ring-1 focus:ring-primary/30"
                   data-idx="${i}" placeholder="Your answer (optional)">
          </div>`;
      });
    } else {
      cqSection.classList.add('hidden');
    }

    // Proposed studies (editable)
    renderPlanStudies(plan.proposed_studies || []);

    // Domains
    const domainsEl = document.getElementById('plan-domains');
    domainsEl.innerHTML = '';
    (plan.domains || []).forEach(d => {
      domainsEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">${esc(d)}</span>`;
    });
    if (plan.complexity) {
      const complexColors = { low: 'bg-green-50 text-green-500', medium: 'bg-amber-50 text-amber-500', high: 'bg-red-50 text-red-500' };
      domainsEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded-full ${complexColors[plan.complexity] || complexColors.medium}">${esc(plan.complexity)} complexity</span>`;
    }
    if (plan.needs_fact_checking) {
      domainsEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-500">fact-check</span>`;
    }
  }

  function renderPlanStudies(studies) {
    const studiesList = document.getElementById('plan-studies-list');
    studiesList.innerHTML = '';
    studies.forEach((study, i) => {
      const questionsHtml = (study.questions || []).map((q, qi) => `
        <div class="flex items-center gap-1 group">
          <input type="text" class="plan-study-q flex-1 text-xs text-slate-500 bg-transparent border-b border-transparent hover:border-slate-200 focus:border-primary focus:ring-0 px-0 py-0.5"
                 data-study="${i}" data-qi="${qi}" value="${esc(q)}">
          <button onclick="App.removePlanQuestion(${i},${qi})" class="opacity-0 group-hover:opacity-100 text-slate-300 hover:text-red-400 transition-all" title="Remove question">
            <span class="material-icons text-xs">close</span>
          </button>
        </div>`).join('');

      studiesList.innerHTML += `
        <div class="plan-study-card p-3 rounded-lg bg-white/40 border border-slate-100 hover:border-primary/30 transition-colors" data-idx="${i}">
          <div class="flex items-start gap-2">
            <input type="checkbox" class="plan-study-toggle mt-1 rounded border-slate-300 text-primary focus:ring-primary/30" data-idx="${i}" checked>
            <div class="flex-1 min-w-0">
              <input type="text" class="plan-study-title w-full text-sm font-medium text-slate-700 bg-transparent border-b border-transparent hover:border-slate-200 focus:border-primary focus:ring-0 px-0 py-0"
                     data-study="${i}" value="${esc(study.title)}" placeholder="Study title">
              <input type="text" class="plan-study-angle w-full text-xs text-slate-400 bg-transparent border-b border-transparent hover:border-slate-200 focus:border-primary focus:ring-0 px-0 py-0 mt-0.5"
                     data-study="${i}" value="${esc(study.angle)}" placeholder="Research angle">
              <div class="mt-1.5 space-y-0.5">${questionsHtml}</div>
              <button onclick="App.addPlanQuestion(${i})" class="mt-1 text-[10px] text-primary/50 hover:text-primary flex items-center gap-0.5 transition-colors">
                <span class="material-icons text-xs">add</span> Add question
              </button>
            </div>
            <button onclick="App.removePlanStudy(${i})" class="text-slate-300 hover:text-red-400 transition-colors mt-1" title="Remove study">
              <span class="material-icons text-sm">delete_outline</span>
            </button>
          </div>
        </div>`;
    });
    document.getElementById('plan-study-count').textContent = `${studies.length} studies`;
  }

  // Wire plan depth buttons
  document.querySelectorAll('.plan-depth-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.plan-depth-btn').forEach(b => {
        b.classList.remove('border-primary','text-primary','bg-primary/10');
        b.classList.add('border-slate-200','text-slate-400');
      });
      btn.classList.remove('border-slate-200','text-slate-400');
      btn.classList.add('border-primary','text-primary','bg-primary/10');
      if (currentPlan) {
        currentPlan.recommended_depth = btn.dataset.depth;
        const durations = { QUICK: 90, STANDARD: 300, DEEP: 2400 };
        currentPlan.estimated_duration = durations[btn.dataset.depth] || 300;
        const estMins = Math.ceil(currentPlan.estimated_duration / 60);
        document.getElementById('plan-estimate').textContent = `Estimated: ~${estMins} min`;
      }
    });
  });

  // ── Plan study editing helpers ──

  function _syncStudiesFromDOM() {
    // Read all edited study values from DOM inputs back into currentPlan
    if (!currentPlan) return;
    const cards = document.querySelectorAll('.plan-study-card');
    const studies = [];
    cards.forEach((card, i) => {
      const toggle = card.querySelector('.plan-study-toggle');
      if (!toggle || !toggle.checked) return;
      const title = (card.querySelector('.plan-study-title') || {}).value || '';
      const angle = (card.querySelector('.plan-study-angle') || {}).value || '';
      const qInputs = card.querySelectorAll('.plan-study-q');
      const questions = [];
      qInputs.forEach(qi => { const v = qi.value.trim(); if (v) questions.push(v); });
      if (title.trim() || questions.length) {
        const orig = (currentPlan.proposed_studies || [])[i] || {};
        studies.push({ title: title.trim(), angle: angle.trim(), questions, recommended_role: orig.recommended_role || 'general' });
      }
    });
    currentPlan.proposed_studies = studies;
  }

  function addPlanStudy() {
    if (!currentPlan) return;
    _syncStudiesFromDOM();
    currentPlan.proposed_studies.push({ title: '', angle: '', questions: [''], recommended_role: 'general' });
    renderPlanStudies(currentPlan.proposed_studies);
    // Focus the new study title
    const titles = document.querySelectorAll('.plan-study-title');
    if (titles.length) titles[titles.length - 1].focus();
  }

  function removePlanStudy(idx) {
    if (!currentPlan) return;
    _syncStudiesFromDOM();
    // Re-read from all cards including unchecked for correct indexing
    const allStudies = [];
    document.querySelectorAll('.plan-study-card').forEach((card, i) => {
      const title = (card.querySelector('.plan-study-title') || {}).value || '';
      const angle = (card.querySelector('.plan-study-angle') || {}).value || '';
      const qInputs = card.querySelectorAll('.plan-study-q');
      const questions = [];
      qInputs.forEach(qi => { const v = qi.value.trim(); if (v) questions.push(v); });
      const orig = (currentPlan.proposed_studies || [])[i] || {};
      allStudies.push({ title: title.trim(), angle: angle.trim(), questions, recommended_role: orig.recommended_role || 'general' });
    });
    allStudies.splice(idx, 1);
    currentPlan.proposed_studies = allStudies;
    renderPlanStudies(currentPlan.proposed_studies);
  }

  function addPlanQuestion(studyIdx) {
    _syncStudiesFromDOM();
    // Read all studies from DOM for accurate state
    const allStudies = [];
    document.querySelectorAll('.plan-study-card').forEach((card) => {
      const title = (card.querySelector('.plan-study-title') || {}).value || '';
      const angle = (card.querySelector('.plan-study-angle') || {}).value || '';
      const qInputs = card.querySelectorAll('.plan-study-q');
      const questions = [];
      qInputs.forEach(qi => questions.push(qi.value));
      allStudies.push({ title, angle, questions, recommended_role: 'general' });
    });
    allStudies[studyIdx].questions.push('');
    currentPlan.proposed_studies = allStudies;
    renderPlanStudies(currentPlan.proposed_studies);
    // Focus the new question input
    const card = document.querySelectorAll('.plan-study-card')[studyIdx];
    if (card) {
      const qInputs = card.querySelectorAll('.plan-study-q');
      if (qInputs.length) qInputs[qInputs.length - 1].focus();
    }
  }

  function removePlanQuestion(studyIdx, qIdx) {
    const allStudies = [];
    document.querySelectorAll('.plan-study-card').forEach((card) => {
      const title = (card.querySelector('.plan-study-title') || {}).value || '';
      const angle = (card.querySelector('.plan-study-angle') || {}).value || '';
      const qInputs = card.querySelectorAll('.plan-study-q');
      const questions = [];
      qInputs.forEach(qi => questions.push(qi.value));
      allStudies.push({ title, angle, questions, recommended_role: 'general' });
    });
    allStudies[studyIdx].questions.splice(qIdx, 1);
    currentPlan.proposed_studies = allStudies;
    renderPlanStudies(currentPlan.proposed_studies);
  }

  async function executePlan() {
    if (!currentPlan) return;

    const btn = document.getElementById('plan-execute-btn');
    btn.disabled = true;
    btn.textContent = 'Starting...';

    try {
      // Collect user edits
      currentPlan.interpreted_query = document.getElementById('plan-query').value.trim() || currentPlan.original_query;

      // Collect selected depth from plan depth buttons
      const activeDepthBtn = document.querySelector('.plan-depth-btn.border-primary');
      if (activeDepthBtn) currentPlan.recommended_depth = activeDepthBtn.dataset.depth;

      // Sync all study edits from DOM
      _syncStudiesFromDOM();

      // Collect clarifying question answers and append to query context
      const cqAnswers = document.querySelectorAll('.plan-cq-answer');
      const answers = [];
      cqAnswers.forEach(input => {
        const val = input.value.trim();
        if (val) {
          const idx = parseInt(input.dataset.idx);
          const q = currentPlan.clarifying_questions[idx] || '';
          answers.push(`Q: ${q}\nA: ${val}`);
        }
      });
      if (answers.length > 0) {
        currentPlan.interpreted_query += '\n\nAdditional context:\n' + answers.join('\n');
      }

      await executePlanDirect(currentPlan);
    } catch (e) {
      showToast('Failed to start: ' + e.message);
      btn.disabled = false;
      btn.innerHTML = '<span class="material-icons text-sm align-middle mr-1">play_arrow</span> Start Research';
    }
  }

  async function executePlanDirect(plan) {
    const res = await fetch('/api/research/execute', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ plan })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Request failed');

    const jobId = data.job_id;
    const estSecs = data.estimated_seconds || 300;
    const now = Date.now();

    activeJobs[jobId] = {
      query: plan.interpreted_query || plan.original_query,
      depth: plan.recommended_depth,
      startTime: now,
      estimatedSeconds: estSecs, phase: 'Starting...', status: 'running',
      phaseTimings: {}, researchStats: {}, studyProgress: [], currentStep: '',
    };
    viewingJobId = jobId;
    persistActiveJobs();
    resetProgressView(now, estSecs);
    if (plan.recommended_depth === 'DEEP') fetchTimingEstimates();
    ensurePolling();
    showView('progress');
    queryInput.value = '';

    // Reset plan execute button
    const btn = document.getElementById('plan-execute-btn');
    btn.disabled = false;
    btn.innerHTML = '<span class="material-icons text-sm align-middle mr-1">play_arrow</span> Start Research';
  }

  async function cancelResearch() {
    if (!viewingJobId) return;
    const cancelBtn = document.getElementById('cancel-research-btn');
    cancelBtn.disabled = true;
    cancelBtn.textContent = 'Cancelling...';
    try {
      const res = await fetch(`/api/research/${viewingJobId}/cancel`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.error || 'Failed to cancel');
        cancelBtn.disabled = false;
        cancelBtn.innerHTML = '<span class="material-icons text-sm align-middle mr-1">stop</span> Cancel Research';
      }
      // Status polling will pick up the cancellation
    } catch(e) {
      showToast('Failed to cancel: ' + e.message);
      cancelBtn.disabled = false;
      cancelBtn.innerHTML = '<span class="material-icons text-sm align-middle mr-1">stop</span> Cancel Research';
    }
  }

  async function launchResearch(query) {
    const payload = { query, depth: selectedDepth };
    const bc = getBusinessContext();
    if (bc) payload.business_context = bc;
    const res = await fetch('/api/research', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Request failed');

    const jobId = data.job_id;
    const estSecs = data.estimated_seconds || 300;
    const now = Date.now();

    // Add to active jobs
    activeJobs[jobId] = {
      query, depth: selectedDepth, startTime: now,
      estimatedSeconds: estSecs, phase: 'Starting...', status: 'running',
      phaseTimings: {}, researchStats: {}, studyProgress: [], currentStep: '',
    };
    viewingJobId = jobId;
    persistActiveJobs();

    // Reset and prepare progress view
    resetProgressView(now, estSecs);

    if (selectedDepth === 'DEEP') fetchTimingEstimates();

    // Start polling if not already running
    ensurePolling();

    showView('progress');
    queryInput.value = '';
  }

  function resetProgressView(startMs, estSecs) {
    pipelineRendered = false;
    lastRenderedStats = {};
    document.getElementById('study-tracker').classList.add('hidden');
    document.getElementById('pipeline-steps').classList.add('hidden');
    document.getElementById('research-stats').classList.add('hidden');
    document.getElementById('parallel-cluster').classList.add('hidden');
    document.getElementById('study-list').innerHTML = '';
    document.getElementById('step-list').innerHTML = '';
    document.getElementById('phase-text').textContent = 'Starting...';
    document.getElementById('progress-bar').style.width = '0%';
    document.getElementById('progress-pct').textContent = '0%';
    // Reset cancel button
    const cancelBtn = document.getElementById('cancel-research-btn');
    cancelBtn.disabled = false;
    cancelBtn.innerHTML = '<span class="material-icons text-sm align-middle mr-1">stop</span> Cancel Research';
    document.getElementById('cancel-research-section').classList.remove('hidden');
    const start = new Date(startMs);
    const eta = new Date(startMs + estSecs * 1000);
    document.getElementById('progress-start').textContent = start.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',hour12:false});
    document.getElementById('progress-eta').textContent = eta.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',hour12:false});
  }

  function useSuggested() {
    if (suggestedQuery) { queryInput.value = suggestedQuery; lastQuery = suggestedQuery; }
    forceStart();
  }
  async function forceStart() {
    activateBtn.disabled = true;
    try { await launchResearch(lastQuery); }
    catch(e) { showToast('Failed to start: ' + e.message); showView('home'); }
    finally { activateBtn.disabled = false; }
  }
  queryInput.addEventListener('keydown', e => { if (e.key === 'Enter') activateBtn.click(); });

  /* ── localStorage persistence for active jobs ── */
  function persistActiveJobs() {
    const toSave = {};
    for (const [jid, j] of Object.entries(activeJobs)) {
      toSave[jid] = { query: j.query, depth: j.depth, startTime: j.startTime, estimatedSeconds: j.estimatedSeconds };
    }
    localStorage.setItem('activeJobs', JSON.stringify(toSave));
  }
  function removeActiveJob(jobId) {
    delete activeJobs[jobId];
    if (viewingJobId === jobId) viewingJobId = Object.keys(activeJobs)[0] || null;
    persistActiveJobs();
    renderBanners();
    if (!hasActiveJobs()) stopPolling();
  }

  /* ── Polling — shared timer for ALL active jobs ── */
  function ensurePolling() {
    if (pollTimer) return;
    updateTimers();
    elapsedTimer = setInterval(updateTimers, 1000);
    pollAllJobs();
    pollTimer = setInterval(pollAllJobs, 3000);
  }
  function stopPolling() {
    clearInterval(pollTimer); clearInterval(elapsedTimer);
    pollTimer = null; elapsedTimer = null;
  }

  async function fetchTimingEstimates() {
    try {
      const res = await fetch('/api/timing-estimates');
      if (res.ok) {
        historicalTimings = await res.json();
        if (historicalTimings.total_average > 0 && viewingJobId && activeJobs[viewingJobId]) {
          activeJobs[viewingJobId].estimatedSeconds = historicalTimings.total_average;
        }
      }
    } catch(e) { /* use default */ }
  }

  function computeSmartEstimate(job) {
    if (!historicalTimings || !historicalTimings.phase_averages || historicalTimings.sample_count === 0) {
      const elapsed = (Date.now() - job.startTime) / 1000;
      return Math.max(0, job.estimatedSeconds - elapsed);
    }
    const avgs = historicalTimings.phase_averages;
    const pt = job.phaseTimings || {};
    let remaining = 0, foundCurrent = false;
    for (const phase of PHASE_ORDER) {
      const avg = avgs[phase] || 0;
      const live = pt[phase];
      if (live && live.duration) continue;
      else if (live && live.start && !live.end) {
        foundCurrent = true;
        const spent = Date.now() / 1000 - live.start;
        remaining += Math.max(0, avg - spent);
      } else if (foundCurrent) {
        remaining += avg;
      }
    }
    return remaining;
  }

  function updateTimers() {
    if (!viewingJobId || !activeJobs[viewingJobId]) return;
    const job = activeJobs[viewingJobId];
    const elapsed = (Date.now() - job.startTime) / 1000;
    const remaining = computeSmartEstimate(job);
    const totalEst = elapsed + remaining;
    const pct = totalEst > 0 ? Math.min(99, (elapsed / totalEst) * 100) : 0;

    document.getElementById('elapsed').textContent = fmtTime(elapsed);
    document.getElementById('countdown').textContent = remaining > 0 ? fmtTime(remaining) : 'Any moment...';
    document.getElementById('progress-bar').style.width = pct.toFixed(1) + '%';
    document.getElementById('progress-pct').textContent = Math.floor(pct) + '%';
  }

  /* ── Poll all active jobs ── */
  let lastPhase = '';

  async function pollAllJobs() {
    const jobIds = Object.keys(activeJobs);
    if (!jobIds.length) return;

    for (const jobId of jobIds) {
      try {
        const res = await fetch('/api/status/' + jobId);
        if (!res.ok) {
          if (res.status === 404) {
            removeActiveJob(jobId);
            if (jobId === viewingJobId && currentView === 'progress') {
              document.getElementById('error-msg').textContent = 'Research session was lost (server restarted). Please start a new one.';
              document.getElementById('resume-btn').classList.add('hidden');
              showView('error');
            }
          }
          continue;
        }
        const data = await res.json();
        const job = activeJobs[jobId];
        if (!job) continue;

        job.phase = data.phase || 'Working...';
        job.status = data.status;
        if (data.phase_timings) job.phaseTimings = data.phase_timings;
        if (data.research_stats) job.researchStats = data.research_stats;
        if (data.study_progress) job.studyProgress = data.study_progress;
        if (data.current_step) job.currentStep = data.current_step;

        // Update progress view if this is the viewing job
        if (jobId === viewingJobId && currentView === 'progress') {
          document.getElementById('phase-text').textContent = job.phase;

          if (data.study_progress && data.study_progress.length) {
            renderStudyTracker(data.study_progress);
            renderParallelCluster(data.study_progress);
          }
          if (data.current_step) renderPipelineSteps(data.current_step);
          if (data.research_stats) renderResearchStats(data.research_stats, job.depth);

          // Mid-check
          const midIcon = document.getElementById('mid-check-icon');
          const midText = document.getElementById('mid-check-text');
          if (data.status === 'running') {
            if (job.phase !== lastPhase && lastPhase) {
              midText.textContent = 'Phase update: ' + job.phase;
            } else {
              midText.textContent = 'Pipeline running normally';
            }
            midIcon.className = 'w-2 h-2 rounded-full bg-primary animate-pulse';
          }
          lastPhase = job.phase;
        }

        // Handle completion / failure
        if (data.status === 'completed') {
          if (jobId === viewingJobId && currentView === 'progress') {
            document.getElementById('progress-bar').style.width = '100%';
            document.getElementById('progress-pct').textContent = '100%';
            document.getElementById('countdown').textContent = '0:00';
            lastDocId = data.elevenlabs_doc_id || '';
            lastDocName = 'Research: ' + (data.query||'').substring(0,60);
            document.getElementById('result-query').textContent = data.query;
            const link = document.getElementById('result-link');
            if (data.result_url) { link.href = data.result_url; link.style.display = 'block'; }
            else { link.style.display = 'none'; }
            renderResultAgents(true);
            renderNotebookLmSources(data.notebooklm_urls || []);
            setTimeout(() => showView('result'), 600);
          }
          removeActiveJob(jobId);
        } else if (data.status === 'cancelled') {
          if (jobId === viewingJobId && currentView === 'progress') {
            document.getElementById('error-msg').textContent = 'Research cancelled. Partial results may have been saved.';
            const resumeBtn = document.getElementById('resume-btn');
            resumeBtn.classList.add('hidden');
            if (data.result_url) {
              // Partial results were salvaged — show result view
              document.getElementById('result-query').textContent = data.query;
              const link = document.getElementById('result-link');
              link.href = data.result_url; link.style.display = 'block';
              renderResultAgents(true);
              setTimeout(() => showView('result'), 600);
            } else {
              setTimeout(() => showView('error'), 500);
            }
          }
          removeActiveJob(jobId);
        } else if (data.status === 'cancelling') {
          if (jobId === viewingJobId && currentView === 'progress') {
            document.getElementById('phase-text').textContent = 'Cancelling...';
          }
        } else if (data.status === 'failed' || data.status === 'lost') {
          if (jobId === viewingJobId && currentView === 'progress') {
            document.getElementById('error-msg').textContent = data.error || 'An unknown error occurred';
            // Show resume button for DEEP jobs or lost jobs with checkpoint
            const resumeBtn = document.getElementById('resume-btn');
            if (job.depth === 'DEEP' || data.has_checkpoint) {
              resumeBtn.classList.remove('hidden');
              resumeBtn.dataset.jobId = jobId;
            } else {
              resumeBtn.classList.add('hidden');
            }
            setTimeout(() => showView('error'), 1500);
          }
          removeActiveJob(jobId);
        }
      } catch(e) { /* keep polling */ }
    }

    // Update banners on home
    if (currentView === 'home') renderBanners();
  }

  /* ── Banners (multiple active jobs on home) ── */
  function renderBanners() {
    renderActiveJobChip();
    const container = document.getElementById('active-jobs-banners');
    if (!container) return;
    const entries = Object.entries(activeJobs).filter(([,j]) => j.status === 'running');
    if (!entries.length) { container.innerHTML = ''; return; }

    container.innerHTML = entries.map(([jid, j]) => {
      const elapsed = (Date.now() - j.startTime) / 1000;
      const remaining = computeSmartEstimate(j);
      const stats = j.researchStats || {};
      const pages = (stats.pages_read || 0) + (stats.news_articles || 0);
      const searches = (stats.web_searches || 0) + (stats.news_searches || 0) + (stats.grok_queries || 0);
      const statsText = searches > 0 ? ` · ${searches} searches · ${pages} pages` : '';
      return `<div class="glass-panel rounded-xl p-3 shadow-glass border border-primary/20 flex items-center gap-3 cursor-pointer"
                   onclick="App.viewJob('${esc(jid)}')">
        <div class="relative w-8 h-8 flex-shrink-0">
          <div class="absolute inset-0 border-2 border-slate-200 border-t-primary rounded-full" style="animation:spin 1.2s linear infinite"></div>
        </div>
        <div class="flex-1 min-w-0">
          <div class="text-xs font-semibold text-slate-700 truncate">${esc(j.query)}</div>
          <div class="text-[10px] text-slate-400">${esc(j.phase)}${statsText} · <span class="text-primary font-mono">${fmtTime(remaining)}</span> remaining</div>
        </div>
        <span class="material-icons text-primary text-lg">arrow_forward</span>
      </div>`;
    }).join('');
  }

  function viewJob(jobId) {
    if (!activeJobs[jobId]) return;
    viewingJobId = jobId;
    const job = activeJobs[jobId];
    resetProgressView(job.startTime, job.estimatedSeconds);
    showView('progress');
  }

  /* ── Persistent active-job chip (never strand a running job) ── */
  function firstRunningJobId() {
    const e = Object.entries(activeJobs).find(([, j]) => j.status === 'running');
    return e ? e[0] : '';
  }

  function renderActiveJobChip() {
    const chip = document.getElementById('active-job-chip');
    if (!chip) return;
    const jid = firstRunningJobId();
    if (!jid || currentView === 'progress') { chip.classList.add('hidden'); return; }
    const j = activeJobs[jid];
    const remaining = computeSmartEstimate(j);
    document.getElementById('active-job-chip-text').textContent =
      (j.query || 'Research') + ' · ' + fmtTime(remaining) + ' left';
    chip.classList.remove('hidden');
  }

  function viewActiveJob() {
    const jid = firstRunningJobId();
    if (jid) viewJob(jid);
  }

  /* ── Research Stats Display ── */
  function renderResearchStats(stats, depth) {
    if (!stats || typeof stats !== 'object') return;
    const container = document.getElementById('research-stats');
    const totalActivity = (stats.web_searches||0) + (stats.pages_read||0) + (stats.news_articles||0) + (stats.grok_queries||0) + (stats.reasoning_calls||0);
    if (totalActivity === 0) return;

    container.classList.remove('hidden');

    // Animate counter changes
    function setCounter(id, val) {
      const el = document.getElementById(id);
      if (!el) return;
      const old = parseInt(el.textContent) || 0;
      if (val !== old) {
        el.textContent = val;
        el.classList.remove('stat-flash');
        void el.offsetWidth; // trigger reflow
        el.classList.add('stat-flash');
      }
    }

    const searches = (stats.web_searches||0) + (stats.news_searches||0) + (stats.grok_queries||0);
    setCounter('stat-searches', searches);
    setCounter('stat-pages', stats.pages_read || 0);
    setCounter('stat-news', stats.news_articles || 0);
    setCounter('stat-ai', stats.reasoning_calls || 0);
    setCounter('stat-sources', stats.urls_fetched || 0);
    setCounter('stat-grok', stats.grok_queries || 0);

    // Human hours
    const hh = stats.human_hours;
    if (hh && hh.total_hours > 0) {
      document.getElementById('stat-human-hours').textContent = hh.total_hours.toFixed(1);
      const parts = [];
      if (hh.searching_min > 0) parts.push(`${Math.round(hh.searching_min/60*10)/10}h searching`);
      if (hh.reading_min > 0) parts.push(`${Math.round(hh.reading_min/60*10)/10}h reading`);
      if (hh.analyzing_min > 0) parts.push(`${Math.round(hh.analyzing_min/60*10)/10}h analyzing`);
      if (hh.writing_min > 0) parts.push(`${Math.round(hh.writing_min/60*10)/10}h writing`);
      document.getElementById('stat-hours-breakdown').textContent = parts.join(' · ');
    } else {
      // Compute approximate human hours from raw stats
      const searchMin = searches * 8;
      const readMin = (stats.pages_read||0) * 5 + (stats.news_articles||0) * 3;
      const analyzeMin = (stats.reasoning_calls||0) * 15;
      const total = searchMin + readMin + analyzeMin;
      if (total > 0) {
        document.getElementById('stat-human-hours').textContent = (total / 60).toFixed(1);
        document.getElementById('stat-hours-breakdown').textContent = 'Searching + reading + analysis equivalent';
      }
    }
  }

  /* ── Parallel Cluster Visualization ── */
  function renderParallelCluster(studyProgress) {
    if (!studyProgress || !studyProgress.length) return;
    const running = studyProgress.filter(s => s.status === 'running');
    const container = document.getElementById('parallel-cluster');
    const nodesEl = document.getElementById('cluster-nodes');
    const countEl = document.getElementById('cluster-count');

    if (running.length < 2) {
      container.classList.add('hidden');
      return;
    }

    container.classList.remove('hidden');
    countEl.textContent = running.length + ' parallel';

    nodesEl.innerHTML = studyProgress.map((s, i) => {
      let cls = 'pending';
      if (s.status === 'running') cls = 'active';
      else if (s.status === 'done') cls = 'done';
      else if (s.status === 'failed') cls = 'failed';
      const label = (s.title || 'Study '+(i+1)).substring(0, 30);
      const icon = cls === 'active' ? '<div class="inline-block w-3 h-3 border-2 border-slate-200 border-t-primary rounded-full mr-1 align-middle" style="animation:spin 0.8s linear infinite"></div>' :
                   cls === 'done' ? '<span class="material-icons text-xs align-middle mr-0.5">check</span>' :
                   cls === 'failed' ? '<span class="material-icons text-xs align-middle mr-0.5">close</span>' : '';
      return `<span class="cluster-node ${cls}">${icon}${esc(label)}</span>`;
    }).join('');
  }

  /* ── Study Tracker ── */
  function renderStudyTracker(studyProgress) {
    const tracker = document.getElementById('study-tracker');
    const list = document.getElementById('study-list');
    if (!studyProgress || !studyProgress.length) { tracker.classList.add('hidden'); return; }
    tracker.classList.remove('hidden');
    list.innerHTML = studyProgress.map((s, i) => {
      let statusIcon, textClass;
      if (s.status === 'done') {
        statusIcon = '<span class="material-icons text-emerald-500 text-sm">check_circle</span>';
        textClass = 'text-emerald-700';
      } else if (s.status === 'running') {
        statusIcon = '<div class="w-4 h-4 border-2 border-slate-200 border-t-primary rounded-full flex-shrink-0" style="animation:spin 1s linear infinite"></div>';
        textClass = 'text-slate-700 font-medium';
      } else if (s.status === 'failed') {
        statusIcon = '<span class="material-icons text-red-400 text-sm">error</span>';
        textClass = 'text-red-500';
      } else {
        statusIcon = '<span class="material-icons text-slate-300 text-sm">radio_button_unchecked</span>';
        textClass = 'text-slate-400';
      }
      return `<div class="flex items-center gap-2 px-1">${statusIcon}<span class="text-xs ${textClass} truncate">${s.title || 'Study '+(i+1)}</span></div>`;
    }).join('');
  }

  function normalizePipelineStep(step) {
    if (!step) return step;
    if (step.startsWith('study_')) return 'studies';
    if (step.startsWith('gap_study_')) return 'refinement';
    return step;
  }

  function renderPipelineSteps(currentStep) {
    const container = document.getElementById('pipeline-steps');
    const list = document.getElementById('step-list');
    const normalized = normalizePipelineStep(currentStep);
    if (!normalized && !pipelineRendered) return;
    container.classList.remove('hidden');
    pipelineRendered = true;
    const stepIdx = PIPELINE_STEPS.findIndex(s => s.id === normalized);
    list.innerHTML = PIPELINE_STEPS.map((s, i) => {
      let icon, textClass;
      if (i < stepIdx) { icon = `<span class="material-icons text-emerald-500 text-sm">check_circle</span>`; textClass = 'text-emerald-700'; }
      else if (i === stepIdx) { icon = `<div class="w-4 h-4 border-2 border-slate-200 border-t-primary rounded-full flex-shrink-0" style="animation:spin 1s linear infinite"></div>`; textClass = 'text-slate-700 font-medium'; }
      else { icon = `<span class="material-icons text-slate-300 text-sm">radio_button_unchecked</span>`; textClass = 'text-slate-400'; }
      return `<div class="flex items-center gap-2 px-1">${icon}<span class="material-icons ${textClass} text-sm">${s.icon}</span><span class="text-xs ${textClass}">${s.label}</span></div>`;
    }).join('');
  }

  /* ── Shared agent card renderer ── */
  function renderAgentCard(a, mode) {
    const docs = a.kb_docs || [];
    const kbHtml = docs.length
      ? docs.slice(0, 3).map(d => {
          const label = (d.name || d.id || '').replace(/^Research:\s*/i, '').substring(0, 50);
          return `<span class="kb-tag">${esc(label)}</span>`;
        }).join('') + (docs.length > 3 ? `<span class="kb-tag">+${docs.length - 3} more</span>` : '')
      : '<span class="text-[10px] text-slate-300 italic">No research loaded</span>';

    if (mode === 'chat' || mode === 'chat-pick') {
      // 'chat-pick' (Chat tab) prompts for research; 'chat' (result view) is
      // already scoped to the just-completed research via the active prep.
      const handler = mode === 'chat-pick' ? 'pickResearchThenCall' : 'startCall';
      return `<div class="agent-card agent-${esc(a.color)}" role="button" tabindex="0" aria-label="Talk to ${esc(a.name)}" onclick="App.${handler}('${esc(a.agent_id)}','${esc(a.name)}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();App.${handler}('${esc(a.agent_id)}','${esc(a.name)}')}">
        <div class="flex items-center gap-3 mb-2">
          <div class="w-10 h-10 rounded-full bg-white/80 shadow-inner-chrome flex items-center justify-center flex-shrink-0">
            <span class="material-icons agent-icon text-xl">${esc(a.icon)}</span>
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="font-semibold text-slate-700 text-sm">${esc(a.name)}</span>
              <span class="agent-dot"></span>
            </div>
            <div class="text-[11px] text-slate-400">${esc(a.subtitle)}</div>
          </div>
          <span class="material-icons text-slate-300 text-lg">chat</span>
        </div>
        <div class="flex flex-wrap gap-1 ml-[52px]">${kbHtml}</div>
      </div>`;
    }

    const cardId = 'agent-card-' + a.slug;
    return `<div id="${cardId}" class="agent-card agent-${esc(a.color)}">
      <div class="flex items-center gap-3 mb-2">
        <div class="w-10 h-10 rounded-full bg-white/80 shadow-inner-chrome flex items-center justify-center flex-shrink-0">
          <span class="material-icons agent-icon text-xl">${esc(a.icon)}</span>
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span class="font-semibold text-slate-700 text-sm">${esc(a.name)}</span>
            <span class="agent-dot"></span>
          </div>
          <div class="text-[11px] text-slate-400">${esc(a.subtitle)}</div>
        </div>
      </div>
      <div class="flex flex-wrap gap-1 ml-[52px] mb-2">${kbHtml}</div>
      <div id="${cardId}-actions" class="flex gap-2 ml-[52px]">
        <button onclick="App.assignToAgent('${esc(a.slug)}','${esc(a.agent_id)}','${esc(a.name)}')"
                class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold text-white bg-gradient-to-r from-primary to-cyan-400 hover:opacity-90 transition-opacity">
          <span class="material-icons text-sm">add_circle</span> Assign Research
        </button>
        <button onclick="App.startCall('${esc(a.agent_id)}','${esc(a.name)}')"
                class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-slate-500 border border-slate-200 hover:bg-slate-50 transition-colors">
          <span class="material-icons text-sm">chat</span> Chat
        </button>
      </div>
    </div>`;
  }

  /* ── Result: agent cards (chat mode primary) ── */
  async function renderResultAgents(fresh) {
    const container = document.getElementById('result-agents');
    const reassignContainer = document.getElementById('reassign-agents');
    try {
      const url = fresh ? '/api/agents?fresh=1' : '/api/agents';
      const res = await fetch(url);
      const data = await res.json();
      agentsData = data.agents || [];
      // Primary: chat cards
      container.innerHTML = agentsData.map(a => renderAgentCard(a, 'chat')).join('');
      // Secondary: attach cards in reassign panel
      if (reassignContainer && lastDocId) {
        reassignContainer.innerHTML = agentsData.map(a => renderAgentCard(a, 'attach')).join('');
      }
    } catch(e) {
      container.innerHTML = '<p class="text-xs text-red-400 text-center">Failed to load agents</p>';
    }
  }

  function toggleReassign() {
    const panel = document.getElementById('reassign-panel');
    const label = document.getElementById('reassign-toggle-label');
    if (panel.classList.contains('hidden')) {
      panel.classList.remove('hidden');
      label.textContent = 'Hide reassign';
    } else {
      panel.classList.add('hidden');
      label.textContent = 'Reassign to specific agent';
    }
  }

  /* ── Assign research to agent ── */
  async function assignToAgent(slug, agentId, agentName) {
    if (!agentId) { showToast('Agent not configured'); return; }
    const cardId = 'agent-card-' + slug;
    const actionsEl = document.getElementById(cardId + '-actions');
    if (!actionsEl) return;

    if (!lastDocId) {
      actionsEl.innerHTML = `<div class="flex items-center gap-2 text-[11px] text-amber-500"><span class="material-icons text-sm">warning</span> No research document available</div>`;
      return;
    }

    actionsEl.innerHTML = `<div class="flex items-center gap-2 text-[11px] text-slate-400">
      <div class="w-4 h-4 border-2 border-slate-200 border-t-primary rounded-full" style="animation:spin 0.8s linear infinite"></div>
      Assigning to ${esc(agentName)}...
    </div>`;

    try {
      const res = await fetch(`/api/agents/${slug}/attach`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ doc_id: lastDocId, doc_name: lastDocName })
      });
      const data = await res.json();
      if (res.ok) {
        actionsEl.innerHTML = `<div class="flex items-center gap-2 text-[11px] text-emerald-600 font-semibold">
          <span class="material-icons text-sm">check_circle</span> Assigned to ${esc(agentName)}!
        </div>`;
        // Start 5-min RAG countdown
        startReassignCountdown(agentId, agentName);
      } else {
        actionsEl.innerHTML = `<div class="flex items-center gap-2 text-[11px] text-red-500"><span class="material-icons text-sm">error</span> ${esc(data.error||'Failed')}</div>
        <button onclick="App.assignToAgent('${esc(slug)}','${esc(agentId)}','${esc(agentName)}')" class="text-[11px] text-slate-500 underline mt-1">Retry</button>`;
      }
    } catch(e) {
      actionsEl.innerHTML = `<div class="flex items-center gap-2 text-[11px] text-red-500"><span class="material-icons text-sm">error</span> Connection failed</div>
      <button onclick="App.assignToAgent('${esc(slug)}','${esc(agentId)}','${esc(agentName)}')" class="text-[11px] text-slate-500 underline mt-1">Retry</button>`;
    }
  }

  /* ── Reassign RAG countdown ── */
  let reassignTimer = null;

  function startReassignCountdown(agentId, agentName) {
    const endTime = Date.now() + 5 * 60 * 1000; // 5 minutes
    localStorage.setItem('reassignCountdown', JSON.stringify({ endTime, agentId, agentName }));
    const countdownEl = document.getElementById('reassign-countdown');
    const timerEl = document.getElementById('reassign-timer');
    if (countdownEl) countdownEl.classList.remove('hidden');

    // Disable chat cards during countdown
    document.querySelectorAll('#result-agents .agent-card').forEach(c => {
      c.style.opacity = '0.5';
      c.style.pointerEvents = 'none';
    });

    clearInterval(reassignTimer);
    reassignTimer = setInterval(() => {
      const remaining = Math.max(0, endTime - Date.now());
      if (remaining <= 0) {
        clearInterval(reassignTimer);
        reassignTimer = null;
        localStorage.removeItem('reassignCountdown');
        if (countdownEl) countdownEl.classList.add('hidden');
        // Re-enable chat cards
        document.querySelectorAll('#result-agents .agent-card').forEach(c => {
          c.style.opacity = '1';
          c.style.pointerEvents = 'auto';
        });
        return;
      }
      const m = Math.floor(remaining / 60000);
      const s = Math.floor((remaining % 60000) / 1000);
      if (timerEl) timerEl.textContent = m + ':' + String(s).padStart(2, '0');
    }, 1000);
  }

  // Restore countdown on page load
  function restoreReassignCountdown() {
    const saved = localStorage.getItem('reassignCountdown');
    if (!saved) return;
    try {
      const { endTime, agentId, agentName } = JSON.parse(saved);
      if (endTime > Date.now()) {
        startReassignCountdown(agentId, agentName);
      } else {
        localStorage.removeItem('reassignCountdown');
      }
    } catch(e) { localStorage.removeItem('reassignCountdown'); }
  }

  /* ── Chat view ── */
  /* ── Non-blocking toast (driving-safe; replaces alert on the in-car path) ── */
  let _toastTimer = null;
  function showToast(msg) {
    let t = document.getElementById('app-toast');
    if (!t) {
      t = document.createElement('div');
      t.id = 'app-toast';
      t.style.cssText = 'position:fixed;left:50%;bottom:88px;transform:translateX(-50%);z-index:60;'
        + 'background:rgba(15,23,42,0.92);color:#fff;padding:12px 18px;border-radius:14px;'
        + 'font-size:14px;max-width:90%;text-align:center;box-shadow:0 8px 24px rgba(0,0,0,.25);'
        + 'opacity:0;transition:opacity .2s;pointer-events:none;';
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.style.opacity = '1';
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { t.style.opacity = '0'; }, 2600);
  }

  /* ── Promise-based confirm dialog (replaces blocking confirm()) ── */
  function showConfirm(message) {
    return new Promise((resolve) => {
      const ov = document.getElementById('confirm-overlay');
      document.getElementById('confirm-message').textContent = message;
      const ok = document.getElementById('confirm-ok');
      const cancel = document.getElementById('confirm-cancel');
      const done = (val) => {
        ov.classList.remove('active');
        ok.onclick = null; cancel.onclick = null;
        document.onkeydown = _prevKeydown;
        resolve(val);
      };
      const _prevKeydown = document.onkeydown;
      document.onkeydown = (e) => { if (e.key === 'Escape') done(false); };
      ok.onclick = () => done(true);
      cancel.onclick = () => done(false);
      ov.classList.add('active');
      ok.focus();
    });
  }

  /* ── Research picker: choose which research to attach before a call ── */
  let pendingCallAgentId = '';
  let pendingCallAgentName = '';

  async function pickResearchThenCall(agentId, agentName) {
    if (!agentId) { showToast('Agent not configured'); return; }
    pendingCallAgentId = agentId;
    pendingCallAgentName = agentName || 'Agent';
    document.getElementById('picker-agent-name').textContent = pendingCallAgentName;
    const list = document.getElementById('picker-list');
    list.innerHTML = '<div class="flex justify-center py-10"><div class="w-6 h-6 border-2 border-slate-200 border-t-primary rounded-full" style="animation:spin 0.8s linear infinite"></div></div>';
    document.getElementById('research-picker-overlay').classList.add('active');
    try {
      const data = await fetch('/api/archive').then(r => r.ok ? r.json() : { results: [] });
      const done = (data.results || []).filter(r => (r.status || '') === 'completed' && r.job_id);
      if (!done.length) {
        list.innerHTML = '<div class="flex flex-col items-center justify-center py-16 text-slate-400"><span class="material-icons text-4xl mb-2 opacity-40">science</span><p class="text-sm">No completed research yet</p></div>';
        return;
      }
      // Current prep = active prep if still present, else the newest completed.
      const prep = done.find(r => r.job_id === activePrepJobId) || done[0];
      const others = done.filter(r => r.job_id !== prep.job_id);
      const itemRow = (r) => {
        const date = r.completed_at ? new Date(r.completed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';
        const depth = (r.depth || '').toUpperCase();
        return `<button onclick="App.chooseResearchForCall('${escAttr(r.job_id)}')"
          class="w-full text-left rounded-2xl bg-white/85 border border-white/70 shadow-inner-chrome px-4 py-4 active:scale-[0.98] transition-transform">
          <div class="text-base font-semibold text-slate-800 line-clamp-2">${esc(r.query || 'Untitled research')}</div>
          <div class="text-[11px] text-slate-500 mt-1">${esc(depth)}${depth && date ? ' · ' : ''}${date}</div>
        </button>`;
      };
      // One-tap default: a big primary button for the current prep, list as fallback.
      const primary = `<button onclick="App.chooseResearchForCall('${escAttr(prep.job_id)}')"
          class="w-full text-left rounded-2xl bg-gradient-to-r from-primary to-cyan-400 text-white shadow-lg px-5 py-5 active:scale-[0.98] transition-transform">
          <div class="text-[11px] uppercase tracking-widest opacity-90 mb-1">Talk about current prep</div>
          <div class="text-lg font-semibold leading-snug line-clamp-2">${esc(prep.query || 'Latest research')}</div>
        </button>`;
      const divider = others.length
        ? '<div class="text-[11px] uppercase tracking-wider text-slate-400 font-semibold pt-3 pb-1">Or choose another topic</div>'
        : '';
      list.innerHTML = primary + divider + others.map(itemRow).join('');
    } catch(e) {
      list.innerHTML = '<p class="text-sm text-red-400 text-center py-10">Failed to load research</p>';
    }
  }

  function chooseResearchForCall(jobId) {
    closeResearchPicker();
    startCall(pendingCallAgentId, pendingCallAgentName, jobId);
  }

  function closeResearchPicker() {
    document.getElementById('research-picker-overlay').classList.remove('active');
  }

  /* ── Mic permission pre-flight (grant at the desk, not mid-drive) ── */
  async function refreshMicButton() {
    const btn = document.getElementById('enable-mic-btn');
    if (!btn) return;
    try {
      if (navigator.permissions && navigator.permissions.query) {
        const st = await navigator.permissions.query({ name: 'microphone' });
        btn.classList.toggle('hidden', st.state === 'granted');
        return;
      }
    } catch(e) { /* permissions API or 'microphone' name unsupported */ }
    btn.classList.remove('hidden');  // safe default: offer it
  }

  async function enableMic() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach(t => t.stop());
      showToast("Microphone enabled — you're set for calls");
      document.getElementById('enable-mic-btn').classList.add('hidden');
    } catch(e) {
      showToast('Microphone permission denied');
    }
  }

  /* ── Home mode: Talk (in-car prep + calls) vs Research (creation) ── */
  let homeMode = 'talk';
  function setHomeMode(mode) {
    homeMode = mode === 'research' ? 'research' : 'talk';
    const research = document.getElementById('home-research-section');
    const prep = document.getElementById('home-prep');
    const talkBtn = document.getElementById('home-mode-talk');
    const researchBtn = document.getElementById('home-mode-research');
    if (homeMode === 'research') {
      research.classList.remove('hidden');
      prep.classList.add('hidden');
    } else {
      research.classList.add('hidden');
      loadHomePrep();  // re-shows the prep card if agents exist
    }
    [talkBtn, researchBtn].forEach(b => { b.classList.remove('bg-primary', 'text-white'); b.classList.add('text-slate-500'); });
    const active = homeMode === 'research' ? researchBtn : talkBtn;
    active.classList.add('bg-primary', 'text-white');
    active.classList.remove('text-slate-500');
  }

  /* ── In-car home: active prep + one-tap agent calls ── */
  async function loadHomePrep() {
    const wrap = document.getElementById('home-prep');
    if (!wrap) return;
    try {
      const [prep, agentsRes] = await Promise.all([
        fetch('/api/active-prep').then(r => r.ok ? r.json() : {}).catch(() => ({})),
        fetch('/api/agents').then(r => r.ok ? r.json() : { agents: [] }).catch(() => ({ agents: [] })),
      ]);
      const agents = (agentsRes.agents || []).filter(a => a.agent_id);
      if (!agents.length) { wrap.classList.add('hidden'); return; }
      agentsData = agentsRes.agents || agentsData;
      activePrepJobId = prep.job_id || '';
      document.getElementById('home-prep-title').textContent = prep.title || 'No prep selected — newest research is used';
      const agentsEl = document.getElementById('home-prep-agents');
      agentsEl.innerHTML = agents.map(a => `
        <button onclick="App.pickResearchThenCall('${esc(a.agent_id)}','${esc(a.name)}')"
          class="agent-${esc(a.color)} flex flex-col items-center justify-center gap-1 min-h-[92px] rounded-2xl bg-white/85 border border-white/70 shadow-inner-chrome active:scale-95 transition-transform">
          <span class="material-icons agent-icon text-3xl">${esc(a.icon)}</span>
          <span class="text-sm font-semibold text-slate-700">${esc(a.name)}</span>
        </button>`).join('');
      wrap.classList.remove('hidden');
      refreshMicButton();
    } catch(e) {
      wrap.classList.add('hidden');
    }
  }

  async function setActivePrep(jobId, title) {
    try {
      const res = await fetch('/api/active-prep', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId }),
      });
      if (!res.ok) throw new Error('failed');
      activePrepJobId = jobId;
      showToast('Meeting prep set: ' + (title || jobId).substring(0, 40));
      loadHomePrep();
    } catch(e) {
      showToast('Could not set prep');
    }
  }

  async function loadChatAgents() {
    const container = document.getElementById('chat-agents');
    container.innerHTML = '<div class="flex justify-center py-8"><div class="w-6 h-6 border-2 border-slate-200 border-t-primary rounded-full" style="animation:spin 0.8s linear infinite"></div></div>';
    try {
      const res = await fetch('/api/agents');
      const data = await res.json();
      agentsData = data.agents || [];
      container.innerHTML = agentsData.map(a => renderAgentCard(a, 'chat-pick')).join('');
    } catch(e) {
      container.innerHTML = '<p class="text-sm text-red-400 text-center py-8">Failed to load agents</p>';
    }
  }

  /* ── Voice Call (ElevenLabs SDK) ── */
  let activeConversation = null;
  let callTimerInterval = null;
  let callStartTime = null;
  let currentCall = null;     // {agentId, agentName, jobId} — for reconnect
  let userEndedCall = false;  // distinguishes a user hang-up from a dropped call
  let micMuted = false;

  async function startCall(agentId, agentName, jobId) {
    if (!agentId) { showToast('Agent not configured'); return; }
    currentCall = { agentId, agentName, jobId };
    userEndedCall = false;
    micMuted = false;
    const agent = agentsData.find(a => a.agent_id === agentId) || {};
    const iconEl = document.getElementById('call-agent-icon');
    const colorMap = { cyan: '#0dccf2', amber: '#f59e0b', violet: '#8b5cf6', emerald: '#10b981' };
    iconEl.textContent = agent.icon || 'mic';
    iconEl.style.color = colorMap[agent.color] || '#0dccf2';
    document.getElementById('call-agent-name').textContent = agentName || 'Agent';
    document.getElementById('call-agent-subtitle').textContent = agent.subtitle || '';
    document.getElementById('call-status-dot').className = 'w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse';
    document.getElementById('call-status-text').textContent = 'Connecting...';
    document.getElementById('call-timer').classList.add('hidden');
    document.getElementById('call-audio-viz').classList.add('hidden');
    document.getElementById('call-pulse-ring').classList.add('hidden');
    document.getElementById('call-error').classList.add('hidden');
    document.getElementById('call-reconnect-btn').classList.add('hidden');
    document.getElementById('call-mute-btn').classList.add('hidden');
    document.getElementById('call-mute-icon').textContent = 'mic';
    document.getElementById('call-overlay').classList.add('active');

    // Resolve the active meeting prep and fetch its briefing for injection.
    let dynamicVariables = null;
    try {
      let pjid = jobId || activePrepJobId;
      if (!pjid) {
        const p = await fetch('/api/active-prep').then(r => r.ok ? r.json() : null).catch(() => null);
        pjid = (p && p.job_id) || '';
      }
      if (pjid) {
        const b = await fetch('/api/research/' + encodeURIComponent(pjid) + '/briefing')
          .then(r => r.ok ? r.json() : null).catch(() => null);
        if (b && b.executive_summary) {
          dynamicVariables = { current_research: b.executive_summary, research_index: b.index_markdown || '', research_title: b.title || '' };
          if (b.title) document.getElementById('call-agent-subtitle').textContent = 'Prep: ' + b.title.substring(0, 40);
        }
      }
    } catch(e) { /* injection is best-effort — never block the call */ }

    try {
      const { Conversation } = await import('https://cdn.jsdelivr.net/npm/@elevenlabs/client@0.14.0/+esm');
      const sessionOpts = {
        agentId,
        onConnect: () => {
          document.getElementById('call-status-dot').className = 'w-2.5 h-2.5 rounded-full bg-emerald-400';
          document.getElementById('call-status-text').textContent = 'Connected';
          document.getElementById('call-timer').classList.remove('hidden');
          document.getElementById('call-audio-viz').classList.remove('hidden');
          document.getElementById('call-pulse-ring').classList.remove('hidden');
          document.getElementById('call-reconnect-btn').classList.add('hidden');
          document.getElementById('call-error').classList.add('hidden');
          // Show mute only if the SDK build supports it (feature-detected).
          const canMute = activeConversation && typeof activeConversation.setMicMuted === 'function';
          document.getElementById('call-mute-btn').classList.toggle('hidden', !canMute);
          callStartTime = Date.now();
          callTimerInterval = setInterval(updateCallTimer, 1000);
        },
        onDisconnect: () => {
          document.getElementById('call-audio-viz').classList.add('hidden');
          document.getElementById('call-pulse-ring').classList.add('hidden');
          document.getElementById('call-mute-btn').classList.add('hidden');
          clearInterval(callTimerInterval);
          activeConversation = null;
          if (userEndedCall) {
            document.getElementById('call-status-dot').className = 'w-2.5 h-2.5 rounded-full bg-slate-300';
            document.getElementById('call-status-text').textContent = 'Call ended';
            setTimeout(() => document.getElementById('call-overlay').classList.remove('active'), 1200);
          } else {
            // Unexpected drop (common on cellular) — don't dead-end; offer reconnect.
            document.getElementById('call-status-dot').className = 'w-2.5 h-2.5 rounded-full bg-amber-400';
            document.getElementById('call-status-text').textContent = 'Connection lost — tap to reconnect';
            document.getElementById('call-reconnect-btn').classList.remove('hidden');
          }
        },
        onError: (error) => {
          console.error('Call error:', error);
          document.getElementById('call-status-dot').className = 'w-2.5 h-2.5 rounded-full bg-red-400';
          document.getElementById('call-status-text').textContent = 'Error';
          const errEl = document.getElementById('call-error');
          errEl.textContent = (error && error.message) || 'Connection failed';
          errEl.classList.remove('hidden');
          document.getElementById('call-audio-viz').classList.add('hidden');
          document.getElementById('call-reconnect-btn').classList.remove('hidden');
        },
      };
      if (dynamicVariables) sessionOpts.dynamicVariables = dynamicVariables;
      activeConversation = await Conversation.startSession(sessionOpts);
    } catch(e) {
      console.error('Failed to start call:', e);
      document.getElementById('call-status-dot').className = 'w-2.5 h-2.5 rounded-full bg-red-400';
      document.getElementById('call-status-text').textContent = 'Failed to connect';
      const errEl = document.getElementById('call-error');
      errEl.textContent = e.message || 'Could not load voice SDK';
      errEl.classList.remove('hidden');
      document.getElementById('call-reconnect-btn').classList.remove('hidden');
    }
  }

  function reconnectCall() {
    if (!currentCall) { closeCallOverlay(); return; }
    startCall(currentCall.agentId, currentCall.agentName, currentCall.jobId);
  }

  function toggleMute() {
    if (!activeConversation || typeof activeConversation.setMicMuted !== 'function') return;
    micMuted = !micMuted;
    try { activeConversation.setMicMuted(micMuted); } catch(e) { return; }
    document.getElementById('call-mute-icon').textContent = micMuted ? 'mic_off' : 'mic';
    document.getElementById('call-mute-btn').classList.toggle('bg-red-100', micMuted);
  }

  function closeCallOverlay() {
    document.getElementById('call-overlay').classList.remove('active');
  }

  function updateCallTimer() {
    if (!callStartTime) return;
    const secs = Math.floor((Date.now() - callStartTime) / 1000);
    document.getElementById('call-timer').textContent = Math.floor(secs/60) + ':' + String(secs%60).padStart(2,'0');
  }

  async function endCall() {
    userEndedCall = true;
    clearInterval(callTimerInterval);
    if (activeConversation) {
      try { await activeConversation.endSession(); } catch(e) { /* ignore */ }
      activeConversation = null;
    }
    document.getElementById('call-overlay').classList.remove('active');
  }

  /* ── Archive ── */
  let expandedArchiveId = null;
  let archiveCountdownTimers = {}; // { "jobId_slug": intervalId }

  async function loadArchive() {
    const container = document.getElementById('archive-list');
    container.innerHTML = '<div class="flex justify-center py-8"><div class="w-6 h-6 border-2 border-slate-200 border-t-primary rounded-full" style="animation:spin 0.8s linear infinite"></div></div>';
    try {
      const res = await fetch('/api/archive');
      const data = await res.json();
      const results = data.results || [];
      if (!results.length) {
        container.innerHTML = '<div class="flex flex-col items-center justify-center py-12 text-slate-400"><span class="material-icons text-4xl mb-2 opacity-40">science</span><p class="text-sm">No research yet</p></div>';
        return;
      }
      expandedArchiveId = null;
      // Store metadata in a lookup so we don't need to embed strings in onclick
      window._archiveMeta = {};
      container.innerHTML = results.map(r => {
        const date = r.completed_at ? new Date(r.completed_at).toLocaleDateString('en-US',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
        const studies = r.num_studies ? r.num_studies + ' studies' : '';
        const docId = r.elevenlabs_doc_id || '';
        const stats = r.research_stats || {};
        const hh = stats.human_hours;
        const hoursText = hh && hh.total_hours > 0 ? `≈${hh.total_hours}h of analyst work` : '';
        const jid = r.job_id || '';
        const nbUrls = r.notebooklm_urls || [];
        const isFailed = r.status === 'failed';
        const isInterrupted = r.status === 'interrupted';
        const isOrphaned = (r.status === 'running' && r.has_checkpoint) || isInterrupted;
        const isDeep = (r.depth || '').toUpperCase() === 'DEEP';
        window._archiveMeta[jid] = { docId, resultUrl: r.result_url || '', query: r.query || '', nbUrls };
        return `<div id="archive-item-${esc(jid)}" class="archive-item glass-panel rounded-xl shadow-glass border border-white/60" data-jid="${escAttr(jid)}" data-docid="${escAttr(docId)}">
          <div class="flex items-center gap-3 p-4 pb-2">
            <div class="flex-1 min-w-0">
              <h3 class="font-semibold text-sm text-slate-700 line-clamp-2">${esc(r.query||'Untitled')}</h3>
              <div class="flex flex-wrap gap-2 text-[11px] text-slate-400 mt-1">
                <span class="bg-primary/10 text-primary px-2 py-0.5 rounded-md font-semibold">${esc(r.depth||'')}</span>
                ${isFailed ? '<span class="bg-red-100 text-red-500 px-2 py-0.5 rounded-md font-semibold">Failed</span>' : ''}
                ${isOrphaned ? '<span class="bg-amber-100 text-amber-600 px-2 py-0.5 rounded-md font-semibold">Interrupted</span>' : ''}
                ${studies ? '<span>'+studies+'</span>' : ''}
                ${hoursText ? '<span class="text-emerald-600 font-medium">'+hoursText+'</span>' : ''}
                ${date ? '<span>'+date+'</span>' : ''}
              </div>
            </div>
            <span class="material-icons archive-chevron text-slate-300 text-lg flex-shrink-0">expand_more</span>
          </div>
          <div id="archive-detail-${esc(jid)}" class="archive-detail">
            <div class="flex flex-wrap items-center gap-2 mb-3">
              ${r.result_url ? `<button data-action="view-report" data-url="${escAttr(r.result_url)}" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold text-white bg-gradient-to-r from-primary to-cyan-400 hover:opacity-90 transition-opacity"><span class="material-icons text-sm">open_in_new</span>View Report</button>` : ''}
              ${r.result_url ? `<button data-action="copy-url" data-url="${escAttr(r.result_url)}" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-slate-500 border border-slate-200 hover:bg-slate-50 transition-colors"><span class="material-icons text-sm">content_copy</span>Copy URL</button>` : ''}
              <button data-action="amend" data-jid="${escAttr(jid)}" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-slate-500 border border-slate-200 hover:bg-amber-50 hover:text-amber-600 hover:border-amber-200 transition-colors"><span class="material-icons text-sm">edit</span>Amend</button>
              <button data-action="set-prep" data-jid="${escAttr(jid)}" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-slate-500 border border-slate-200 hover:bg-emerald-50 hover:text-emerald-600 hover:border-emerald-200 transition-colors"><span class="material-icons text-sm">directions_car</span>Set as prep</button>
              ${r.result_url ? `<button data-action="generate-podcast" data-jid="${escAttr(jid)}" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold text-white bg-gradient-to-r from-violet-500 to-purple-500 hover:opacity-90 transition-opacity"><span class="material-icons text-sm">podcasts</span>Podcast</button>` : ''}
              ${(isFailed && isDeep) || isOrphaned ? `<button data-action="resume" data-jid="${escAttr(jid)}" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold text-white bg-emerald-500 hover:bg-emerald-600 transition-colors"><span class="material-icons text-sm">replay</span>Resume</button>` : ''}
              <button data-action="delete" data-jid="${escAttr(jid)}" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-slate-500 border border-slate-200 hover:bg-red-50 hover:text-red-500 hover:border-red-200 transition-colors ml-auto"><span class="material-icons text-sm">delete_forever</span>Delete</button>
            </div>
            ${nbUrls.length ? `
            <div class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2 mt-1">NotebookLM Sources</div>
            <div class="mb-3 space-y-1">
              <button data-action="copy-all-nb" data-jid="${escAttr(jid)}" class="flex items-center gap-1 text-[11px] text-primary font-medium hover:underline mb-1"><span class="material-icons" style="font-size:14px">content_copy</span>Copy all URLs</button>
              ${nbUrls.map((u, i) => `<div class="flex items-center gap-2 text-[11px]">
                <span class="text-slate-400 truncate flex-1" title="${escAttr(u.url)}">${esc(u.label)}</span>
                <button data-action="copy-nb-url" data-url="${escAttr(u.url)}" class="flex items-center gap-0.5 text-slate-400 hover:text-primary transition-colors flex-shrink-0"><span class="material-icons" style="font-size:13px">content_copy</span></button>
              </div>`).join('')}
            </div>
            ` : ''}
            <div class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">Agents</div>
            <div id="archive-agents-${esc(jid)}" class="space-y-2">
              <div class="flex justify-center py-3"><div class="w-4 h-4 border-2 border-slate-200 border-t-primary rounded-full" style="animation:spin 0.8s linear infinite"></div></div>
            </div>
          </div>
        </div>`;
      }).join('');
      restoreArchiveCountdowns();
    } catch(e) {
      container.innerHTML = '<div class="flex flex-col items-center justify-center py-12 text-slate-400"><span class="material-icons text-4xl mb-2 opacity-40">cloud_off</span><p class="text-sm">Failed to load archive</p></div>';
    }
  }

  // Event delegation for archive list — handles all clicks
  document.addEventListener('click', function(event) {
    // Handle action buttons inside archive detail
    const actionBtn = event.target.closest('[data-action]');
    if (actionBtn && actionBtn.closest('#archive-list')) {
      event.stopPropagation();
      const action = actionBtn.dataset.action;
      if (action === 'view-report') {
        window.open(actionBtn.dataset.url, '_blank');
      } else if (action === 'copy-url') {
        navigator.clipboard.writeText(actionBtn.dataset.url);
        const icon = actionBtn.querySelector('.material-icons');
        icon.textContent = 'check';
        setTimeout(() => icon.textContent = 'content_copy', 1500);
      } else if (action === 'amend') {
        const jid = actionBtn.dataset.jid;
        const meta = (window._archiveMeta || {})[jid] || {};
        amendResearch(jid, (meta.query || '').substring(0, 120));
      } else if (action === 'set-prep') {
        const jid = actionBtn.dataset.jid;
        const meta = (window._archiveMeta || {})[jid] || {};
        setActivePrep(jid, meta.query || '');
      } else if (action === 'generate-podcast') {
        startPodcast(actionBtn.dataset.jid);
      } else if (action === 'resume') {
        resumeResearch(actionBtn.dataset.jid);
      } else if (action === 'delete') {
        deleteResearch(actionBtn.dataset.jid);
      } else if (action === 'copy-nb-url') {
        navigator.clipboard.writeText(actionBtn.dataset.url);
        const icon = actionBtn.querySelector('.material-icons');
        icon.textContent = 'check';
        setTimeout(() => icon.textContent = 'content_copy', 1500);
      } else if (action === 'copy-all-nb') {
        const jid = actionBtn.dataset.jid;
        const meta = (window._archiveMeta || {})[jid] || {};
        const allUrls = (meta.nbUrls || []).map(u => u.url).join('\n');
        navigator.clipboard.writeText(allUrls);
        const icon = actionBtn.querySelector('.material-icons');
        icon.textContent = 'check';
        setTimeout(() => icon.textContent = 'content_copy', 1500);
      }
      return;
    }

    // Handle archive item expand/collapse
    const archiveItem = event.target.closest('.archive-item');
    if (!archiveItem || !archiveItem.closest('#archive-list')) return;
    if (event.target.closest('button')) return;

    const jobId = archiveItem.dataset.jid;
    const docId = archiveItem.dataset.docid;
    if (!jobId) return;

    const detail = document.getElementById('archive-detail-' + jobId);
    if (!detail) return;

    const isExpanded = archiveItem.classList.contains('expanded');

    // Collapse any currently expanded item
    if (expandedArchiveId && expandedArchiveId !== jobId) {
      const prevItem = document.getElementById('archive-item-' + expandedArchiveId);
      const prevDetail = document.getElementById('archive-detail-' + expandedArchiveId);
      if (prevItem) prevItem.classList.remove('expanded');
      if (prevDetail) prevDetail.classList.remove('open');
    }

    if (isExpanded) {
      archiveItem.classList.remove('expanded');
      detail.classList.remove('open');
      expandedArchiveId = null;
    } else {
      archiveItem.classList.add('expanded');
      detail.classList.add('open');
      expandedArchiveId = jobId;
      loadArchiveAgents(jobId, docId);
    }
  });

  async function loadArchiveAgents(jobId, docId) {
    const container = document.getElementById('archive-agents-' + jobId);
    if (!container) return;
    container.innerHTML = '<div class="flex justify-center py-3"><div class="w-4 h-4 border-2 border-slate-200 border-t-primary rounded-full" style="animation:spin 0.8s linear infinite"></div></div>';
    try {
      const res = await fetch('/api/agents?fresh=1');
      const data = await res.json();
      const agents = data.agents || [];
      agentsData = agents;

      if (!docId) {
        container.innerHTML = '<div class="flex items-center gap-2 text-[11px] text-amber-500 py-2"><span class="material-icons text-sm">info</span>No KB document uploaded for this research</div>';
        return;
      }

      container.innerHTML = agents.map(a => {
        const isAssigned = (a.kb_docs || []).some(d => d.id === docId);
        const kbCount = (a.kb_docs || []).length;
        const colorMap = { cyan: '#0dccf2', amber: '#f59e0b', violet: '#8b5cf6', emerald: '#10b981' };
        const countdownKey = 'ragCountdown_' + jobId + '_' + a.slug;
        const hasCountdown = localStorage.getItem(countdownKey);
        let countdownActive = false;
        if (hasCountdown) {
          try { countdownActive = JSON.parse(hasCountdown).endTime > Date.now(); } catch(e) {}
        }

        return `<div id="archive-agent-${jobId}-${a.slug}" class="archive-agent-row" onclick="event.stopPropagation()">
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-full bg-white/80 shadow-inner-chrome flex items-center justify-center flex-shrink-0">
              <span class="material-icons text-lg" style="color:${colorMap[a.color]||'#0dccf2'}">${esc(a.icon)}</span>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="font-semibold text-slate-700 text-xs">${esc(a.name)}</span>
                ${isAssigned
                  ? '<span class="flex items-center gap-0.5 text-[10px] text-emerald-600 font-semibold"><span class="material-icons" style="font-size:12px">check_circle</span>Assigned</span>'
                  : '<span class="text-[10px] text-slate-400">Not assigned</span>'}
              </div>
              <div class="text-[10px] text-slate-400">KB: ${kbCount} doc${kbCount !== 1 ? 's' : ''}</div>
            </div>
            <div class="flex items-center gap-2">
              ${isAssigned ? `
                <button onclick="event.stopPropagation();App.archiveStartChat('${esc(a.agent_id)}','${esc(a.name)}','${jobId}','${esc(a.slug)}')"
                  id="archive-chat-btn-${jobId}-${a.slug}"
                  class="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-white bg-gradient-to-r from-primary to-cyan-400 hover:opacity-90 transition-opacity ${countdownActive ? 'opacity-50 pointer-events-none' : ''}"
                  ${countdownActive ? 'disabled' : ''}>
                  <span class="material-icons" style="font-size:14px">chat</span>Chat
                </button>
                <button onclick="event.stopPropagation();App.archiveUnassign('${jobId}','${esc(a.slug)}','${esc(a.agent_id)}','${esc(docId)}')"
                  class="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium text-slate-500 border border-slate-200 hover:bg-red-50 hover:text-red-500 hover:border-red-200 transition-colors">
                  <span class="material-icons" style="font-size:14px">link_off</span>Unassign
                </button>
              ` : `
                <button onclick="event.stopPropagation();App.archiveAssign('${jobId}','${esc(a.slug)}','${esc(a.agent_id)}','${esc(docId)}')"
                  id="archive-assign-btn-${jobId}-${a.slug}"
                  class="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-white bg-gradient-to-r from-primary to-cyan-400 hover:opacity-90 transition-opacity">
                  <span class="material-icons" style="font-size:14px">add_circle</span>Assign
                </button>
              `}
            </div>
          </div>
          <div id="archive-countdown-${jobId}-${a.slug}" class="${countdownActive ? 'archive-countdown mt-2 flex items-center gap-2 text-[11px] text-amber-600' : 'hidden'}">
            <span class="material-icons" style="font-size:14px">hourglass_top</span>
            RAG indexing — <span id="archive-timer-${jobId}-${a.slug}">5:00</span> remaining
          </div>
        </div>`;
      }).join('');

      // Restore any active countdowns for this job
      agents.forEach(a => {
        const countdownKey = 'ragCountdown_' + jobId + '_' + a.slug;
        const saved = localStorage.getItem(countdownKey);
        if (saved) {
          try {
            const { endTime } = JSON.parse(saved);
            if (endTime > Date.now()) {
              runArchiveCountdown(jobId, a.slug, endTime);
            } else {
              localStorage.removeItem(countdownKey);
            }
          } catch(e) { localStorage.removeItem(countdownKey); }
        }
      });
    } catch(e) {
      container.innerHTML = '<p class="text-xs text-red-400 text-center py-2">Failed to load agents</p>';
    }
  }

  async function archiveAssign(jobId, slug, agentId, docId) {
    const btn = document.getElementById('archive-assign-btn-' + jobId + '-' + slug);
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<div class="w-3 h-3 border-2 border-white/50 border-t-white rounded-full" style="animation:spin 0.8s linear infinite"></div> Assigning...';
    }
    try {
      const res = await fetch('/api/agents/' + slug + '/attach', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ doc_id: docId, doc_name: 'Research' })
      });
      const data = await res.json();
      if (res.ok) {
        // Start countdown
        const endTime = Date.now() + 5 * 60 * 1000;
        const countdownKey = 'ragCountdown_' + jobId + '_' + slug;
        localStorage.setItem(countdownKey, JSON.stringify({ endTime, agentId }));
        // Reload agent rows for this item
        loadArchiveAgents(jobId, docId);
      } else if (data.rag_not_ready) {
        // Show inline RAG indexing message — keep button disabled
        const row = document.getElementById('archive-agent-' + jobId + '-' + slug);
        if (row) {
          const cd = row.querySelector('[id^="archive-countdown-"]');
          if (cd) {
            cd.className = 'archive-countdown mt-2 flex items-center gap-2 text-[11px] text-amber-600';
            cd.innerHTML = '<span class="material-icons" style="font-size:14px">hourglass_top</span> Document still indexing at ElevenLabs. Try again in a few minutes.';
          }
        }
        if (btn) {
          btn.disabled = true;
          btn.classList.add('opacity-50');
          btn.innerHTML = '<span class="material-icons" style="font-size:14px">hourglass_top</span>Indexing...';
          // Re-enable after 60s so user can retry
          setTimeout(() => {
            btn.disabled = false;
            btn.classList.remove('opacity-50');
            btn.innerHTML = '<span class="material-icons" style="font-size:14px">add_circle</span>Retry';
          }, 60000);
        }
      } else {
        showToast(data.error || 'Failed to assign');
        if (btn) { btn.disabled = false; btn.innerHTML = '<span class="material-icons" style="font-size:14px">add_circle</span>Assign'; }
      }
    } catch(e) {
      showToast('Connection failed: ' + e.message);
      if (btn) { btn.disabled = false; btn.innerHTML = '<span class="material-icons" style="font-size:14px">add_circle</span>Assign'; }
    }
  }

  async function archiveUnassign(jobId, slug, agentId, docId) {
    if (!(await showConfirm('Unassign this research from ' + slug + '?'))) return;
    try {
      const res = await fetch('/api/agents/' + slug + '/kb/' + docId, { method: 'DELETE' });
      if (res.ok) {
        // Clear any countdown for this agent
        const countdownKey = 'ragCountdown_' + jobId + '_' + slug;
        localStorage.removeItem(countdownKey);
        if (archiveCountdownTimers[countdownKey]) {
          clearInterval(archiveCountdownTimers[countdownKey]);
          delete archiveCountdownTimers[countdownKey];
        }
        // Reload agent rows
        loadArchiveAgents(jobId, docId);
      } else {
        const data = await res.json();
        showToast(data.error || 'Failed to unassign');
      }
    } catch(e) {
      showToast('Connection failed: ' + e.message);
    }
  }

  function archiveStartChat(agentId, agentName, jobId, slug) {
    // Check if countdown is active
    const countdownKey = 'ragCountdown_' + jobId + '_' + slug;
    const saved = localStorage.getItem(countdownKey);
    if (saved) {
      try {
        const { endTime } = JSON.parse(saved);
        if (endTime > Date.now()) {
          showToast('RAG indexing is still in progress. Please wait for the countdown to finish.');
          return;
        }
      } catch(e) {}
    }
    startCall(agentId, agentName, jobId);
  }

  function runArchiveCountdown(jobId, slug, endTime) {
    const countdownKey = 'ragCountdown_' + jobId + '_' + slug;
    const countdownEl = document.getElementById('archive-countdown-' + jobId + '-' + slug);
    const timerEl = document.getElementById('archive-timer-' + jobId + '-' + slug);
    const chatBtn = document.getElementById('archive-chat-btn-' + jobId + '-' + slug);

    if (countdownEl) {
      countdownEl.className = 'archive-countdown mt-2 flex items-center gap-2 text-[11px] text-amber-600';
    }
    if (chatBtn) {
      chatBtn.classList.add('opacity-50', 'pointer-events-none');
      chatBtn.disabled = true;
    }

    // Clear any existing timer for this key
    if (archiveCountdownTimers[countdownKey]) {
      clearInterval(archiveCountdownTimers[countdownKey]);
    }

    archiveCountdownTimers[countdownKey] = setInterval(() => {
      const remaining = Math.max(0, endTime - Date.now());
      if (remaining <= 0) {
        clearInterval(archiveCountdownTimers[countdownKey]);
        delete archiveCountdownTimers[countdownKey];
        localStorage.removeItem(countdownKey);
        if (countdownEl) countdownEl.className = 'hidden';
        if (chatBtn) {
          chatBtn.classList.remove('opacity-50', 'pointer-events-none');
          chatBtn.disabled = false;
        }
        return;
      }
      const m = Math.floor(remaining / 60000);
      const s = Math.floor((remaining % 60000) / 1000);
      if (timerEl) timerEl.textContent = m + ':' + String(s).padStart(2, '0');
    }, 1000);
  }

  function restoreArchiveCountdowns() {
    // Scan localStorage for any active archive countdowns
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith('ragCountdown_')) {
        try {
          const { endTime } = JSON.parse(localStorage.getItem(key));
          if (endTime <= Date.now()) {
            localStorage.removeItem(key);
          }
          // Countdown will be restored when the item is expanded and agents are loaded
        } catch(e) { localStorage.removeItem(key); }
      }
    }
  }

  let amendJobId = '';

  function amendResearch(jobId, query) {
    amendJobId = jobId;
    document.getElementById('amend-original-query').textContent = query;
    document.getElementById('amend-questions').value = '';
    document.getElementById('amend-perspective').value = '';
    showView('amend');
  }

  async function submitAmendment() {
    const questions = document.getElementById('amend-questions').value.trim();
    const perspective = document.getElementById('amend-perspective').value.trim();
    if (!questions) { showToast('Please enter at least one question.'); return; }

    const btn = document.getElementById('amend-submit-btn');
    btn.disabled = true;
    btn.textContent = 'Starting...';

    try {
      const res = await fetch('/api/research/amend', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          job_id: amendJobId,
          additional_questions: questions,
          perspective: perspective,
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Request failed');

      const jobId = data.job_id;
      const now = Date.now();
      activeJobs[jobId] = {
        query: 'Amendment: ' + (document.getElementById('amend-original-query').textContent || '').substring(0, 80),
        depth: 'STANDARD',
        startTime: now,
        estimatedSeconds: data.estimated_seconds || 300,
        phase: 'Starting...', status: 'running',
        phaseTimings: {}, researchStats: {}, studyProgress: [], currentStep: '',
      };
      viewingJobId = jobId;
      persistActiveJobs();
      resetProgressView(now, data.estimated_seconds || 300);
      ensurePolling();
      showView('progress');
    } catch(e) {
      showToast('Failed to start amendment: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Run Amendment';
    }
  }

  async function deleteResearch(jobId) {
    if (!(await showConfirm('Delete this research? This will remove it from the archive and all agents.'))) return;
    try {
      const res = await fetch('/api/archive/' + jobId, { method: 'DELETE' });
      if (res.ok) {
        loadArchive(); // Refresh archive list
      } else {
        const data = await res.json();
        showToast(data.error || 'Failed to delete');
      }
    } catch(e) {
      showToast('Failed to delete: ' + e.message);
    }
  }

  // archiveChat removed — chat now starts directly from archive expand view via archiveStartChat

  function copyReportUrl() {
    const link = document.getElementById('result-link');
    const url = link ? link.href : '';
    if (!url || url === '#' || url.endsWith('#')) return;
    navigator.clipboard.writeText(url).then(() => {
      const btn = document.getElementById('copy-url-btn');
      const icon = btn.querySelector('.material-icons');
      icon.textContent = 'check';
      btn.classList.add('text-emerald-500', 'border-emerald-300');
      setTimeout(() => { icon.textContent = 'content_copy'; btn.classList.remove('text-emerald-500', 'border-emerald-300'); }, 2000);
    }).catch(() => prompt('Copy this URL:', url));
  }

  function renderNotebookLmSources(urls) {
    const section = document.getElementById('notebooklm-section');
    const list = document.getElementById('notebooklm-list');
    if (!urls || !urls.length) { section.classList.add('hidden'); return; }
    section.classList.remove('hidden');
    list.classList.add('hidden'); // start collapsed
    list.innerHTML = urls.map(s => `
      <div class="flex items-center gap-2 py-1.5 px-3 rounded-lg bg-white/50 border border-white/60">
        <span class="material-icons text-sm text-primary/60">description</span>
        <span class="flex-1 text-[11px] text-slate-600 truncate">${esc(s.label)}</span>
        <button onclick="navigator.clipboard.writeText('${esc(s.url)}');this.querySelector('.material-icons').textContent='check';setTimeout(()=>this.querySelector('.material-icons').textContent='content_copy',1500)"
                class="flex items-center gap-0.5 text-[10px] text-slate-400 hover:text-primary transition-colors" title="Copy URL">
          <span class="material-icons text-xs">content_copy</span>
        </button>
      </div>
    `).join('') + `
      <button onclick="copyAllNotebookLmUrls()" class="w-full mt-1 py-2 rounded-lg border border-dashed border-slate-200 text-[11px] text-slate-400 hover:text-primary hover:border-primary transition-colors flex items-center justify-center gap-1">
        <span class="material-icons text-sm">copy_all</span> Copy all URLs
      </button>`;
  }

  function copyAllNotebookLmUrls() {
    const items = document.querySelectorAll('#notebooklm-list .truncate');
    const section = document.getElementById('notebooklm-section');
    // Collect URLs from the copy buttons' onclick handlers
    const urls = [];
    document.querySelectorAll('#notebooklm-list button[title="Copy URL"]').forEach(btn => {
      const match = btn.getAttribute('onclick').match(/writeText\('([^']+)'\)/);
      if (match) urls.push(match[1]);
    });
    if (!urls.length) return;
    navigator.clipboard.writeText(urls.join('\n')).then(() => {
      const copyBtn = document.querySelector('#notebooklm-list button:last-child');
      if (copyBtn) { copyBtn.innerHTML = '<span class="material-icons text-sm text-emerald-500">check</span> Copied!'; setTimeout(() => { copyBtn.innerHTML = '<span class="material-icons text-sm">copy_all</span> Copy all URLs'; }, 2000); }
    });
  }

  /* ── Watches ── */
  async function loadWatches() {
    const list = document.getElementById('watches-list');
    list.innerHTML = '<div class="flex justify-center py-8"><div class="w-6 h-6 border-2 border-slate-200 border-t-primary rounded-full" style="animation:spin 0.8s linear infinite"></div></div>';
    try {
      const res = await fetch('/api/watches');
      const data = await res.json();
      const watches = data.watches || [];
      if (!watches.length) {
        list.innerHTML = '<div class="flex flex-col items-center justify-center py-12 text-slate-400"><span class="material-icons text-4xl mb-2 opacity-40">visibility</span><p class="text-sm">No watches yet</p></div>';
        return;
      }
      list.innerHTML = watches.map(w => {
        const lastChecked = w.last_checked ? new Date(w.last_checked).toLocaleDateString('en-US',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : 'Never';
        const lastChanged = w.last_changed ? new Date(w.last_changed).toLocaleDateString('en-US',{month:'short',day:'numeric'}) : '';
        const intervalLabel = w.interval_hours <= 6 ? 'Every 6h' : w.interval_hours <= 12 ? 'Every 12h' : w.interval_hours <= 24 ? 'Daily' : 'Weekly';
        return `<div class="glass-panel rounded-xl p-3 shadow-glass border border-white/60">
          <div class="flex items-start gap-2">
            <span class="material-icons text-primary text-lg mt-0.5">visibility</span>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium text-slate-700 truncate">${esc(w.query)}</div>
              <div class="flex flex-wrap gap-2 text-[10px] text-slate-400 mt-1">
                <span class="bg-primary/10 text-primary px-1.5 py-0.5 rounded">${intervalLabel}</span>
                <span>Last: ${lastChecked}</span>
                ${lastChanged ? `<span class="text-amber-500">Changed: ${lastChanged}</span>` : ''}
                <span>${w.history_count} checks</span>
              </div>
            </div>
          </div>
          <div class="flex items-center gap-2 mt-2 ml-7">
            <button onclick="App.checkWatch('${esc(w.id)}')" class="text-[11px] text-primary font-medium flex items-center gap-1 hover:underline"><span class="material-icons text-sm">refresh</span>Check now</button>
            <button onclick="App.deleteWatch('${esc(w.id)}')" class="text-[11px] text-slate-400 font-medium flex items-center gap-1 hover:text-red-500 transition-colors ml-auto"><span class="material-icons text-sm">delete</span></button>
          </div>
        </div>`;
      }).join('');
    } catch(e) {
      list.innerHTML = '<p class="text-sm text-red-400 text-center py-8">Failed to load watches</p>';
    }
  }

  async function createWatch() {
    const query = document.getElementById('watch-query').value.trim();
    const interval = document.getElementById('watch-interval').value;
    if (!query) { showToast('Please enter a topic to monitor.'); return; }
    const payload = { query, interval_hours: parseInt(interval) };
    const email = document.getElementById('watch-email').value.trim();
    const webhook = document.getElementById('watch-webhook').value.trim();
    if (email) payload.notification_email = email;
    if (webhook) payload.notification_webhook = webhook;
    try {
      const res = await fetch('/api/watches', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        document.getElementById('watch-query').value = '';
        document.getElementById('watch-email').value = '';
        document.getElementById('watch-webhook').value = '';
        loadWatches();
      } else {
        const data = await res.json();
        showToast(data.error || 'Failed to create watch');
      }
    } catch(e) {
      showToast('Failed: ' + e.message);
    }
  }

  async function checkWatch(watchId) {
    try {
      const res = await fetch('/api/watches/' + watchId + '/check', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        const msg = data.changed ? 'Changes detected!\n\n' + data.summary : 'No significant changes detected.';
        showToast(msg);
        loadWatches();
      } else {
        showToast(data.error || 'Check failed');
      }
    } catch(e) {
      showToast('Check failed: ' + e.message);
    }
  }

  async function deleteWatch(watchId) {
    if (!(await showConfirm('Delete this watch?'))) return;
    try {
      const res = await fetch('/api/watches/' + watchId, { method: 'DELETE' });
      if (res.ok) loadWatches();
    } catch(e) { showToast('Failed: ' + e.message); }
  }

  /* ── Knowledge Graph ── */
  let graphData = null;

  async function loadGraph() {
    const list = document.getElementById('graph-entities-list');
    list.innerHTML = '<div class="flex justify-center py-8"><div class="w-6 h-6 border-2 border-slate-200 border-t-primary rounded-full" style="animation:spin 0.8s linear infinite"></div></div>';
    try {
      const res = await fetch('/api/graph');
      graphData = await res.json();
      document.getElementById('graph-entities-count').textContent = graphData.stats?.total_entities || 0;
      document.getElementById('graph-rels-count').textContent = graphData.stats?.total_relationships || 0;
      renderGraphEntities(graphData.entities || []);
    } catch(e) {
      list.innerHTML = '<p class="text-sm text-red-400 text-center py-8">Failed to load graph</p>';
    }
  }

  function renderGraphEntities(entities) {
    const list = document.getElementById('graph-entities-list');
    if (!entities.length) {
      list.innerHTML = '<div class="flex flex-col items-center justify-center py-12 text-slate-400"><span class="material-icons text-4xl mb-2 opacity-40">hub</span><p class="text-sm">No entities yet — complete some research first</p></div>';
      return;
    }
    const typeColors = {company:'primary',person:'amber-500',product:'emerald-500',concept:'violet-500',technology:'cyan-500',regulation:'rose-500',market:'indigo-500'};
    list.innerHTML = entities.map(e => {
      const color = typeColors[e.type] || 'slate-400';
      const rels = (graphData?.relationships || []).filter(r => r.from === e.name || r.to === e.name);
      const relText = rels.slice(0,3).map(r => {
        const other = r.from === e.name ? r.to : r.from;
        return `<span class="text-[10px] text-slate-400">${esc(r.type.replace('_',' '))} → ${esc(other)}</span>`;
      }).join(', ');
      return `<div class="glass-panel rounded-lg p-3 shadow-glass border border-white/60">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-${color}"></span>
          <span class="text-sm font-medium text-slate-700">${esc(e.name)}</span>
          <span class="text-[10px] bg-${color}/10 text-${color} px-1.5 py-0.5 rounded font-medium">${esc(e.type)}</span>
          <span class="text-[10px] text-slate-400 ml-auto">${e.mentions} mention${e.mentions !== 1 ? 's' : ''}</span>
        </div>
        ${relText ? `<div class="ml-4 mt-1 flex flex-wrap gap-1">${relText}</div>` : ''}
      </div>`;
    }).join('');
  }

  function filterGraph(query) {
    if (!graphData) return;
    const q = query.toLowerCase();
    const filtered = (graphData.entities || []).filter(e =>
      e.name.toLowerCase().includes(q) ||
      e.type.toLowerCase().includes(q) ||
      (e.aliases || []).some(a => a.toLowerCase().includes(q))
    );
    renderGraphEntities(filtered);
  }

  /* ── Stats ── */
  async function loadStats() {
    try {
      const res = await fetch('/api/stats');
      const data = await res.json();
      document.getElementById('stat-researching').textContent = String(data.researching||0).padStart(2,'0');
      document.getElementById('stat-completed').textContent = data.completed || 0;
    } catch(e) { /* silent */ }
    try {
      const res = await fetch('/api/agents');
      const data = await res.json();
      for (const a of (data.agents || [])) {
        const el = document.getElementById('kb-' + a.slug);
        if (el) el.textContent = String(a.kb_count).padStart(2, '0');
      }
    } catch(e) { /* silent */ }
  }

  function retry() { queryInput.value = lastQuery; showView('home'); }

  async function resumeResearch(jobId) {
    // Accept jobId param (from archive) or read from resume button dataset (from error view)
    if (!jobId) {
      const btn = document.getElementById('resume-btn');
      jobId = btn ? btn.dataset.jobId : null;
    }
    if (!jobId) return;
    try {
      const res = await fetch('/api/research/resume', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({job_id: jobId})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Resume failed');

      const estSecs = data.estimated_seconds || 2400;
      const now = Date.now();
      // Also try archive metadata for query
      const archiveMeta = (window._archiveMeta || {})[jobId] || {};
      activeJobs[jobId] = {
        query: data.query || archiveMeta.query || lastQuery || 'Resumed research', depth: 'DEEP',
        startTime: now, estimatedSeconds: estSecs,
        phase: 'Resuming from ' + (data.checkpoint_phase || 'checkpoint') + '...',
        status: 'running', phaseTimings: {}, researchStats: {},
        studyProgress: [], currentStep: '',
      };
      viewingJobId = jobId;
      persistActiveJobs();
      resetProgressView(now, estSecs);
      ensurePolling();
      showView('progress');
    } catch(e) {
      showToast('Failed to resume: ' + e.message);
    }
  }

  function resumeProgress() {
    if (viewingJobId && activeJobs[viewingJobId]) showView('progress');
  }

  /* ── Podcast ── */
  let podcastJobId = null;
  let podcastResearchJobId = null;
  let podcastSelectedStyle = null;
  let podcastPollTimer = null;
  let podcastHosts = [];
  let podcastStylesData = [];
  let podcastSelectedScenario = null;

  async function startPodcast(jobId) {
    podcastResearchJobId = jobId;
    podcastJobId = null;
    podcastSelectedStyle = null;
    podcastHosts = [];
    podcastStylesData = [];
    podcastSelectedScenario = null;
    const meta = (window._archiveMeta || {})[jobId] || {};
    document.getElementById('podcast-query').textContent = (meta.query || 'Research').substring(0, 120);

    // Reset visibility
    document.getElementById('podcast-loading').classList.remove('hidden');
    document.getElementById('podcast-styles').classList.add('hidden');
    document.getElementById('podcast-progress').classList.add('hidden');
    document.getElementById('podcast-player').classList.add('hidden');
    document.getElementById('podcast-error').classList.add('hidden');

    showView('podcast');

    try {
      const res = await fetch('/api/podcast/analyze', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({job_id: jobId})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Analysis failed');

      // Render angles checkboxes
      const angles = data.angles || [];
      const anglesSection = document.getElementById('podcast-angles-section');
      if (angles.length > 0) {
        const anglesContainer = document.getElementById('podcast-angle-cards');
        anglesContainer.innerHTML = angles.map((a, i) => `
          <label class="flex items-start gap-2.5 cursor-pointer glass-panel rounded-lg px-3 py-2.5 shadow-glass border border-white/60 hover:border-violet-200 transition-all">
            <input type="checkbox" name="podcast-angle" value="${escAttr(a.title)}" class="mt-0.5 accent-violet-500 flex-shrink-0">
            <div>
              <div class="text-[12px] font-semibold text-slate-700">${esc(a.title)}</div>
              <div class="text-[10px] text-slate-400 mt-0.5">${esc(a.description)}</div>
            </div>
          </label>
        `).join('');
        anglesSection.classList.remove('hidden');
      } else {
        anglesSection.classList.add('hidden');
      }

      // Render style cards
      podcastStylesData = data.styles || [];
      const container = document.getElementById('podcast-style-cards');
      container.innerHTML = podcastStylesData.map((s, i) => `
        <label class="podcast-style-card block cursor-pointer glass-panel rounded-xl p-4 shadow-glass border-2 transition-all ${i === 0 ? 'border-violet-400 bg-violet-50/40' : 'border-white/60 hover:border-violet-200'}">
          <input type="radio" name="podcast-style" value="${escAttr(s.id)}" class="hidden" ${i === 0 ? 'checked' : ''}>
          <div class="flex items-start gap-3">
            <span class="material-icons text-violet-400 mt-0.5">${s.id === 'executive' ? 'business_center' : s.id === 'debate' ? 'forum' : 'explore'}</span>
            <div>
              <div class="text-sm font-semibold text-slate-700">${esc(s.name)}</div>
              <div class="text-[11px] text-slate-500 mt-0.5">${esc(s.preview)}</div>
            </div>
          </div>
        </label>
      `).join('');

      if (podcastStylesData.length > 0) {
        podcastSelectedStyle = podcastStylesData[0].id;
        renderPodcastSuggestions(podcastSelectedStyle);
      }

      // Wire up radio buttons
      container.querySelectorAll('input[name="podcast-style"]').forEach(radio => {
        radio.addEventListener('change', function() {
          podcastSelectedStyle = this.value;
          podcastSelectedScenario = null;
          container.querySelectorAll('.podcast-style-card').forEach(card => {
            card.classList.remove('border-violet-400', 'bg-violet-50/40');
            card.classList.add('border-white/60');
          });
          this.closest('.podcast-style-card').classList.add('border-violet-400', 'bg-violet-50/40');
          this.closest('.podcast-style-card').classList.remove('border-white/60');
          renderPodcastSuggestions(this.value);
        });
      });

      // Render host selection dropdowns
      podcastHosts = data.hosts || [];
      const hostsSection = document.getElementById('podcast-hosts-section');
      if (podcastHosts.length >= 2) {
        const hostSelect = document.getElementById('podcast-host-select');
        const guestSelect = document.getElementById('podcast-guest-select');
        const optionsHtml = podcastHosts.map(h =>
          `<option value="${escAttr(h.slug)}">${esc(h.name)} — ${esc(h.subtitle)}</option>`
        ).join('');
        hostSelect.innerHTML = optionsHtml;
        guestSelect.innerHTML = optionsHtml;
        // Default: first two different agents
        hostSelect.selectedIndex = 0;
        guestSelect.selectedIndex = 1;
        hostsSection.classList.remove('hidden');
      } else {
        hostsSection.classList.add('hidden');
      }

      // Wire up language radio buttons
      document.querySelectorAll('input[name="podcast-lang"]').forEach(radio => {
        radio.addEventListener('change', function() {
          document.querySelectorAll('.podcast-lang-card').forEach(card => {
            card.classList.remove('border-violet-400', 'bg-violet-50/40');
            card.classList.add('border-white/60');
          });
          this.closest('.podcast-lang-card').classList.add('border-violet-400', 'bg-violet-50/40');
          this.closest('.podcast-lang-card').classList.remove('border-white/60');
        });
      });

      // Wire up duration radio buttons
      document.querySelectorAll('input[name="podcast-duration"]').forEach(radio => {
        radio.addEventListener('change', function() {
          document.querySelectorAll('.podcast-dur-card').forEach(card => {
            card.classList.remove('border-violet-400', 'bg-violet-50/40');
            card.classList.add('border-white/60');
          });
          this.closest('.podcast-dur-card').classList.add('border-violet-400', 'bg-violet-50/40');
          this.closest('.podcast-dur-card').classList.remove('border-white/60');
        });
      });

      document.getElementById('podcast-loading').classList.add('hidden');
      document.getElementById('podcast-styles').classList.remove('hidden');
    } catch(e) {
      document.getElementById('podcast-loading').classList.add('hidden');
      document.getElementById('podcast-error').classList.remove('hidden');
      document.getElementById('podcast-error-msg').textContent = e.message;
    }
  }

  function renderPodcastSuggestions(styleId) {
    const section = document.getElementById('podcast-suggestions-section');
    const cardsEl = document.getElementById('podcast-suggestion-cards');
    const styleData = podcastStylesData.find(s => s.id === styleId);
    const suggestions = (styleData && styleData.suggestions) || [];

    if (suggestions.length === 0) {
      section.classList.add('hidden');
      podcastSelectedScenario = null;
      return;
    }

    cardsEl.innerHTML = suggestions.map((sg, i) => `
      <label class="podcast-suggestion-card flex items-start gap-2.5 cursor-pointer glass-panel rounded-lg px-3 py-2.5 shadow-glass border-2 border-white/60 hover:border-violet-200 transition-all">
        <input type="radio" name="podcast-scenario" value="${i}" class="hidden">
        <div class="flex-1">
          <div class="text-[12px] font-semibold text-slate-700">${esc(sg.title)}</div>
          <div class="text-[10px] text-slate-400 mt-0.5">${esc(sg.description)}</div>
          <div class="flex gap-3 mt-1">
            <span class="text-[9px] text-violet-500 font-medium">${esc(sg.host_angle || '')}</span>
            <span class="text-[9px] text-slate-300">vs.</span>
            <span class="text-[9px] text-amber-600 font-medium">${esc(sg.guest_angle || '')}</span>
          </div>
        </div>
      </label>
    `).join('');

    // Wire up scenario radio buttons
    cardsEl.querySelectorAll('input[name="podcast-scenario"]').forEach(radio => {
      radio.addEventListener('change', function() {
        const idx = parseInt(this.value);
        podcastSelectedScenario = suggestions[idx] || null;
        cardsEl.querySelectorAll('.podcast-suggestion-card').forEach(card => {
          card.classList.remove('border-violet-400', 'bg-violet-50/30');
          card.classList.add('border-white/60');
        });
        this.closest('.podcast-suggestion-card').classList.add('border-violet-400', 'bg-violet-50/30');
        this.closest('.podcast-suggestion-card').classList.remove('border-white/60');
      });
    });

    // Allow deselect by clicking a selected card again
    cardsEl.querySelectorAll('.podcast-suggestion-card').forEach(card => {
      card.addEventListener('click', function(e) {
        const radio = this.querySelector('input[name="podcast-scenario"]');
        if (radio.checked && podcastSelectedScenario) {
          e.preventDefault();
          radio.checked = false;
          podcastSelectedScenario = null;
          this.classList.remove('border-violet-400', 'bg-violet-50/30');
          this.classList.add('border-white/60');
        }
      });
    });

    section.classList.remove('hidden');
  }

  async function submitPodcast() {
    if (!podcastResearchJobId || !podcastSelectedStyle) return;

    const btn = document.getElementById('podcast-generate-btn');
    btn.disabled = true;
    btn.textContent = 'Starting...';

    // Collect selected angles
    const selectedAngles = [];
    document.querySelectorAll('input[name="podcast-angle"]:checked').forEach(cb => {
      selectedAngles.push(cb.value);
    });

    // Collect host/guest selections
    const hostSelect = document.getElementById('podcast-host-select');
    const guestSelect = document.getElementById('podcast-guest-select');
    const hostSlug = hostSelect ? hostSelect.value : '';
    const guestSlug = guestSelect ? guestSelect.value : '';

    // Collect language and duration
    const langRadio = document.querySelector('input[name="podcast-lang"]:checked');
    const durRadio = document.querySelector('input[name="podcast-duration"]:checked');
    const language = langRadio ? langRadio.value : 'en';
    const duration = durRadio ? parseInt(durRadio.value) : 10;

    try {
      const res = await fetch('/api/podcast/generate', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          job_id: podcastResearchJobId,
          style: podcastSelectedStyle,
          host_slug: hostSlug,
          guest_slug: guestSlug,
          angles: selectedAngles,
          scenario: podcastSelectedScenario || null,
          language: language,
          duration: duration,
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to start');

      podcastJobId = data.podcast_job_id;
      document.getElementById('podcast-styles').classList.add('hidden');
      document.getElementById('podcast-progress').classList.remove('hidden');

      // Start polling
      pollPodcastStatus();
    } catch(e) {
      document.getElementById('podcast-error').classList.remove('hidden');
      document.getElementById('podcast-error-msg').textContent = e.message;
    } finally {
      btn.disabled = false;
      btn.textContent = 'Generate Podcast';
    }
  }

  function pollPodcastStatus() {
    if (podcastPollTimer) clearInterval(podcastPollTimer);
    podcastPollTimer = setInterval(async () => {
      if (!podcastJobId) { clearInterval(podcastPollTimer); return; }
      try {
        const res = await fetch('/api/podcast/status/' + podcastJobId);
        if (!res.ok) return;
        const data = await res.json();

        document.getElementById('podcast-phase').textContent = data.phase || data.status || '...';
        if (data.script_preview) {
          document.getElementById('podcast-script-preview').textContent = data.script_preview;
        }

        if (data.status === 'completed') {
          clearInterval(podcastPollTimer);
          document.getElementById('podcast-progress').classList.add('hidden');
          document.getElementById('podcast-player').classList.remove('hidden');

          const audioEl = document.getElementById('podcast-audio');
          const downloadEl = document.getElementById('podcast-download');
          const url = data.audio_url || '';
          if (url) {
            audioEl.src = url;
            downloadEl.href = url;
          }
        } else if (data.status === 'failed') {
          clearInterval(podcastPollTimer);
          document.getElementById('podcast-progress').classList.add('hidden');
          document.getElementById('podcast-error').classList.remove('hidden');
          document.getElementById('podcast-error-msg').textContent = data.error || 'Unknown error';
        }
      } catch(e) {
        // Ignore polling errors
      }
    }, 3000);
  }

  /* ── Init ── */
  // Honor the OS dark-mode preference.
  try {
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      document.body.classList.add('theme-dark');
    }
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (ev) => {
        document.body.classList.toggle('theme-dark', ev.matches);
      });
    }
  } catch(e) { /* matchMedia unsupported */ }
  loadStats();
  setHomeMode('talk');
  setInterval(loadStats, 30000);

  // Restore active jobs from localStorage
  (async function restoreActiveJobs() {
    const saved = localStorage.getItem('activeJobs');
    if (!saved) {
      // Migrate from old single-job format
      const oldSaved = localStorage.getItem('activeJob');
      if (oldSaved) {
        try {
          const old = JSON.parse(oldSaved);
          if (old.jobId) {
            const res = await fetch('/api/status/' + old.jobId);
            if (res.ok) {
              const data = await res.json();
              if (data.status === 'running') {
                activeJobs[old.jobId] = {
                  query: old.query || '', depth: old.depth || 'STANDARD',
                  startTime: old.startTime || Date.now(), estimatedSeconds: old.estimatedSeconds || 300,
                  phase: data.phase || '', status: 'running', phaseTimings: data.phase_timings || {},
                  researchStats: data.research_stats || {}, studyProgress: data.study_progress || [],
                  currentStep: data.current_step || '',
                };
                viewingJobId = old.jobId;
              }
            }
          }
        } catch(e) {}
        localStorage.removeItem('activeJob');
      }
      if (!hasActiveJobs()) return;
      persistActiveJobs();
      renderBanners();
      ensurePolling();
      return;
    }

    try {
      const jobs = JSON.parse(saved);
      for (const [jid, j] of Object.entries(jobs)) {
        try {
          const res = await fetch('/api/status/' + jid);
          if (!res.ok) continue;
          const data = await res.json();
          if (data.status === 'running') {
            activeJobs[jid] = {
              query: j.query || '', depth: j.depth || 'STANDARD',
              startTime: j.startTime || Date.now(), estimatedSeconds: j.estimatedSeconds || 300,
              phase: data.phase || '', status: 'running', phaseTimings: data.phase_timings || {},
              researchStats: data.research_stats || {}, studyProgress: data.study_progress || [],
              currentStep: data.current_step || '',
            };
            if (!viewingJobId) viewingJobId = jid;
          }
        } catch(e) {}
      }
      persistActiveJobs(); // Clean up completed jobs
      if (hasActiveJobs()) {
        renderBanners();
        ensurePolling();
      }
    } catch(e) {
      localStorage.removeItem('activeJobs');
    }
  })();

  /* ── Init reassign countdown ── */
  restoreReassignCountdown();

  /* ── Public API ── */
  return { showView, retry, resumeResearch, assignToAgent, startCall, endCall, copyReportUrl, useSuggested, forceStart, resumeProgress, viewJob, toggleReassign, deleteResearch, amendResearch, submitAmendment, filterGraph, createWatch, checkWatch, deleteWatch, archiveAssign, archiveUnassign, archiveStartChat, startPodcast, submitPodcast, executePlan, cancelResearch, addPlanStudy, removePlanStudy, addPlanQuestion, removePlanQuestion, setActivePrep, pickResearchThenCall, chooseResearchForCall, closeResearchPicker, reconnectCall, toggleMute, enableMic, viewActiveJob, setHomeMode };
})();
