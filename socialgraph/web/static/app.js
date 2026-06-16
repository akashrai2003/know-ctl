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
async function api(path) {
  const resp = await fetch(`/api${path}`);
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

/* ── Router ───────────────────────────────────────────────────────────────── */
async function router() {
  const hash = location.hash || '#/';
  const parts = hash.slice(2).split('?');
  const path = parts[0] || '';
  const params = new URLSearchParams(parts[1] || '');

  // Update active nav link
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
    } else {
      app().innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><p>Page not found</p></div>`;
    }
  } catch (err) {
    console.error('Router error:', err);
    app().innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><p>Error loading page</p></div>`;
  }

  // Animate in
  app().classList.remove('page-enter');
  void app().offsetWidth; // force reflow
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

  app().innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Knowledge Dashboard</h1>
      <p class="page-description">Your LinkedIn knowledge graph — ${stats.total_posts.toLocaleString()} posts across ${stats.total_topics} topics from ${stats.total_authors} authors.</p>
    </div>
    ${statsHtml}
    <div class="section-header">
      <h2 class="section-title">Topics</h2>
      <p class="section-subtitle">Explore posts by topic area</p>
    </div>
    <div class="topic-grid">${topicsHtml}</div>
    <div style="margin-top: var(--space-2xl)">
      <div class="section-header">
        <h2 class="section-title">Top Authors</h2>
        <p class="section-subtitle">Most active contributors</p>
      </div>
      <div class="author-grid">${topAuthorsHtml}</div>
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
    <div class="topic-grid">${html}</div>
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

  // Trend chart
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
      <div class="comment-author">${escapeHtml(c.author || 'Anonymous')}</div>
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
    </div>
    <div class="post-detail-content">${escapeHtml(displayContent)}</div>
    ${data.source_url ? `<div style="margin-top:var(--space-md)"><a href="${escapeHtml(data.source_url)}" target="_blank" class="btn btn-ghost">View on LinkedIn →</a></div>` : ''}
    ${linksHtml ? `<div class="post-detail-section"><h3>External Links</h3>${linksHtml}</div>` : ''}
    ${commentsHtml ? `<div class="post-detail-section"><h3>Comments</h3>${commentsHtml}</div>` : ''}
    ${similarHtml ? `<div class="post-detail-section"><h3>Similar Posts</h3>${similarHtml}</div>` : ''}
  `;
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
    <div class="author-grid">${html}</div>
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
    $('#graph-container').innerHTML = `<div class="empty-state"><div class="empty-icon">🕸️</div><p>No graph data available</p></div>`;
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
window.addEventListener('DOMContentLoaded', router);
