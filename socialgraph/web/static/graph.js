/* ══════════════════════════════════════════════════════════════════════════════
   Social Graph — D3.js Force-Directed Graph Visualization
   ══════════════════════════════════════════════════════════════════════════════ */

function renderForceGraph(data, containerSelector) {
  const container = document.querySelector(containerSelector);
  if (!container || !data.nodes || data.nodes.length === 0) return;

  const width = container.clientWidth;
  const height = container.clientHeight || 600;

  // Clear existing
  container.innerHTML = '';

  const svg = d3.select(containerSelector)
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', [0, 0, width, height]);

  // Tooltip
  const tooltip = d3.select('body').append('div')
    .attr('class', 'graph-tooltip')
    .style('display', 'none');

  // Zoom behavior
  const g = svg.append('g');

  const zoom = d3.zoom()
    .scaleExtent([0.1, 4])
    .on('zoom', (event) => {
      g.attr('transform', event.transform);
    });

  svg.call(zoom);

  // Center initially
  svg.call(zoom.transform, d3.zoomIdentity.translate(width / 2, height / 2).scale(0.6));

  // Separate topic and post nodes for sizing
  const topicNodes = data.nodes.filter(n => n.type === 'topic');
  const postNodes = data.nodes.filter(n => n.type === 'post');

  // Force simulation
  const simulation = d3.forceSimulation(data.nodes)
    .force('link', d3.forceLink(data.links).id(d => d.id).distance(d => {
      // Topic-topic links longer, post-topic shorter
      const s = data.nodes.find(n => n.id === (typeof d.source === 'string' ? d.source : d.source.id));
      const t = data.nodes.find(n => n.id === (typeof d.target === 'string' ? d.target : d.target.id));
      if (s && t && s.type === 'topic' && t.type === 'topic') return 200;
      return 60;
    }).strength(0.3))
    .force('charge', d3.forceManyBody().strength(d => d.type === 'topic' ? -300 : -15))
    .force('center', d3.forceCenter(0, 0))
    .force('collision', d3.forceCollide().radius(d => d.type === 'topic' ? 30 : 4));

  // Links
  const link = g.append('g')
    .selectAll('line')
    .data(data.links)
    .join('line')
    .attr('stroke', 'rgba(255,255,255,0.05)')
    .attr('stroke-width', d => Math.max(0.3, d.weight * 0.8));

  // Nodes
  const node = g.append('g')
    .selectAll('circle')
    .data(data.nodes)
    .join('circle')
    .attr('r', d => d.type === 'topic' ? Math.max(12, Math.sqrt(d.size) * 3) : 3)
    .attr('fill', d => d.color || '#555')
    .attr('stroke', d => d.type === 'topic' ? 'rgba(255,255,255,0.2)' : 'none')
    .attr('stroke-width', d => d.type === 'topic' ? 2 : 0)
    .style('cursor', 'pointer')
    .on('mouseover', (event, d) => {
      tooltip
        .style('display', 'block')
        .html(`<strong>${d.label}</strong><br><span style="color:#9ca3af">${d.type}</span>`)
        .style('left', (event.pageX + 12) + 'px')
        .style('top', (event.pageY - 12) + 'px');

      d3.select(event.target)
        .transition().duration(150)
        .attr('r', d.type === 'topic' ? Math.max(16, Math.sqrt(d.size) * 3.5) : 6)
        .attr('stroke', 'rgba(255,255,255,0.5)')
        .attr('stroke-width', 2);
    })
    .on('mouseout', (event, d) => {
      tooltip.style('display', 'none');
      d3.select(event.target)
        .transition().duration(150)
        .attr('r', d.type === 'topic' ? Math.max(12, Math.sqrt(d.size) * 3) : 3)
        .attr('stroke', d.type === 'topic' ? 'rgba(255,255,255,0.2)' : 'none')
        .attr('stroke-width', d.type === 'topic' ? 2 : 0);
    })
    .on('click', (event, d) => {
      if (d.type === 'topic') {
        const topicSlug = d.id.replace(/^topic_/, '');
        // Find slug from label
        const s = d.label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 80);
        location.hash = `#/topics/${s}`;
      } else {
        // post_<urn_tail> → find URN
        const tail = d.id.replace('post_', '');
        // We'll need the full URN — construct it
        location.hash = `#/posts/urn:li:activity:${tail}`;
      }
    })
    .call(d3.drag()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on('drag', (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      })
    );

  // Topic labels
  const labels = g.append('g')
    .selectAll('text')
    .data(topicNodes)
    .join('text')
    .text(d => d.label)
    .attr('fill', '#e8e6e3')
    .attr('font-size', '10px')
    .attr('font-weight', '600')
    .attr('font-family', 'Inter, sans-serif')
    .attr('text-anchor', 'middle')
    .attr('dy', d => -(Math.max(12, Math.sqrt(d.size) * 3) + 8))
    .style('pointer-events', 'none')
    .style('text-shadow', '0 0 8px rgba(0,0,0,0.8)');

  // Tick
  simulation.on('tick', () => {
    link
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y);

    node
      .attr('cx', d => d.x)
      .attr('cy', d => d.y);

    labels
      .attr('x', d => d.x)
      .attr('y', d => d.y);
  });

  // Slow down simulation after initial layout
  setTimeout(() => simulation.alphaTarget(0).restart(), 3000);
}
