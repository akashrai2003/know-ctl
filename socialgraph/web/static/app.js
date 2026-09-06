/* ══════════════════════════════════════════════════════════════════════════════
   Social Graph — Client-Side SPA Router & Page Renderers
   Hash-based routing, API calls, page transitions
   ══════════════════════════════════════════════════════════════════════════════ */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const app = () => $('#app');

/* ── Topic Colors ─────────────────────────────────────────────────────────── */
const TOPIC_COLORS = [
  '#6366f1', '#8b5cf6', '#a855f7', '#d946ef', '#ec4899',
  '#f43f5e', '#ef4444', '#f97316', '#f59e0b', '#eab308',
  '#84cc16', '#22c55e', '#10b981', '#14b8a6', '#06b6d4',
  '#0ea5e9', '#3b82f6', '#6366f1', '#8b5cf6',
];

let topicColorMap = {};

function assignTopicColors(topics) {
  topics.sort((a, b) => a.name.localeCompare(b.name));
  topics.forEach((t, i) => {
    topicColorMap[t.name] = TOPIC_COLORS[i % TOPIC_COLORS.length];
  });
}

function topicColor(name) {
  return topicColorMap[name] || '#6366f1';
}

/* ── API helpers ──────────────────────────────────────────────────────────── */
async function api(path, opts = {}) {
  const resp = await fetch(`/api${path}`, opts);
  return resp.json();
}

async function apiPost(path, body) {
  const resp = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return resp.json();
}

async function apiPut(path, body) {
  const resp = await fetch(`/api${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return resp.json();
}

function slug(text) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 80);
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function truncate(str, len = 120) {
  if (!str) return '';
  return str.length > len ? str.slice(0, len) + '…' : str;
}

function urnTail(urn) {
  return urn ? urn.split(':').pop() : '';
}

/* ── Loading ──────────────────────────────────────────────────────────────── */
function showLoading() {
  app().innerHTML = `<div class="loading-spinner"><div class="spinner"></div></div>`;
}

/* ── Toast Notifications ──────────────────────────────────────────────────── */
function showToast(message, type = 'info', duration = 4000) {
  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
  const container = $('#toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span class="toast-icon">${icons[type]}</span><span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('toast-out');
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

/* ── Pipeline indicator ───────────────────────────────────────────────────── */
let _pipelinePolling = null;

function updatePipelineIndicator(state) {
  const el = $('#pipeline-indicator');
  if (!el) return;
  if (state === 'running') {
    el.style.display = 'flex';
  } else {
    el.style.display = 'none';
    if (state === 'completed') showToast('Pipeline completed!', 'success');
    if (state === 'failed') showToast('Pipeline failed — check the Pipeline page.', 'error');
  }
}

function startPipelinePolling() {
  if (_pipelinePolling) return;
  _pipelinePolling = setInterval(async () => {
    try {
      const status = await api('/pipeline/status');
      updatePipelineIndicator(status.state);
      if (status.state !== 'running') {
        clearInterval(_pipelinePolling);
        _pipelinePolling = null;
      }
    } catch (_) {}
  }, 3000);
}

/* ── Router ───────────────────────────────────────────────────────────────── */
async function router() {
  const hash = location.hash || '#/';
  const parts = hash.slice(2).split('?');
  const path = parts[0] || '';
  const params = new URLSearchParams(parts[1] || '');

  $$('.navbar-links a').forEach(a => {
    const page = a.dataset.page;
    if (page === 'home' && path === '') a.classList.add('active');
    else if (page && path.startsWith(page)) a.classList.add('active');
    else a.classList.remove('active');
  });

  showLoading();

  try {
    if (path === '' || path === 'home') {
      await renderHome();
    } else if (path === 'topics') {
      await renderTopicsList();
    } else if (path.startsWith('topics/')) {
      await renderTopicDetail(path.replace('topics/', ''));
    } else if (path.startsWith('posts/')) {
      await renderPostDetail(decodeURIComponent(path.replace('posts/', '')));
    } else if (path === 'authors') {
      await renderAuthorsList();
    } else if (path.startsWith('authors/')) {
      await renderAuthorDetail(path.replace('authors/', ''));
    } else if (path === 'graph') {
      await renderGraphPage();
    } else if (path === 'search') {
      await renderSearchResults(params.get('q') || '', params.get('topic'));
    } else if (path === 'settings') {
      await renderSettingsPage();
    } else if (path === 'pipeline') {
      await renderPipelinePage();
    } else {
      app().innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><p>Page not found</p></div>`;
    }
  } catch (err) {
    console.error('Router error:', err);
    app().innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><p>Error loading page</p></div>`;
  }

  app().classList.remove('page-enter');
  void app().offsetWidth;
  app().classList.add('page-enter');
}

/* ── HOME ─────────────────────────────────────────────────────────────────── */
async function renderHome() {
  const [stats, topics] = await Promise.all([api('/stats'), api('/topics')]);
  assignTopicColors(topics);

  const statsHtml = `
    <div class="stats-row">
      <div class="card stat-card">
        <div class="stat-value">${stats.total_posts.toLocaleString()}</div>
        <div class="stat-label">Posts</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">${stats.total_topics}</div>
        <div class="stat-label">Topics</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">${stats.total_authors}</div>
        <div class="stat-label">Authors</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">${stats.total_embeddings.toLocaleString()}</div>
        <div class="stat-label">Embeddings</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">${stats.total_external_links.toLocaleString()}</div>
        <div class="stat-label">Links</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">${stats.total_comments.toLocaleString()}</div>
        <div class="stat-label">Comments</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">${(stats.total_briefings || 0).toLocaleString()}</div>
        <div class="stat-label">AI Briefings</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">${(stats.total_useful_comments || 0).toLocaleString()}</div>
        <div class="stat-label">Useful Claims</div>
      </div>
    </div>
  `;

  const intelligenceHtml = `
    <div class="intelligence-banner">
      <div>
        <div class="intelligence-kicker">Community intelligence</div>
        <div class="intelligence-value">${(stats.useful_comments_last_7_days || 0).toLocaleString()} high-signal comments added this week</div>
        <div class="intelligence-copy">${Math.round((stats.briefing_coverage || 0) * 100)}% of saved posts now have an evidence-backed AI briefing.</div>
      </div>
      <a href="#/pipeline" class="btn btn-ghost">Run understanding pipeline →</a>
    </div>
  `;

  const topicsHtml = topics.map(t => `
    <div class="card card-clickable topic-card" style="--topic-color: ${topicColor(t.name)}" onclick="location.hash='#/topics/${t.slug}'">
      <div class="topic-name">${escapeHtml(t.name)}</div>
      <div class="topic-count">${t.post_count} posts</div>
      ${t.description ? `<div class="topic-desc">${escapeHtml(t.description)}</div>` : ''}
    </div>
  `).join('');

  const topAuthorsHtml = (stats.top_authors || []).slice(0, 8).map(a => `
    <div class="card card-clickable author-card" onclick="location.hash='#/authors/${slug(a.name)}'">
      <div class="author-name">${escapeHtml(a.name)}</div>
      <div class="author-posts">${a.count} posts</div>
    </div>
  `).join('');

  const lastRunHtml = stats.last_pipeline_run ? `
    <div class="card" style="margin-top:var(--space-2xl);padding:var(--space-md) var(--space-lg)">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--space-md)">
        <div>
          <div style="font-size:0.8rem;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.05em">Last Pipeline Run</div>
          <div style="font-size:0.9rem;color:var(--text-primary);margin-top:4px">${escapeHtml(stats.last_pipeline_run.run_id || '')} — <span class="status-badge ${escapeHtml(stats.last_pipeline_run.status || '')}">${escapeHtml(stats.last_pipeline_run.status || '')}</span></div>
        </div>
        <a href="#/pipeline" class="btn btn-ghost" style="font-size:0.8rem">⚡ Run Pipeline</a>
      </div>
    </div>
  ` : `
    <div class="card" style="margin-top:var(--space-2xl);text-align:center;padding:var(--space-xl)">
      <div style="font-size:1.8rem;margin-bottom:var(--space-sm)">⚡</div>
      <div style="font-weight:600;color:var(--text-primary);margin-bottom:var(--space-xs)">No pipeline runs yet</div>
      <div style="font-size:0.85rem;color:var(--text-muted);margin-bottom:var(--space-lg)">Upload your LinkedIn data and run the pipeline to start building your knowledge graph.</div>
      <a href="#/pipeline" class="btn btn-primary">Run Pipeline →</a>
    </div>
  `;

  app().innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Knowledge Dashboard</h1>
      <p class="page-description">Your LinkedIn knowledge graph — ${stats.total_posts.toLocaleString()} posts across ${stats.total_topics} topics from ${stats.total_authors} authors.</p>
    </div>
    ${statsHtml}
    ${intelligenceHtml}
    ${lastRunHtml}
    <div class="section-header" style="margin-top:var(--space-2xl)">
      <h2 class="section-title">Topics</h2>
      <p class="section-subtitle">Explore posts by topic area</p>
    </div>
    <div class="topic-grid">${topicsHtml || '<div class="empty-state"><p>No topics yet — run the pipeline first.</p></div>'}</div>
    <div style="margin-top: var(--space-2xl)">
      <div class="section-header">
        <h2 class="section-title">Top Authors</h2>
        <p class="section-subtitle">Most active contributors</p>
      </div>
      <div class="author-grid">${topAuthorsHtml || '<div class="empty-state"><p>No authors yet.</p></div>'}</div>
    </div>
  `;
}

/* ── TOPICS LIST ──────────────────────────────────────────────────────────── */
async function renderTopicsList() {
  const topics = await api('/topics');
  assignTopicColors(topics);

  const html = topics.map(t => `
    <div class="card card-clickable topic-card" style="--topic-color: ${topicColor(t.name)}" onclick="location.hash='#/topics/${t.slug}'">
      <div class="topic-name">${escapeHtml(t.name)}</div>
      <div class="topic-count">${t.post_count} posts</div>
      ${t.description ? `<div class="topic-desc">${escapeHtml(t.description)}</div>` : ''}
    </div>
  `).join('');

  app().innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Topics</h1>
      <p class="page-description">All ${topics.length} knowledge topics</p>
    </div>
    <div class="topic-grid">${html || '<div class="empty-state"><p>No topics yet.</p></div>'}</div>
  `;
}

/* ── TOPIC DETAIL ─────────────────────────────────────────────────────────── */
async function renderTopicDetail(topicSlug) {
  const data = await api(`/topics/${topicSlug}`);
  if (data.error) {
    app().innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><p>${escapeHtml(data.error)}</p></div>`;
    return;
  }

  const subtopicsHtml = (data.subtopics || []).map(s =>
    `<span class="tag">${escapeHtml(s)}</span>`
  ).join(' ');

  const authorsHtml = (data.top_authors || []).map(a =>
    `<a href="#/authors/${slug(a.name)}" class="tag">${escapeHtml(a.name)} <span class="tag-count">${a.count}</span></a>`
  ).join(' ');

  const postsHtml = (data.posts || []).map(p => `
    <div class="card card-clickable post-card" onclick="location.hash='#/posts/${encodeURIComponent(p.urn)}'">
      <div class="post-title">${escapeHtml(p.title || truncate(p.urn))}</div>
      <div class="post-meta">
        ${p.author ? `<span class="author-name">${escapeHtml(p.author)}</span>` : ''}
        ${p.date_raw ? `<span>${escapeHtml(p.date_raw.split('•')[0].trim())}</span>` : ''}
      </div>
    </div>
  `).join('');

  let trendHtml = '';
  if (data.trend && data.trend.length > 0) {
    const maxCount = Math.max(...data.trend.map(t => t.count));
    const barWidth = Math.max(20, Math.floor(600 / data.trend.length));
    const chartWidth = barWidth * data.trend.length;
    const bars = data.trend.map((t, i) => {
      const h = maxCount > 0 ? (t.count / maxCount) * 160 : 0;
      return `<rect class="trend-bar" x="${i * barWidth}" y="${170 - h}" width="${barWidth - 4}" height="${h}" rx="3">
        <title>${t.month}: ${t.count} posts</title>
      </rect>
      <text x="${i * barWidth + barWidth/2}" y="190" fill="#6b7280" font-size="9" text-anchor="middle">${t.month.slice(5)}</text>`;
    }).join('');
    trendHtml = `
      <div class="post-detail-section">
        <h3>Monthly Trend</h3>
        <div class="trend-chart">
          <svg viewBox="0 0 ${chartWidth} 200" preserveAspectRatio="none">${bars}</svg>
        </div>
      </div>
    `;
  }

  app().innerHTML = `
    <a href="#/topics" class="back-link">← All Topics</a>
    <div class="page-header">
      <h1 class="page-title">${escapeHtml(data.name)}</h1>
      <p class="page-description">${data.post_count} posts${data.description ? ' — ' + escapeHtml(data.description) : ''}</p>
    </div>
    ${subtopicsHtml ? `<div style="margin-bottom: var(--space-lg)"><strong style="font-size:0.8rem;color:var(--text-muted)">Subtopics:</strong><div style="margin-top:var(--space-sm);display:flex;flex-wrap:wrap;gap:var(--space-xs)">${subtopicsHtml}</div></div>` : ''}
    ${authorsHtml ? `<div style="margin-bottom: var(--space-lg)"><strong style="font-size:0.8rem;color:var(--text-muted)">Top Authors:</strong><div style="margin-top:var(--space-sm);display:flex;flex-wrap:wrap;gap:var(--space-xs)">${authorsHtml}</div></div>` : ''}
    ${trendHtml}
    <div class="section-header" style="margin-top: var(--space-xl)">
      <h2 class="section-title">Posts</h2>
    </div>
    <div class="post-list">${postsHtml || '<div class="empty-state"><p>No posts in this topic</p></div>'}</div>
  `;
}

/* ── POST DETAIL ──────────────────────────────────────────────────────────── */
function renderBriefing(insight) {
  if (!insight) return '';

  const takeaways = (insight.article_takeaways || []).map(item =>
    `<li>${escapeHtml(item)}</li>`
  ).join('');
  const community = (insight.community_insights || []).map(item => `
    <div class="insight-claim">
      <div class="insight-claim-author">${escapeHtml(item.author || 'Community')}</div>
      <div class="insight-claim-text">${escapeHtml(item.claim || '')}</div>
      ${item.why_it_matters ? `<div class="insight-why">Why it matters: ${escapeHtml(item.why_it_matters)}</div>` : ''}
    </div>
  `).join('');
  const resources = (insight.resources || []).map(item => `
    <div class="link-card">
      ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" class="link-title">${escapeHtml(item.title || item.url)}</a>` : `<div class="link-title">${escapeHtml(item.title || 'Resource')}</div>`}
      ${item.value ? `<div class="link-summary">${escapeHtml(item.value)}</div>` : ''}
    </div>
  `).join('');
  const questions = (insight.open_questions || []).map(item =>
    `<li>${escapeHtml(item)}</li>`
  ).join('');

  return `
    <section class="briefing-card">
      <div class="briefing-label">AI briefing</div>
      ${insight.thesis ? `<div class="briefing-thesis">${escapeHtml(insight.thesis)}</div>` : ''}
      ${takeaways ? `<div class="briefing-section"><h3>From the article</h3><ul>${takeaways}</ul></div>` : ''}
      ${community ? `<div class="briefing-section"><h3>Community insights</h3>${community}</div>` : ''}
      ${resources ? `<div class="briefing-section"><h3>Resources</h3>${resources}</div>` : ''}
      ${questions ? `<div class="briefing-section"><h3>Open questions</h3><ul>${questions}</ul></div>` : ''}
    </section>
  `;
}

async function renderPostDetail(urn) {
  const data = await api(`/posts/${urn}`);
  if (data.error) {
    app().innerHTML = `<div class="empty-state"><div class="empty-icon">📄</div><p>${escapeHtml(data.error)}</p></div>`;
    return;
  }

  const topicsHtml = (data.topics || []).map(t =>
    `<a href="#/topics/${slug(t)}" class="tag" style="background:${topicColor(t)}22;color:${topicColor(t)};border-color:${topicColor(t)}33">${escapeHtml(t)}</a>`
  ).join(' ');

  const linksHtml = (data.external_links || []).map(l => `
    <div class="link-card">
      <a href="${escapeHtml(l.url)}" target="_blank" class="link-title">${escapeHtml(l.title || l.url)}</a>
      ${l.ai_summary ? `<div class="link-summary">${escapeHtml(l.ai_summary)}</div>` : (l.description ? `<div class="link-summary">${escapeHtml(l.description)}</div>` : '')}
    </div>
  `).join('');

  const commentsHtml = (data.comments || []).map(c => `
    <div class="comment-card">
      <div class="comment-heading">
        <div class="comment-author">${escapeHtml(c.author || 'Anonymous')}</div>
        ${c.kind ? `<span class="comment-kind">${escapeHtml(c.kind)}</span>` : ''}
      </div>
      <div class="comment-text">${escapeHtml(truncate(c.text, 300))}</div>
    </div>
  `).join('');

  const similarHtml = (data.similar_posts || []).map(s => `
    <div class="similar-item">
      <span class="search-score">${s.score.toFixed(3)}</span>
      <a href="#/posts/${encodeURIComponent(s.urn)}">${escapeHtml(s.title || s.urn)}</a>
      ${s.author ? `<span style="color:var(--text-muted);font-size:0.75rem">— ${escapeHtml(s.author)}</span>` : ''}
    </div>
  `).join('');

  const heading = data.title ? data.title.split('\n')[0] : `Post by ${data.author || 'Unknown'}`;
  const displayContent = data.summary || data.content || '';
  const briefingHtml = renderBriefing(data.insight);
  const coverage = data.source_coverage || {};
  const coverageHtml = `
    <div class="source-coverage">
      <span>${coverage.articles || 0} articles</span>
      <span>${coverage.useful_comments || 0} useful comments</span>
      <span>${coverage.comment_resources || 0} community resources</span>
    </div>
  `;

  app().innerHTML = `
    <a href="#/" class="back-link">← Back</a>
    <div class="page-header">
      <h1 class="page-title" style="font-size:1.5rem">${escapeHtml(heading)}</h1>
      <div class="post-meta" style="margin-top:var(--space-sm)">
        ${data.author ? `<a href="#/authors/${slug(data.author)}" class="author-name" style="font-size:0.9rem">${escapeHtml(data.author)}</a>` : ''}
        ${data.subtitle ? `<span style="color:var(--text-muted);font-size:0.8rem">${escapeHtml(data.subtitle)}</span>` : ''}
        ${data.date_raw ? `<span style="color:var(--text-muted);font-size:0.8rem">${escapeHtml(data.date_raw.split('•')[0].trim())}</span>` : ''}
      </div>
      ${topicsHtml ? `<div style="margin-top:var(--space-sm);display:flex;flex-wrap:wrap;gap:var(--space-xs)">${topicsHtml}</div>` : ''}
      <div class="briefing-actions">
        ${coverageHtml}
        <button class="btn btn-ghost" id="btn-regenerate-briefing" data-urn="${escapeHtml(encodeURIComponent(data.urn))}" onclick="regenerateBriefing(this)">${data.insight ? 'Regenerate briefing' : 'Generate briefing'}</button>
      </div>
    </div>
    ${briefingHtml || `<div class="post-detail-content">${escapeHtml(displayContent)}</div>`}
    ${data.source_url ? `<div style="margin-top:var(--space-md)"><a href="${escapeHtml(data.source_url)}" target="_blank" class="btn btn-ghost">View on LinkedIn →</a></div>` : ''}
    ${linksHtml ? `<div class="post-detail-section"><h3>External Links</h3>${linksHtml}</div>` : ''}
    ${commentsHtml ? `<div class="post-detail-section"><h3>High-signal thread</h3>${commentsHtml}</div>` : ''}
    ${similarHtml ? `<div class="post-detail-section"><h3>Similar Posts</h3>${similarHtml}</div>` : ''}
    ${data.insight && data.content ? `<details class="original-post"><summary>Original post</summary><div class="post-detail-content">${escapeHtml(data.content)}</div></details>` : ''}
  `;
}

async function regenerateBriefing(button) {
  const urn = decodeURIComponent(button.dataset.urn || '');
  if (!urn) return;
  button.disabled = true;
  button.textContent = 'Reasoning…';
  try {
    const result = await apiPost('/briefings', { urn });
    if (!result.ok) {
      showToast(result.error || 'Briefing generation failed', 'error');
      return;
    }
    showToast('Briefing regenerated and synced to Obsidian', 'success');
    await renderPostDetail(urn);
  } catch (_) {
    showToast('Briefing generation failed', 'error');
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = 'Regenerate briefing';
    }
  }
}

/* ── AUTHORS LIST ─────────────────────────────────────────────────────────── */
async function renderAuthorsList() {
  const authors = await api('/authors?limit=200');

  const html = authors.map(a => `
    <div class="card card-clickable author-card" onclick="location.hash='#/authors/${a.slug}'">
      <div class="author-name">${escapeHtml(a.name)}</div>
      ${a.subtitle ? `<div class="author-subtitle">${escapeHtml(a.subtitle)}</div>` : ''}
      <div class="author-posts">${a.post_count} posts</div>
    </div>
  `).join('');

  app().innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Authors</h1>
      <p class="page-description">${authors.length} contributors in your knowledge graph</p>
    </div>
    <div class="author-grid">${html || '<div class="empty-state"><p>No authors yet.</p></div>'}</div>
  `;
}

/* ── AUTHOR DETAIL ────────────────────────────────────────────────────────── */
async function renderAuthorDetail(authorSlug) {
  const data = await api(`/authors/${authorSlug}`);
  if (data.error) {
    app().innerHTML = `<div class="empty-state"><div class="empty-icon">👤</div><p>${escapeHtml(data.error)}</p></div>`;
    return;
  }

  const topicsHtml = (data.top_topics || []).map(t =>
    `<a href="#/topics/${slug(t.name)}" class="tag">${escapeHtml(t.name)} <span class="tag-count">${t.count}</span></a>`
  ).join(' ');

  const postsHtml = (data.posts || []).map(p => `
    <div class="card card-clickable post-card" onclick="location.hash='#/posts/${encodeURIComponent(p.urn)}'">
      <div class="post-title">${escapeHtml(p.title || truncate(p.urn))}</div>
      <div class="post-meta">
        ${p.date_raw ? `<span>${escapeHtml(p.date_raw.split('•')[0].trim())}</span>` : ''}
      </div>
    </div>
  `).join('');

  app().innerHTML = `
    <a href="#/authors" class="back-link">← All Authors</a>
    <div class="page-header">
      <h1 class="page-title">${escapeHtml(data.name)}</h1>
      <p class="page-description">${data.subtitle ? escapeHtml(data.subtitle) + ' — ' : ''}${data.post_count} posts</p>
    </div>
    ${topicsHtml ? `<div style="margin-bottom:var(--space-lg)"><strong style="font-size:0.8rem;color:var(--text-muted)">Topics:</strong><div style="margin-top:var(--space-sm);display:flex;flex-wrap:wrap;gap:var(--space-xs)">${topicsHtml}</div></div>` : ''}
    <div class="section-header"><h2 class="section-title">Posts</h2></div>
    <div class="post-list">${postsHtml}</div>
  `;
}

/* ── GRAPH PAGE ───────────────────────────────────────────────────────────── */
async function renderGraphPage() {
  app().innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Knowledge Graph</h1>
      <p class="page-description">Interactive visualization — topic nodes (large, colored) and post nodes (small). Click to navigate.</p>
    </div>
    <div class="graph-container" id="graph-container"></div>
  `;

  const data = await api('/graph');
  if (data.nodes && data.nodes.length > 0) {
    renderForceGraph(data, '#graph-container');
  } else {
    $('#graph-container').innerHTML = `<div class="empty-state"><div class="empty-icon">🕸️</div><p>No graph data available — run the pipeline first.</p></div>`;
  }
}

/* ── SEARCH RESULTS ───────────────────────────────────────────────────────── */
async function renderSearchResults(query, topic) {
  if (!query) {
    app().innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><p>Enter a search query</p></div>`;
    return;
  }

  const params = new URLSearchParams({ q: query, limit: '30' });
  if (topic) params.set('topic', topic);
  const results = await api(`/search?${params}`);

  const resultsHtml = results.map(r => `
    <div class="card card-clickable post-card search-result" onclick="location.hash='#/posts/${encodeURIComponent(r.urn)}'">
      <div style="display:flex;align-items:center;gap:var(--space-sm)">
        ${r.score > 0 ? `<span class="search-score">${r.score.toFixed(3)}</span>` : ''}
        <div class="post-title">${escapeHtml(r.title || r.urn)}</div>
      </div>
      <div class="post-meta">
        ${r.author ? `<span class="author-name">${escapeHtml(r.author)}</span>` : ''}
        ${(r.topics || []).map(t => `<span class="tag" style="font-size:0.65rem">${escapeHtml(t)}</span>`).join('')}
      </div>
    </div>
  `).join('');

  app().innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Search: "${escapeHtml(query)}"</h1>
      <p class="page-description">${results.length} results found</p>
    </div>
    <div class="post-list">${resultsHtml || '<div class="empty-state"><p>No results found</p></div>'}</div>
  `;
}

/* ══════════════════════════════════════════════════════════════════════════════
   SETTINGS PAGE
   ══════════════════════════════════════════════════════════════════════════════ */

let _settingsData = {};

async function renderSettingsPage() {
  _settingsData = await api('/settings');

  function pw(id, val, placeholder = '') {
    return `
      <div class="input-password-wrap">
        <input type="password" id="${id}" class="settings-input" value="${escapeHtml(val === '***' ? '' : val)}" placeholder="${placeholder}">
        <button class="btn-reveal" onclick="toggleReveal('${id}')" type="button">👁</button>
      </div>`;
  }

  app().innerHTML = `
    <div class="settings-page">
      <div class="page-header">
        <h1 class="page-title">Settings</h1>
        <p class="page-description">Configure API keys, credentials, and pipeline settings. Saved securely in local storage — no .env file needed.</p>
      </div>

      <!-- ── Groq API ── -->
      <div class="settings-section" id="section-groq">
        <div class="settings-section-header">
          <div class="settings-section-icon">🚀</div>
          <div>
            <div class="settings-section-title">Groq API</div>
            <div class="settings-section-subtitle">Required · Powers complex reasoning, graph building, and enrichment</div>
          </div>
        </div>
        <div class="settings-field">
          <label class="settings-label">API Key <span class="required-badge">Required</span></label>
          <div class="settings-input-row">
            ${pw('groq_api_key', _settingsData.groq_api_key, 'gsk_...')}
            <button class="btn-test" id="btn-test-groq" onclick="testGroq()">Test</button>
          </div>
          <div id="groq-status"></div>
          <div class="settings-hint">Get a free key at <a href="https://console.groq.com" target="_blank">console.groq.com</a></div>
        </div>
        <div class="settings-field">
          <label class="settings-label">Model</label>
          <select id="groq_model" class="settings-input pipeline-select">
            ${['llama-3.3-70b-versatile','meta-llama/llama-4-scout-17b-16e-instruct','qwen/qwen3-32b','qwen/qwen3.6-27b'].map(m =>
              `<option value="${m}" ${_settingsData.groq_model === m ? 'selected' : ''}>${m}</option>`
            ).join('')}
          </select>
          <div class="settings-hint">Primary model for heavy tasks. Fallback models are configured automatically.</div>
        </div>
      </div>

      <!-- ── Local Model (vLLM / llama.cpp) ── -->
      <div class="settings-section" id="section-vllm">
        <div class="settings-section-header">
          <div class="settings-section-icon">🖥️</div>
          <div>
            <div class="settings-section-title">Local Model Server</div>
            <div class="settings-section-subtitle">Optional · vLLM, llama.cpp, Ollama, or any OpenAI-compatible server for batch classification</div>
          </div>
        </div>
        <div class="settings-field">
          <label class="settings-label">Base URL <span class="optional-badge">Optional</span></label>
          <div class="settings-input-row">
            <input type="text" id="vllm_base_url" class="settings-input monospace" value="${escapeHtml(_settingsData.vllm_base_url)}" placeholder="http://localhost:8000 or https://ngrok-url.app">
            <button class="btn-test" id="btn-test-vllm" onclick="testVllm()">Test</button>
          </div>
          <div id="vllm-status"></div>
          <div class="settings-hint">Works with any OpenAI-compatible server. If <code>/v1/chat/completions/batch</code> isn't available (e.g. llama.cpp), the pipeline automatically falls back to concurrent async calls.</div>
        </div>
        <div class="settings-two-col">
          <div class="settings-field">
            <label class="settings-label">Model ID</label>
            <input type="text" id="vllm_model" class="settings-input" value="${escapeHtml(_settingsData.vllm_model)}" placeholder="Qwen/Qwen3.5-9B-FP8">
          </div>
          <div class="settings-field">
            <label class="settings-label">Embedding Model</label>
            <input type="text" id="embedding_model" class="settings-input" value="${escapeHtml(_settingsData.embedding_model)}" placeholder="Qwen/Qwen3-Embedding-0.6B">
          </div>
        </div>
        <div class="settings-field">
          <label class="settings-label">Embedding Device</label>
          <select id="embedding_device" class="settings-input pipeline-select">
            <option value="cuda" ${_settingsData.embedding_device === 'cuda' ? 'selected' : ''}>CUDA (GPU)</option>
            <option value="cpu" ${_settingsData.embedding_device === 'cpu' ? 'selected' : ''}>CPU</option>
            <option value="mps" ${_settingsData.embedding_device === 'mps' ? 'selected' : ''}>MPS (Apple Silicon)</option>
          </select>
        </div>
      </div>

      <!-- ── LinkedIn ── -->
      <div class="settings-section" id="section-linkedin">
        <div class="settings-section-header">
          <div class="settings-section-icon">💼</div>
          <div>
            <div class="settings-section-title">LinkedIn</div>
            <div class="settings-section-subtitle">Optional · Only needed for live scraping and comment fetching</div>
          </div>
        </div>

        <div class="settings-tabs" id="linkedin-tabs">
          <button class="settings-tab active" id="tab-creds" onclick="switchLinkedinTab('creds')">Email &amp; Password</button>
          <button class="settings-tab" id="tab-cookie" onclick="switchLinkedinTab('cookie')">Session Cookie</button>
        </div>

        <div id="linkedin-creds-panel">
          <div class="settings-two-col">
            <div class="settings-field">
              <label class="settings-label">Email</label>
              <input type="email" id="linkedin_email" class="settings-input" value="${escapeHtml(_settingsData.linkedin_email)}" placeholder="you@example.com">
            </div>
            <div class="settings-field">
              <label class="settings-label">Password</label>
              ${pw('linkedin_password', _settingsData.linkedin_password, '••••••••')}
            </div>
          </div>
        </div>

        <div id="linkedin-cookie-panel" style="display:none">
          <div class="settings-field">
            <label class="settings-label">li_at Cookie Value</label>
            ${pw('linkedin_cookie', _settingsData.linkedin_cookie, 'Paste your li_at cookie value here')}
          </div>
          <details class="cookie-instructions">
            <summary>📖 How to get your LinkedIn session cookie</summary>
            <ol>
              <li>Log in to <a href="https://linkedin.com" target="_blank" style="color:var(--text-accent)">linkedin.com</a> in your browser</li>
              <li>Open DevTools: press <code>F12</code> or <code>Cmd+Option+I</code></li>
              <li>Go to the <code>Application</code> tab (Chrome) or <code>Storage</code> tab (Firefox)</li>
              <li>Expand <code>Cookies</code> → click <code>https://www.linkedin.com</code></li>
              <li>Find the cookie named <code>li_at</code> and copy its <strong>Value</strong></li>
              <li>Paste it in the field above and save</li>
            </ol>
          </details>
        </div>
      </div>

      <!-- ── Data Upload ── -->
      <div class="settings-section" id="section-upload">
        <div class="settings-section-header">
          <div class="settings-section-icon">📁</div>
          <div>
            <div class="settings-section-title">LinkedIn Data Export</div>
            <div class="settings-section-subtitle">Upload your saved posts JSON from LinkedIn data export</div>
          </div>
        </div>
        <div class="settings-field">
          <label class="settings-label">linkedin_saved_posts.json</label>
          <div class="upload-area" id="upload-area" onclick="$('#json-file-input').click()">
            <input type="file" id="json-file-input" accept=".json" onchange="handleJsonUpload(this)">
            <div class="upload-icon">📤</div>
            <div class="upload-title">Drop your JSON file here or click to browse</div>
            <div class="upload-hint">From LinkedIn's <strong>Data Export</strong> → Saved posts JSON file</div>
          </div>
          <div id="upload-status"></div>
          <div class="settings-hint" style="margin-top:var(--space-sm)">
            To export: LinkedIn → Me → Settings &amp; Privacy → Data Privacy → Get a copy of your data → select "Saved items"
          </div>
        </div>
      </div>

      <!-- ── Pipeline Tuning ── -->
      <div class="settings-section" id="section-pipeline">
        <div class="settings-section-header">
          <div class="settings-section-icon">⚙️</div>
          <div>
            <div class="settings-section-title">Pipeline Settings</div>
            <div class="settings-section-subtitle">Tune performance and processing behavior</div>
          </div>
        </div>
        <div class="settings-two-col">
          <div class="settings-field">
            <label class="settings-label">Batch Size</label>
            <input type="number" id="batch_size" class="settings-input" value="${escapeHtml(_settingsData.batch_size)}" min="1" max="50">
            <div class="settings-hint">Posts per LLM batch (1–50)</div>
          </div>
          <div class="settings-field">
            <label class="settings-label">LLM Timeout (seconds)</label>
            <input type="number" id="llm_timeout" class="settings-input" value="${escapeHtml(_settingsData.llm_timeout)}" min="30">
          </div>
          <div class="settings-field">
            <label class="settings-label">Max Comments per Post</label>
            <input type="number" id="max_comments" class="settings-input" value="${escapeHtml(_settingsData.max_comments)}" min="0">
          </div>
          <div class="settings-field">
            <label class="settings-label">Schedule Interval (hours)</label>
            <input type="number" id="schedule_interval_hours" class="settings-input" value="${escapeHtml(_settingsData.schedule_interval_hours)}" min="0.5" step="0.5">
          </div>
        </div>
        <div class="settings-two-col">
          <div class="settings-field">
            <label class="settings-label">Log Level</label>
            <select id="log_level" class="settings-input pipeline-select">
              ${['DEBUG','INFO','WARNING','ERROR'].map(l =>
                `<option value="${l}" ${_settingsData.log_level === l ? 'selected' : ''}>${l}</option>`
              ).join('')}
            </select>
          </div>
          <div class="settings-field">
            <label class="settings-label">Web Dashboard Port</label>
            <input type="number" id="web_port" class="settings-input" value="${escapeHtml(_settingsData.web_port)}" min="1024" max="65535">
          </div>
        </div>
      </div>

      <!-- Save bar -->
      <div class="settings-save-bar">
        <div class="settings-save-note">Changes are saved locally and encrypted at rest.</div>
        <button class="btn btn-primary btn-lg" id="btn-save-settings" onclick="saveSettings()">Save Settings</button>
      </div>
    </div>
  `;

  // Drag & drop for upload area
  const ua = $('#upload-area');
  ua.addEventListener('dragover', e => { e.preventDefault(); ua.classList.add('drag-over'); });
  ua.addEventListener('dragleave', () => ua.classList.remove('drag-over'));
  ua.addEventListener('drop', e => {
    e.preventDefault();
    ua.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) handleJsonUploadFile(file);
  });
}

function toggleReveal(id) {
  const el = $(`#${id}`);
  el.type = el.type === 'password' ? 'text' : 'password';
}

function switchLinkedinTab(tab) {
  $('#tab-creds').classList.toggle('active', tab === 'creds');
  $('#tab-cookie').classList.toggle('active', tab === 'cookie');
  $('#linkedin-creds-panel').style.display = tab === 'creds' ? '' : 'none';
  $('#linkedin-cookie-panel').style.display = tab === 'cookie' ? '' : 'none';
}

async function testGroq() {
  const btn = $('#btn-test-groq');
  const statusEl = $('#groq-status');
  const key = $('#groq_api_key').value.trim();

  // Save the key first so the backend can test it
  if (key && key !== '***') {
    await apiPut('/settings', { groq_api_key: key });
  }

  btn.disabled = true;
  btn.textContent = '…';
  statusEl.innerHTML = `<div class="conn-status testing">Testing connection…</div>`;

  try {
    const res = await apiPost('/settings/test-groq', {});
    statusEl.innerHTML = `<div class="conn-status ${res.ok ? 'ok' : 'fail'}">
      ${res.ok ? '✓' : '✗'} ${escapeHtml(res.message)}${res.latency_ms ? ` (${res.latency_ms}ms)` : ''}
    </div>`;
    if (res.ok) showToast('Groq connected ✓', 'success');
    else showToast(`Groq test failed: ${res.message}`, 'error');
  } catch (e) {
    statusEl.innerHTML = `<div class="conn-status fail">✗ Request failed</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test';
  }
}

async function testVllm() {
  const btn = $('#btn-test-vllm');
  const statusEl = $('#vllm-status');
  const url = $('#vllm_base_url').value.trim();

  if (url) {
    await apiPut('/settings', { vllm_base_url: url });
  }

  btn.disabled = true;
  btn.textContent = '…';
  statusEl.innerHTML = `<div class="conn-status testing">Testing connection…</div>`;

  try {
    const res = await apiPost('/settings/test-vllm', {});
    statusEl.innerHTML = `<div class="conn-status ${res.ok ? 'ok' : 'fail'}">
      ${res.ok ? '✓' : '✗'} ${escapeHtml(res.message)}${res.latency_ms ? ` (${res.latency_ms}ms)` : ''}
    </div>`;
    if (res.ok) showToast('Local model server connected ✓', 'success');
    else showToast(`vLLM test failed: ${res.message}`, 'error');
  } catch (e) {
    statusEl.innerHTML = `<div class="conn-status fail">✗ Request failed</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test';
  }
}

async function saveSettings() {
  const btn = $('#btn-save-settings');
  btn.disabled = true;
  btn.textContent = 'Saving…';

  const fields = [
    'groq_api_key', 'groq_model',
    'vllm_base_url', 'vllm_model', 'embedding_model', 'embedding_device',
    'linkedin_email', 'linkedin_password', 'linkedin_cookie',
    'batch_size', 'llm_timeout', 'max_comments', 'schedule_interval_hours',
    'log_level', 'web_port',
  ];

  const payload = {};
  for (const f of fields) {
    const el = $(`#${f}`);
    if (!el) continue;
    const val = el.value.trim();
    if (val && val !== '***') payload[f] = val;
  }

  try {
    await apiPut('/settings', payload);
    showToast('Settings saved ✓', 'success');
  } catch (e) {
    showToast('Failed to save settings', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save Settings';
  }
}

async function handleJsonUpload(input) {
  const file = input.files[0];
  if (file) await handleJsonUploadFile(file);
}

async function handleJsonUploadFile(file) {
  const statusEl = $('#upload-status');
  statusEl.innerHTML = `<div class="conn-status testing">Uploading ${escapeHtml(file.name)}…</div>`;

  const form = new FormData();
  form.append('file', file);

  try {
    const resp = await fetch('/api/upload/linkedin-json', { method: 'POST', body: form });
    const res = await resp.json();
    if (res.ok) {
      statusEl.innerHTML = `<div class="upload-success">✅ Uploaded successfully — ${res.size_kb} KB saved to workspace</div>`;
      showToast(`${file.name} uploaded ✓`, 'success');
    } else {
      statusEl.innerHTML = `<div class="conn-status fail">✗ ${escapeHtml(res.error)}</div>`;
      showToast(`Upload failed: ${res.error}`, 'error');
    }
  } catch (e) {
    statusEl.innerHTML = `<div class="conn-status fail">✗ Upload failed</div>`;
    showToast('Upload failed', 'error');
  }
}

/* ══════════════════════════════════════════════════════════════════════════════
   PIPELINE PAGE
   ══════════════════════════════════════════════════════════════════════════════ */

const PIPELINE_STAGES = [
  { id: 'ingest',         icon: '📥', name: 'Ingest' },
  { id: 'comments',       icon: '💬', name: 'Comments' },
  { id: 'rank_comments',  icon: '🎯', name: 'Rank Comments' },
  { id: 'comment_enrich', icon: '🔗', name: 'Link Enrich' },
  { id: 'enrich',         icon: '🌐', name: 'Enrich' },
  { id: 'classify',       icon: '🏷️', name: 'Classify' },
  { id: 'embed',          icon: '🔢', name: 'Embed' },
  { id: 'subtopic',       icon: '🧬', name: 'Subtopics' },
  { id: 'insights',       icon: '🧠', name: 'AI Briefings' },
  { id: 'semantic_edges', icon: '🕸️', name: 'Edges' },
  { id: 'graph_build',    icon: '🗺️', name: 'Graph Build' },
  { id: 'vault_write',    icon: '📝', name: 'Vault Write' },
];

let _sseSource = null;
let _pipelineStatus = { state: 'idle' };
let _stageResults = {};

async function renderPipelinePage() {
  _pipelineStatus = await api('/pipeline/status');
  _stageResults = {};
  if (_pipelineStatus.last_result) {
    for (const s of (_pipelineStatus.last_result.stages || [])) {
      _stageResults[s.stage] = s;
    }
  }

  const stagesHtml = PIPELINE_STAGES.map(s => {
    const r = _stageResults[s.id];
    const cls = _pipelineStatus.state === 'running' ? '' : (r ? 'done' : '');
    return `<div class="stage-item ${cls}" id="stage-${s.id}">
      <span class="stage-icon">${s.icon}</span>
      <span class="stage-name">${s.name}</span>
      <span class="stage-count" id="stage-count-${s.id}">${r ? `${r.processed} done` : '—'}</span>
    </div>`;
  }).join('');

  app().innerHTML = `
    <div class="pipeline-page">
      <div class="page-header">
        <h1 class="page-title">Pipeline</h1>
        <p class="page-description">Run and monitor your LinkedIn knowledge graph pipeline. Upload a JSON export in Settings first, or enable live scraping.</p>
      </div>

      <!-- Stage overview -->
      <div class="pipeline-stage-list">${stagesHtml}</div>

      <!-- Controls -->
      <div class="pipeline-controls">
        <div style="display:flex;flex-direction:column;gap:4px">
          <label style="font-size:0.78rem;color:var(--text-muted);font-weight:600">Start From</label>
          <select id="select-start-from" class="pipeline-select">
            <option value="">— Full Run —</option>
            ${PIPELINE_STAGES.map(s => `<option value="${s.id}">${s.name}</option>`).join('')}
          </select>
        </div>
        <div style="display:flex;flex-direction:column;gap:4px">
          <label style="font-size:0.78rem;color:var(--text-muted);font-weight:600">Only Stage</label>
          <select id="select-only-stage" class="pipeline-select">
            <option value="">— All stages —</option>
            ${PIPELINE_STAGES.map(s => `<option value="${s.id}">${s.name}</option>`).join('')}
          </select>
        </div>
        <button class="btn btn-primary btn-lg" id="btn-run" onclick="runPipeline()">⚡ Run Pipeline</button>
        <button class="btn btn-ghost" id="btn-cancel" onclick="cancelPipeline()" style="display:none">✕ Cancel</button>
      </div>

      <!-- Status bar -->
      <div class="pipeline-status-bar">
        <span class="status-badge ${_pipelineStatus.state}" id="pipeline-state-badge">${_pipelineStatus.state}</span>
        <span style="color:var(--text-muted);font-size:0.8rem" id="pipeline-status-text">
          ${_pipelineStatus.started_at ? `Started ${new Date(_pipelineStatus.started_at).toLocaleTimeString()}` : 'Ready to run'}
        </span>
        <span style="margin-left:auto;font-size:0.78rem;color:var(--text-muted)" id="pipeline-log-count">${_pipelineStatus.log_count} log entries</span>
      </div>

      <!-- Terminal -->
      <div class="pipeline-terminal">
        <div class="terminal-header">
          <div class="terminal-dots">
            <div class="terminal-dot red"></div>
            <div class="terminal-dot yellow"></div>
            <div class="terminal-dot green"></div>
          </div>
          <div class="terminal-title">pipeline.log — Social Graph</div>
          <button onclick="clearTerminal()" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:0.7rem">Clear</button>
        </div>
        <div class="terminal-body" id="terminal-body">
          <div class="log-line"><span class="log-event" style="color:var(--text-muted)">Ready. Click "Run Pipeline" to start.</span></div>
        </div>
      </div>
    </div>
  `;

  // Reconnect SSE if pipeline is already running
  if (_pipelineStatus.state === 'running') {
    startPipelineSSE(_pipelineStatus.log_count);
    updatePipelineControls('running');
  }
}

function appendLog(entry) {
  if (entry.event === '__done__') return;
  const body = $('#terminal-body');
  if (!body) return;

  const ts = entry.ts ? new Date(entry.ts).toLocaleTimeString() : '';
  const level = (entry.level || 'info').toLowerCase();
  const event = escapeHtml(entry.event || '');

  // Build metadata string from extra keys
  const skip = new Set(['ts', 'level', 'event']);
  const meta = Object.entries(entry)
    .filter(([k]) => !skip.has(k))
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join(' ');

  const line = document.createElement('div');
  line.className = 'log-line';
  line.innerHTML = `
    <span class="log-ts">${ts}</span>
    <span class="log-level ${level}">${level.toUpperCase()}</span>
    <span class="log-event">${event}</span>
    ${meta ? `<span class="log-meta">${escapeHtml(meta)}</span>` : ''}
  `;

  body.appendChild(line);

  // Auto-scroll
  body.scrollTop = body.scrollHeight;

  // Update stage item if this log is for a stage
  if (entry.stage) {
    const stageEl = $(`#stage-${entry.stage}`);
    if (stageEl) {
      stageEl.classList.add('active');
      stageEl.classList.remove('done');
    }
  }
  if (entry.event && entry.event.endsWith('.stage_done') && entry.stage) {
    const stageEl = $(`#stage-${entry.stage}`);
    const countEl = $(`#stage-count-${entry.stage}`);
    if (stageEl) { stageEl.classList.remove('active'); stageEl.classList.add('done'); }
    if (countEl && entry.processed !== undefined) countEl.textContent = `${entry.processed} done`;
  }
}

function clearTerminal() {
  const body = $('#terminal-body');
  if (body) body.innerHTML = '';
}

function updatePipelineControls(state) {
  const runBtn = $('#btn-run');
  const cancelBtn = $('#btn-cancel');
  const badge = $('#pipeline-state-badge');

  if (runBtn) {
    runBtn.disabled = state === 'running';
    runBtn.textContent = state === 'running' ? '⏳ Running…' : '⚡ Run Pipeline';
  }
  if (cancelBtn) cancelBtn.style.display = state === 'running' ? '' : 'none';
  if (badge) { badge.className = `status-badge ${state}`; badge.textContent = state; }
  updatePipelineIndicator(state);
}

function startPipelineSSE(fromIndex = 0) {
  if (_sseSource) { _sseSource.close(); _sseSource = null; }

  const url = `/api/pipeline/logs?from_index=${fromIndex}`;
  _sseSource = new EventSource(url);

  _sseSource.onmessage = (e) => {
    try {
      const entry = JSON.parse(e.data);
      appendLog(entry);

      if (entry.event === 'pipeline.completed') {
        updatePipelineControls('completed');
        _sseSource.close();
        _sseSource = null;
      } else if (entry.event === 'pipeline.failed') {
        updatePipelineControls('failed');
        _sseSource.close();
        _sseSource = null;
      } else if (entry.event === '__done__') {
        _sseSource.close();
        _sseSource = null;
      }
    } catch (_) {}
  };

  _sseSource.onerror = () => {
    if (_sseSource) { _sseSource.close(); _sseSource = null; }
  };
}

async function runPipeline() {
  const startFrom = $('#select-start-from')?.value || null;
  const onlyStage = $('#select-only-stage')?.value || null;

  clearTerminal();
  updatePipelineControls('running');
  startPipelinePolling();

  const res = await apiPost('/pipeline/run', {
    start_from: startFrom || null,
    only_stage: onlyStage || null,
    live: false,
  });

  if (res.ok) {
    showToast('Pipeline started ⚡', 'info');
    startPipelineSSE(0);
  } else {
    showToast(`Could not start: ${res.error}`, 'error');
    updatePipelineControls('idle');
  }
}

async function cancelPipeline() {
  await apiPost('/pipeline/cancel', {});
  showToast('Pipeline cancellation requested…', 'warning');
  updatePipelineControls('idle');
  if (_sseSource) { _sseSource.close(); _sseSource = null; }
}

/* ══════════════════════════════════════════════════════════════════════════════
   ONBOARDING WIZARD
   ══════════════════════════════════════════════════════════════════════════════ */

const ONBOARDING_STEPS = [
  {
    icon: '⬡',
    title: 'Welcome to Social Graph',
    desc: `Turn your LinkedIn saved posts into a searchable, navigable knowledge graph — locally, privately, and for free.<br><br>Let's get you set up in under 2 minutes.`,
    action: 'Get Started →',
    skip: 'I already have my keys in .env, skip setup',
  },
  {
    icon: '🚀',
    title: 'Connect Groq API',
    desc: `Groq powers the complex reasoning tasks — graph building, enrichment, and synthesis. It has a generous free tier.`,
    field: `
      <div class="settings-field">
        <label class="settings-label">Groq API Key <span class="required-badge">Required</span></label>
        <div class="settings-input-row">
          <div class="input-password-wrap" style="flex:1">
            <input type="password" id="ob-groq-key" class="settings-input" placeholder="gsk_...">
            <button class="btn-reveal" onclick="toggleReveal('ob-groq-key')" type="button">👁</button>
          </div>
          <button class="btn-test" id="ob-btn-test-groq" onclick="obTestGroq()">Test</button>
        </div>
        <div id="ob-groq-status"></div>
        <div class="settings-hint">Get a free key at <a href="https://console.groq.com" target="_blank">console.groq.com</a> — takes 30 seconds.</div>
      </div>`,
    action: 'Save & Continue →',
    skip: 'Skip for now',
  },
  {
    icon: '🖥️',
    title: 'Local Model Server',
    desc: `Optional: connect a local model server (vLLM, llama.cpp, Ollama) for batch classification. If you skip this, Groq handles everything.`,
    field: `
      <div class="settings-field">
        <label class="settings-label">Server URL <span class="optional-badge">Optional</span></label>
        <div class="settings-input-row">
          <input type="text" id="ob-vllm-url" class="settings-input" placeholder="http://localhost:8000">
          <button class="btn-test" onclick="obTestVllm()">Test</button>
        </div>
        <div id="ob-vllm-status"></div>
        <div class="settings-hint">Works with vLLM, llama.cpp, Ollama, or any OpenAI-compatible server. Batch endpoint is auto-detected.</div>
      </div>`,
    action: 'Continue →',
    skip: 'Skip — use Groq only',
  },
  {
    icon: '💼',
    title: 'LinkedIn Access',
    desc: `Optional: provide credentials for live scraping and fetching comments. You can also just use the JSON export from LinkedIn.`,
    field: `
      <div class="settings-tabs" style="margin-bottom:var(--space-md)">
        <button class="settings-tab active" id="ob-tab-creds" onclick="obSwitchTab('creds')">Email &amp; Password</button>
        <button class="settings-tab" id="ob-tab-cookie" onclick="obSwitchTab('cookie')">Session Cookie</button>
      </div>
      <div id="ob-creds-panel">
        <div class="settings-two-col">
          <div class="settings-field"><label class="settings-label">Email</label><input type="email" id="ob-li-email" class="settings-input" placeholder="you@example.com"></div>
          <div class="settings-field"><label class="settings-label">Password</label><div class="input-password-wrap"><input type="password" id="ob-li-password" class="settings-input" placeholder="••••••••"><button class="btn-reveal" onclick="toggleReveal('ob-li-password')" type="button">👁</button></div></div>
        </div>
      </div>
      <div id="ob-cookie-panel" style="display:none">
        <div class="settings-field">
          <label class="settings-label">li_at Cookie</label>
          <div class="input-password-wrap"><input type="password" id="ob-li-cookie" class="settings-input" placeholder="Paste your li_at cookie value"><button class="btn-reveal" onclick="toggleReveal('ob-li-cookie')" type="button">👁</button></div>
          <details class="cookie-instructions"><summary>📖 How to get your cookie</summary><ol><li>Log in to linkedin.com</li><li>Open DevTools (F12)</li><li>Go to Application → Cookies → linkedin.com</li><li>Find <code>li_at</code> and copy its Value</li></ol></details>
        </div>
      </div>`,
    action: 'Save & Continue →',
    skip: 'Skip — I\'ll use JSON export',
  },
  {
    icon: '🎉',
    title: 'You\'re all set!',
    desc: `Your Social Graph is configured and ready. Upload a LinkedIn JSON export or run the pipeline — your knowledge graph awaits.`,
    action: '⚡ Go to Pipeline →',
    skip: null,
    done: true,
  },
];

let _obStep = 0;

async function checkAndShowOnboarding() {
  try {
    const status = await api('/settings/is-configured');
    if (!status.configured) {
      showOnboarding();
    }
  } catch (_) {}
}

function showOnboarding() {
  _obStep = 0;
  const overlay = $('#onboarding-overlay');
  overlay.style.display = 'flex';
  renderOnboardingStep();
}

function hideOnboarding() {
  $('#onboarding-overlay').style.display = 'none';
}

function renderOnboardingStep() {
  const step = ONBOARDING_STEPS[_obStep];
  const total = ONBOARDING_STEPS.length;
  const modal = $('#onboarding-modal');

  const dots = Array.from({ length: total }, (_, i) => {
    const cls = i < _obStep ? 'done' : (i === _obStep ? 'active' : '');
    return `<div class="step-dot ${cls}"></div>`;
  }).join('');

  modal.innerHTML = `
    <div class="onboarding-step-indicator">${dots}</div>
    <div class="onboarding-icon">${step.icon}</div>
    <div class="onboarding-title">${step.title}</div>
    <div class="onboarding-desc">${step.desc}</div>
    ${step.field || ''}
    <div class="onboarding-actions">
      ${step.skip ? `<button class="onboarding-skip" onclick="onboardingSkip()">${step.skip}</button>` : '<div></div>'}
      <button class="btn btn-primary btn-lg" onclick="onboardingNext()">${step.action}</button>
    </div>
  `;
}

async function onboardingNext() {
  const step = ONBOARDING_STEPS[_obStep];

  // Save data for each step
  if (_obStep === 1) {
    const key = $('#ob-groq-key')?.value.trim();
    if (key) await apiPut('/settings', { groq_api_key: key });
  } else if (_obStep === 2) {
    const url = $('#ob-vllm-url')?.value.trim();
    if (url) await apiPut('/settings', { vllm_base_url: url });
  } else if (_obStep === 3) {
    const email = $('#ob-li-email')?.value.trim();
    const pw = $('#ob-li-password')?.value.trim();
    const cookie = $('#ob-li-cookie')?.value.trim();
    const payload = {};
    if (email) payload.linkedin_email = email;
    if (pw) payload.linkedin_password = pw;
    if (cookie) payload.linkedin_cookie = cookie;
    if (Object.keys(payload).length) await apiPut('/settings', payload);
  }

  if (step.done) {
    hideOnboarding();
    location.hash = '#/pipeline';
    return;
  }

  _obStep++;
  renderOnboardingStep();
}

function onboardingSkip() {
  if (_obStep >= ONBOARDING_STEPS.length - 2) {
    hideOnboarding();
    return;
  }
  _obStep++;
  renderOnboardingStep();
}

async function obTestGroq() {
  const key = $('#ob-groq-key')?.value.trim();
  if (key) await apiPut('/settings', { groq_api_key: key });
  const statusEl = $('#ob-groq-status');
  statusEl.innerHTML = `<div class="conn-status testing">Testing…</div>`;
  const res = await apiPost('/settings/test-groq', {});
  statusEl.innerHTML = `<div class="conn-status ${res.ok ? 'ok' : 'fail'}">${res.ok ? '✓' : '✗'} ${escapeHtml(res.message)}</div>`;
}

async function obTestVllm() {
  const url = $('#ob-vllm-url')?.value.trim();
  if (url) await apiPut('/settings', { vllm_base_url: url });
  const statusEl = $('#ob-vllm-status');
  statusEl.innerHTML = `<div class="conn-status testing">Testing…</div>`;
  const res = await apiPost('/settings/test-vllm', {});
  statusEl.innerHTML = `<div class="conn-status ${res.ok ? 'ok' : 'fail'}">${res.ok ? '✓' : '✗'} ${escapeHtml(res.message)}</div>`;
}

function obSwitchTab(tab) {
  $('#ob-tab-creds').classList.toggle('active', tab === 'creds');
  $('#ob-tab-cookie').classList.toggle('active', tab === 'cookie');
  $('#ob-creds-panel').style.display = tab === 'creds' ? '' : 'none';
  $('#ob-cookie-panel').style.display = tab === 'cookie' ? '' : 'none';
}

/* ── Search Bar Handler ───────────────────────────────────────────────────── */
let searchTimeout = null;
$('#search-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    const q = e.target.value.trim();
    if (q) {
      location.hash = `#/search?q=${encodeURIComponent(q)}`;
    }
  }
});

$('#search-input').addEventListener('input', (e) => {
  clearTimeout(searchTimeout);
  const q = e.target.value.trim();
  if (q.length >= 3) {
    searchTimeout = setTimeout(() => {
      location.hash = `#/search?q=${encodeURIComponent(q)}`;
    }, 500);
  }
});

/* ── Bootstrap ────────────────────────────────────────────────────────────── */
window.addEventListener('hashchange', router);
window.addEventListener('DOMContentLoaded', async () => {
  await router();
  // Check pipeline status for indicator
  try {
    const status = await api('/pipeline/status');
    if (status.state === 'running') {
      updatePipelineIndicator('running');
      startPipelinePolling();
    }
  } catch (_) {}
  // Show onboarding if not configured
  await checkAndShowOnboarding();
});
