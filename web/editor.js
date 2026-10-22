(() => {
  "use strict";

  const TYPE_COLORS = {
    concept: "#58a6ff",
    law: "#f85149",
    formula: "#3fb950",
    method: "#d29922",
    application: "#a371f7",
    phenomenon: "#39c5cf",
  };
  const TYPE_LABELS = {
    concept: "概念",
    law: "定律",
    formula: "公式",
    method: "方法",
    application: "应用",
    phenomenon: "现象",
  };
  const REL_LABELS = {
    prerequisite: "先修",
    derives: "推导",
    related_to: "关联",
  };
  const REL_STYLES = {
    prerequisite: { color: "#8b949e", dash: "", arrow: true },
    derives: { color: "#58a6ff", dash: "7 5", arrow: true },
    related_to: { color: "#6e7681", dash: "", arrow: false },
  };

  const state = {
    graph: null,
    positions: new Map(),
    selection: null, // {type:'node'|'edge', id:string}
    merge: [],
    history: [],
    view: { x: 0, y: 0, k: 1 },
    filterChapter: "",
    search: "",
    drag: null,
    suppressClick: false,
  };

  const els = {};
  let svgNS = "http://www.w3.org/2000/svg";

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    els.fileInput = document.getElementById("file-input");
    els.exportBtn = document.getElementById("export-btn");
    els.layoutBtn = document.getElementById("layout-btn");
    els.search = document.getElementById("search-input");
    els.chapterFilter = document.getElementById("chapter-filter");
    els.stats = document.getElementById("stats");
    els.graphWrap = document.getElementById("graph-wrap");
    els.svg = document.getElementById("graph");
    els.emptyHint = document.getElementById("empty-hint");
    els.panel = document.getElementById("panel");
    els.addNodeBtn = document.getElementById("add-node-btn");
    els.addEdgeBtn = document.getElementById("add-edge-btn");
    els.mergeBtn = document.getElementById("merge-btn");
    els.undoBtn = document.getElementById("undo-btn");
    els.toast = document.getElementById("toast");

    els.fileInput.addEventListener("change", async (event) => {
      const file = event.target.files && event.target.files[0];
      if (file) await loadFile(file);
    });

    els.graphWrap.addEventListener("dragover", (event) => {
      event.preventDefault();
    });
    els.graphWrap.addEventListener("drop", async (event) => {
      event.preventDefault();
      const file = event.dataTransfer && event.dataTransfer.files[0];
      if (file) await loadFile(file);
    });

    els.exportBtn.addEventListener("click", exportGraph);
    els.layoutBtn.addEventListener("click", () => {
      state.positions.clear();
      layoutGraph();
      render();
      toast("已重新布局");
    });
    els.search.addEventListener("input", () => {
      state.search = els.search.value.trim();
      render();
    });
    els.chapterFilter.addEventListener("change", () => {
      state.filterChapter = els.chapterFilter.value;
      render();
    });
    els.addNodeBtn.addEventListener("click", addNode);
    els.addEdgeBtn.addEventListener("click", addEdge);
    els.mergeBtn.addEventListener("click", mergeSelected);
    els.undoBtn.addEventListener("click", undo);

    els.svg.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    els.svg.addEventListener("click", onGraphClick);
    els.svg.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("resize", () => {
      if (state.graph) {
        layoutGraph();
        render();
      }
    });
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        state.selection = null;
        state.merge = [];
        render();
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        undo();
      }
      if (event.key === "Delete" && state.selection) {
        if (state.selection.type === "node") deleteNode(state.selection.id);
        else deleteEdge(state.selection.id);
      }
    });
  }

  async function loadFile(file) {
    try {
      const text = await file.text();
      const graph = JSON.parse(text);
      if (!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) {
        throw new Error("不是有效的图谱文件：缺少 nodes / edges");
      }
      state.graph = graph;
      state.positions.clear();
      state.selection = null;
      state.merge = [];
      state.history = [];
      state.view = { x: 0, y: 0, k: 1 };
      state.filterChapter = "";
      state.search = "";
      els.search.value = "";
      els.emptyHint.classList.add("hidden");
      els.exportBtn.disabled = false;
      els.layoutBtn.disabled = false;
      els.search.disabled = false;
      els.chapterFilter.disabled = false;
      els.addNodeBtn.disabled = false;
      els.addEdgeBtn.disabled = false;
      els.undoBtn.disabled = true;
      buildChapterOptions();
      initPositions();
      layoutGraph();
      render();
      toast(`已加载 ${file.name}`);
    } catch (error) {
      console.error(error);
      toast(`加载失败：${error.message}`, "error");
    }
  }

  // ---------------------------------------------------------------- 章节

  function chapterMap() {
    const map = new Map();
    for (const chapter of state.graph.chapters || []) map.set(chapter.id, chapter);
    return map;
  }

  function chapterChildren() {
    const children = new Map();
    for (const chapter of state.graph.chapters || []) {
      const key = chapter.parent_id || null;
      if (!children.has(key)) children.set(key, []);
      children.get(key).push(chapter);
    }
    return children;
  }

  function chapterPath(id) {
    const map = chapterMap();
    const parts = [];
    let current = map.get(id);
    let guard = 0;
    while (current && guard < 20) {
      parts.unshift(current.title);
      current = current.parent_id ? map.get(current.parent_id) : null;
      guard += 1;
    }
    return parts.join(" / ") || id || "未分章";
  }

  function buildChapterOptions() {
    const children = chapterChildren();
    const options = ['<option value="">全部章节</option>'];
    const walk = (parentId, depth) => {
      const items = (children.get(parentId) || []).sort((a, b) => a.order - b.order);
      for (const chapter of items) {
        const prefix = "&nbsp;".repeat(depth * 3);
        options.push(
          `<option value="${escapeAttr(chapter.id)}">${prefix}${escapeHtml(chapter.title)}</option>`
        );
        walk(chapter.id, depth + 1);
      }
    };
    walk(null, 0);
    els.chapterFilter.innerHTML = options.join("");
    els.chapterFilter.value = state.filterChapter;
  }

  function visibleChapterIds() {
    if (!state.filterChapter) return null;
    const children = chapterChildren();
    const result = new Set();
    const stack = [state.filterChapter];
    while (stack.length) {
      const id = stack.pop();
      result.add(id);
      for (const child of children.get(id) || []) stack.push(child.id);
    }
    return result;
  }

  // ---------------------------------------------------------------- 布局

  function initPositions() {
    const W = Math.max(640, els.graphWrap.clientWidth);
    const H = Math.max(480, els.graphWrap.clientHeight);
    const nodes = state.graph.nodes;
    const radius = Math.min(W, H) * 0.34;
    nodes.forEach((node, index) => {
      if (state.positions.has(node.id)) return;
      const angle = (index / Math.max(1, nodes.length)) * Math.PI * 2;
      state.positions.set(node.id, {
        x: W / 2 + Math.cos(angle) * radius,
        y: H / 2 + Math.sin(angle) * radius,
      });
    });
  }

  function layoutGraph() {
    if (!state.graph) return;
    const W = Math.max(640, els.graphWrap.clientWidth);
    const H = Math.max(480, els.graphWrap.clientHeight);
    const nodes = state.graph.nodes;
    if (!nodes.length) return;

    const index = new Map();
    nodes.forEach((node, i) => index.set(node.id, i));
    const xs = new Float64Array(nodes.length);
    const ys = new Float64Array(nodes.length);

    nodes.forEach((node, i) => {
      const pos = state.positions.get(node.id);
      xs[i] = pos ? pos.x : W / 2 + Math.cos((i / nodes.length) * Math.PI * 2) * 220;
      ys[i] = pos ? pos.y : H / 2 + Math.sin((i / nodes.length) * Math.PI * 2) * 220;
    });

    const edges = [];
    for (const edge of state.graph.edges) {
      const s = index.get(edge.source);
      const t = index.get(edge.target);
      if (s !== undefined && t !== undefined && s !== t) edges.push([s, t]);
    }

    const n = nodes.length;
    const repulsion = 22000;
    const spring = 0.012;
    const springLength = 120;
    const gravity = 0.0025;
    const iterations = n > 80 ? 220 : 320;

    for (let iter = 0; iter < iterations; iter++) {
      const fx = new Float64Array(n);
      const fy = new Float64Array(n);

      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          let dx = xs[i] - xs[j];
          let dy = ys[i] - ys[j];
          let dist2 = dx * dx + dy * dy;
          if (dist2 < 1) {
            dx = (Math.random() - 0.5) * 2;
            dy = (Math.random() - 0.5) * 2;
            dist2 = dx * dx + dy * dy + 1;
          }
          const dist = Math.sqrt(dist2);
          const force = repulsion / dist2;
          const ux = dx / dist;
          const uy = dy / dist;
          fx[i] += ux * force;
          fy[i] += uy * force;
          fx[j] -= ux * force;
          fy[j] -= uy * force;
        }
      }

      for (const [s, t] of edges) {
        const dx = xs[t] - xs[s];
        const dy = ys[t] - ys[s];
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (dist - springLength) * spring;
        const ux = dx / dist;
        const uy = dy / dist;
        fx[s] += ux * force;
        fy[s] += uy * force;
        fx[t] -= ux * force;
        fy[t] -= uy * force;
      }

      for (let i = 0; i < n; i++) {
        fx[i] += (W / 2 - xs[i]) * gravity;
        fy[i] += (H / 2 - ys[i]) * gravity;
        xs[i] = Math.max(40, Math.min(W - 40, xs[i] + fx[i]));
        ys[i] = Math.max(40, Math.min(H - 40, ys[i] + fy[i]));
      }
    }

    nodes.forEach((node, i) => state.positions.set(node.id, { x: xs[i], y: ys[i] }));
  }

  // ---------------------------------------------------------------- 渲染

  function render() {
    if (!state.graph) return;
    updateStats();
    renderGraph();
    renderSidebar();
    els.mergeBtn.disabled = state.merge.length !== 2;
    els.undoBtn.disabled = state.history.length === 0;
  }

  function updateStats() {
    const graph = state.graph;
    const counts = {};
    for (const node of graph.nodes) counts[node.type] = (counts[node.type] || 0) + 1;
    const parts = Object.entries(TYPE_LABELS)
      .filter(([key]) => counts[key])
      .map(([key, label]) => `${label} ${counts[key]}`);
    els.stats.textContent = `${graph.nodes.length} 节点 / ${graph.edges.length} 边 · ${parts.join(" · ")}`;
  }

  function renderGraph() {
    const W = Math.max(640, els.graphWrap.clientWidth);
    const H = Math.max(480, els.graphWrap.clientHeight);
    els.svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

    const visibleChapters = visibleChapterIds();
    const visible = new Set();
    for (const node of state.graph.nodes) {
      const chapterOk = !visibleChapters || visibleChapters.has(node.chapter);
      if (!chapterOk) continue;
      const text = `${node.name || ""} ${node.id || ""} ${(node.aliases || []).join(" ")}`.toLowerCase();
      const searchOk = !state.search || text.includes(state.search.toLowerCase());
      visible.add(node.id);
      node.__dim = !searchOk;
    }

    const degree = new Map();
    for (const edge of state.graph.edges) {
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
    }

    while (els.svg.firstChild) els.svg.removeChild(els.svg.firstChild);

    const defs = svgEl("defs");
    defs.appendChild(marker("arrow-prereq", "#8b949e"));
    defs.appendChild(marker("arrow-derives", "#58a6ff"));
    els.svg.appendChild(defs);

    const viewport = svgEl("g", { id: "viewport" });
    viewport.setAttribute("transform", `translate(${state.view.x},${state.view.y}) scale(${state.view.k})`);
    els.svg.appendChild(viewport);

    const edgeLayer = svgEl("g");
    const nodeLayer = svgEl("g");
    viewport.appendChild(edgeLayer);
    viewport.appendChild(nodeLayer);

    for (const edge of state.graph.edges) {
      if (!visible.has(edge.source) || !visible.has(edge.target)) continue;
      const a = state.positions.get(edge.source);
      const b = state.positions.get(edge.target);
      if (!a || !b) continue;
      const style = REL_STYLES[edge.relation] || REL_STYLES.related_to;
      const selected = state.selection && state.selection.type === "edge" && state.selection.id === edge.id;
      const line = svgEl("line", {
        x1: a.x,
        y1: a.y,
        x2: b.x,
        y2: b.y,
        stroke: selected ? "#2f81f7" : style.color,
        "stroke-width": selected ? 2.8 : 1.4,
        "stroke-dasharray": style.dash,
        "marker-end": style.arrow ? `url(#arrow-${edge.relation === "derives" ? "derives" : "prereq"})` : "",
        "data-edge-key": edge.id,
        class: "edge-line",
      });
      const hit = svgEl("line", {
        x1: a.x,
        y1: a.y,
        x2: b.x,
        y2: b.y,
        stroke: "transparent",
        "stroke-width": 14,
        "data-edge-key": edge.id,
      });
      edgeLayer.appendChild(line);
      edgeLayer.appendChild(hit);
    }

    for (const node of state.graph.nodes) {
      if (!visible.has(node.id)) continue;
      const pos = state.positions.get(node.id);
      if (!pos) continue;
      const radius = Math.min(22, 8 + Math.sqrt(degree.get(node.id) || 0) * 2.6);
      const selected = state.selection && state.selection.type === "node" && state.selection.id === node.id;
      const mergeSelected = state.merge.includes(node.id);
      const group = svgEl("g", {
        transform: `translate(${pos.x},${pos.y})`,
        "data-node-id": node.id,
        class: node.__dim ? "node dim" : "node",
      });
      group.style.cursor = "pointer";

      const circle = svgEl("circle", {
        r: radius,
        fill: TYPE_COLORS[node.type] || "#8b949e",
        "fill-opacity": 0.88,
        stroke: mergeSelected ? "#d29922" : selected ? "#ffffff" : "#0d1117",
        "stroke-width": mergeSelected || selected ? 3 : 2,
        "stroke-dasharray": mergeSelected ? "4 3" : "",
      });
      group.appendChild(circle);

      const label = svgEl("text", {
        x: 0,
        y: radius + 14,
        "text-anchor": "middle",
        class: node.__dim ? "node-label dim" : "node-label",
      });
      label.textContent = shortName(node.name || node.id);
      group.appendChild(label);

      nodeLayer.appendChild(group);
    }

    els.emptyHint.classList.toggle("hidden", state.graph.nodes.length > 0);
  }

  function marker(id, color) {
    const mark = svgEl("marker", {
      id,
      viewBox: "0 0 10 10",
      refX: 9,
      refY: 5,
      markerWidth: 7,
      markerHeight: 7,
      orient: "auto-start-reverse",
    });
    mark.appendChild(svgEl("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: color }));
    return mark;
  }

  function svgEl(name, attrs = {}) {
    const node = document.createElementNS(svgNS, name);
    for (const [key, value] of Object.entries(attrs)) {
      if (value !== undefined && value !== null && value !== "") node.setAttribute(key, value);
    }
    return node;
  }

  function shortName(name) {
    const value = String(name || "");
    return value.length > 12 ? value.slice(0, 11) + "…" : value;
  }

  // ---------------------------------------------------------------- 交互

  function onGraphClick(event) {
    if (state.suppressClick) {
      state.suppressClick = false;
      return;
    }
    const edgeEl = event.target.closest("[data-edge-key]");
    if (edgeEl) {
      selectEdge(edgeEl.getAttribute("data-edge-key"));
      return;
    }
    const nodeEl = event.target.closest("[data-node-id]");
    if (nodeEl) selectNode(nodeEl.getAttribute("data-node-id"), event.ctrlKey || event.metaKey);
  }

  function onPointerDown(event) {
    if (!state.graph) return;
    const nodeEl = event.target.closest("[data-node-id]");
    if (nodeEl) {
      const id = nodeEl.getAttribute("data-node-id");
      const pos = state.positions.get(id);
      if (!pos) return;
      state.drag = {
        kind: "node",
        id,
        startX: event.clientX,
        startY: event.clientY,
        origX: pos.x,
        origY: pos.y,
        moved: false,
      };
      return;
    }
    if (event.target.closest("[data-edge-key]")) return;
    state.drag = {
      kind: "pan",
      startX: event.clientX,
      startY: event.clientY,
      origX: state.view.x,
      origY: state.view.y,
      moved: false,
    };
    els.svg.classList.add("dragging");
  }

  function onPointerMove(event) {
    if (!state.drag) return;
    const drag = state.drag;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    if (drag.kind === "node") {
      const pos = state.positions.get(drag.id);
      if (!pos) return;
      pos.x = drag.origX + dx / state.view.k;
      pos.y = drag.origY + dy / state.view.k;
      renderGraph();
    } else {
      state.view.x = drag.origX + dx;
      state.view.y = drag.origY + dy;
      const viewport = els.svg.querySelector("#viewport");
      if (viewport) {
        viewport.setAttribute(
          "transform",
          `translate(${state.view.x},${state.view.y}) scale(${state.view.k})`
        );
      }
    }
  }

  function onPointerUp() {
    const drag = state.drag;
    state.drag = null;
    els.svg.classList.remove("dragging");
    if (!drag) return;
    if (drag.moved) {
      state.suppressClick = true;
      setTimeout(() => {
        state.suppressClick = false;
      }, 60);
      if (drag.kind === "node") render();
    }
  }

  function onWheel(event) {
    if (!state.graph) return;
    event.preventDefault();
    const rect = els.svg.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const worldX = (px - state.view.x) / state.view.k;
    const worldY = (py - state.view.y) / state.view.k;
    const factor = Math.exp(-event.deltaY * 0.0012);
    const next = Math.max(0.35, Math.min(3, state.view.k * factor));
    state.view.k = next;
    state.view.x = px - worldX * next;
    state.view.y = py - worldY * next;
    const viewport = els.svg.querySelector("#viewport");
    if (viewport) {
      viewport.setAttribute(
        "transform",
        `translate(${state.view.x},${state.view.y}) scale(${state.view.k})`
      );
    }
  }

  function selectNode(id, additive) {
    const node = state.graph.nodes.find((item) => item.id === id);
    if (!node) return;
    if (additive) {
      if (state.merge.includes(id)) {
        state.merge = state.merge.filter((item) => item !== id);
      } else {
        state.merge.push(id);
        if (state.merge.length > 2) state.merge.shift();
      }
      state.selection = { type: "node", id };
    } else {
      state.selection = { type: "node", id };
      state.merge = [id];
    }
    render();
  }

  function selectEdge(id) {
    const edge = state.graph.edges.find((item) => item.id === id);
    if (!edge) return;
    state.selection = { type: "edge", id };
    state.merge = [];
    render();
  }

  // ---------------------------------------------------------------- 侧栏

  function renderSidebar() {
    if (!state.graph) return;
    if (state.selection && state.selection.type === "node") {
      const node = state.graph.nodes.find((item) => item.id === state.selection.id);
      if (node) return renderNodePanel(node);
    }
    if (state.selection && state.selection.type === "edge") {
      const edge = state.graph.edges.find((item) => item.id === state.selection.id);
      if (edge) return renderEdgePanel(edge);
    }
    renderOverview();
  }

  function renderOverview() {
    const nodes = state.graph.nodes
      .filter((node) => {
        if (!state.search) return true;
        const text = `${node.name} ${node.id} ${(node.aliases || []).join(" ")}`.toLowerCase();
        return text.includes(state.search.toLowerCase());
      })
      .slice(0, 40);

    els.panel.innerHTML = `
      <h2>图谱概览 <span class="badge">${state.graph.nodes.length} 节点</span></h2>
      <p class="muted" style="margin-top:-4px">点击节点或边进行审核；Ctrl+点击两个节点可合并。</p>
      <div class="list">
        ${nodes
          .map(
            (node) => `
          <div class="list-item" data-select-node="${escapeAttr(node.id)}">
            <span>${escapeHtml(node.name)}</span>
            <span class="meta">${TYPE_LABELS[node.type] || node.type}</span>
          </div>`
          )
          .join("")}
      </div>
      ${
        state.graph.nodes.length > nodes.length
          ? `<p class="muted">仅显示前 ${nodes.length} 个，可用搜索缩小范围。</p>`
          : ""
      }
    `;
    els.panel.querySelectorAll("[data-select-node]").forEach((item) => {
      item.addEventListener("click", () => selectNode(item.getAttribute("data-select-node"), false));
    });
  }

  function renderNodePanel(node) {
    const chapters = (state.graph.chapters || [])
      .map(
        (chapter) =>
          `<option value="${escapeAttr(chapter.id)}" ${
            chapter.id === node.chapter ? "selected" : ""
          }>${escapeHtml(chapterPath(chapter.id))}</option>`
      )
      .join("");
    const types = Object.entries(TYPE_LABELS)
      .map(
        ([value, label]) =>
          `<option value="${value}" ${node.type === value ? "selected" : ""}>${label} (${value})</option>`
      )
      .join("");
    const evidence = (node.evidence_ids || [])
      .map((id) => state.graph.evidence.find((item) => item.id === id))
      .filter(Boolean);
    const review = node.review || {};

    els.panel.innerHTML = `
      <h2>节点 <span class="badge">${escapeHtml(node.id)}</span></h2>
      <div class="field"><label>名称</label><input id="f-name" type="text" value="${escapeAttr(node.name)}" /></div>
      <div class="field"><label>类型</label><select id="f-type">${types}</select></div>
      <div class="field"><label>章节</label><select id="f-chapter">${chapters}</select></div>
      <div class="field"><label>描述</label><textarea id="f-desc">${escapeHtml(node.description || "")}</textarea></div>
      <div class="field"><label>别名（逗号分隔）</label><input id="f-aliases" type="text" value="${escapeAttr((node.aliases || []).join("，"))}" /></div>
      <div class="field"><label>LaTeX 公式（仅 formula 类型）</label><input id="f-formula" type="text" value="${escapeAttr(node.formula_latex || "")}" /></div>
      <div class="field"><label>适用条件（每行一条）</label><textarea id="f-conditions">${escapeHtml((node.conditions || []).join("\n"))}</textarea></div>
      <div class="field"><label>证据</label>
        <div class="evidence-list">
          ${
            evidence.length
              ? evidence
                  .map(
                    (item) => `<div class="evidence">${escapeHtml(item.id)} · ${escapeHtml(
                      item.locator ? item.locator.section || "" : ""
                    )}<q>${escapeHtml((item.quote || "").slice(0, 220))}</q></div>`
                  )
                  .join("")
              : '<div class="evidence">暂无证据</div>'
          }
        </div>
      </div>
      <div class="field"><label>审核状态</label><div class="row">
        <select id="f-review">
          <option value="pending" ${review.status === "pending" ? "selected" : ""}>pending</option>
          <option value="approved" ${review.status === "approved" ? "selected" : ""}>approved</option>
          <option value="rejected" ${review.status === "rejected" ? "selected" : ""}>rejected</option>
        </select>
      </div></div>
      <div class="actions">
        <button id="save-node" class="button primary">保存</button>
        <button id="delete-node" class="button danger">删除节点</button>
      </div>
    `;

    document.getElementById("save-node").addEventListener("click", () => saveNode(node.id));
    document.getElementById("delete-node").addEventListener("click", () => deleteNode(node.id));
  }

  function saveNode(id) {
    const node = state.graph.nodes.find((item) => item.id === id);
    if (!node) return;
    const name = document.getElementById("f-name").value.trim();
    const type = document.getElementById("f-type").value;
    const chapter = document.getElementById("f-chapter").value;
    const description = document.getElementById("f-desc").value.trim();
    const aliases = document
      .getElementById("f-aliases")
      .value.split(/[，,]/)
      .map((item) => item.trim())
      .filter(Boolean);
    const formula = document.getElementById("f-formula").value.trim();
    const conditions = document
      .getElementById("f-conditions")
      .value.split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
    const reviewStatus = document.getElementById("f-review").value;

    if (!name) return toast("名称不能为空", "error");
    if (!description) return toast("描述不能为空", "error");
    if (type === "formula" && !formula) return toast("formula 节点必须填写 LaTeX 公式", "error");
    if (type !== "formula" && formula) return toast("非 formula 节点的公式必须留空", "error");

    pushHistory();
    node.name = name;
    node.type = type;
    node.chapter = chapter;
    node.description = description;
    node.aliases = aliases;
    node.formula_latex = type === "formula" ? formula : null;
    node.conditions = [...new Set(conditions)];
    applyReview(node, reviewStatus);
    render();
    toast("节点已保存", "ok");
  }

  function applyReview(item, status) {
    if (status === "approved" || status === "rejected") {
      item.review = {
        status,
        reviewer_id: "editor",
        reviewed_at: state.graph.created_at,
        note: status === "rejected" ? "审核界面标记为 rejected" : null,
      };
    } else {
      item.review = { status: "pending", reviewer_id: null, reviewed_at: null, note: null };
    }
  }

  function renderEdgePanel(edge) {
    const options = state.graph.nodes
      .map(
        (node) =>
          `<option value="${escapeAttr(node.id)}" ${node.id === edge.source ? "selected" : ""}>${escapeHtml(
            node.name
          )} (${escapeHtml(node.id)})</option>`
      )
      .join("");
    const targetOptions = state.graph.nodes
      .map(
        (node) =>
          `<option value="${escapeAttr(node.id)}" ${node.id === edge.target ? "selected" : ""}>${escapeHtml(
            node.name
          )} (${escapeHtml(node.id)})</option>`
      )
      .join("");
    const evidence = (edge.evidence_ids || [])
      .map((id) => state.graph.evidence.find((item) => item.id === id))
      .filter(Boolean);

    els.panel.innerHTML = `
      <h2>关系 <span class="badge">${escapeHtml(edge.id)}</span></h2>
      <div class="field"><label>起点</label><select id="e-source">${options}</select></div>
      <div class="field"><label>终点</label><select id="e-target">${targetOptions}</select></div>
      <div class="field"><label>关系类型</label>
        <select id="e-relation">
          ${Object.entries(REL_LABELS)
            .map(
              ([value, label]) =>
                `<option value="${value}" ${edge.relation === value ? "selected" : ""}>${label} (${value})</option>`
            )
            .join("")}
        </select>
      </div>
      <div class="field"><label>描述</label><textarea id="e-desc">${escapeHtml(edge.description || "")}</textarea></div>
      <div class="field"><label>证据</label>
        <div class="evidence-list">
          ${
            evidence.length
              ? evidence
                  .map(
                    (item) => `<div class="evidence">${escapeHtml(item.id)}<q>${escapeHtml(
                      (item.quote || "").slice(0, 220)
                    )}</q></div>`
                  )
                  .join("")
              : '<div class="evidence">暂无证据</div>'
          }
        </div>
      </div>
      <div class="field"><label>审核状态</label>
        <select id="e-review">
          <option value="pending" ${edge.review && edge.review.status === "pending" ? "selected" : ""}>pending</option>
          <option value="approved" ${edge.review && edge.review.status === "approved" ? "selected" : ""}>approved</option>
          <option value="rejected" ${edge.review && edge.review.status === "rejected" ? "selected" : ""}>rejected</option>
        </select>
      </div>
      <div class="actions">
        <button id="save-edge" class="button primary">保存</button>
        <button id="delete-edge" class="button danger">删除边</button>
      </div>
    `;

    document.getElementById("save-edge").addEventListener("click", () => saveEdge(edge.id));
    document.getElementById("delete-edge").addEventListener("click", () => deleteEdge(edge.id));
  }

  function saveEdge(id) {
    const edge = state.graph.edges.find((item) => item.id === id);
    if (!edge) return;
    let source = document.getElementById("e-source").value;
    let target = document.getElementById("e-target").value;
    const relation = document.getElementById("e-relation").value;
    const description = document.getElementById("e-desc").value.trim();
    const reviewStatus = document.getElementById("e-review").value;

    if (source === target) return toast("起点和终点不能相同", "error");
    if (!description) return toast("描述不能为空", "error");
    if (relation === "related_to" && source > target) [source, target] = [target, source];

    const duplicate = state.graph.edges.some((item) => {
      if (item.id === id) return false;
      if (item.relation !== relation) return false;
      if (relation === "related_to") {
        return (
          (item.source === source && item.target === target) ||
          (item.source === target && item.target === source)
        );
      }
      return item.source === source && item.target === target;
    });
    if (duplicate) return toast("已存在相同的关系", "error");

    pushHistory();
    edge.source = source;
    edge.target = target;
    edge.relation = relation;
    edge.description = description;
    applyReview(edge, reviewStatus);
    render();
    toast("关系已保存", "ok");
  }

  // ---------------------------------------------------------------- 增删合并

  function addNode() {
    if (!state.graph) return;
    const name = window.prompt("节点名称");
    if (!name) return;
    const type = window.prompt("类型：concept / law / formula / method / application / phenomenon", "concept");
    if (!type || !TYPE_LABELS[type]) return toast("类型不合法", "error");
    const chapter =
      window.prompt("章节 ID（可从左侧下拉查看）", state.filterChapter || state.graph.chapters[0]?.id || "") || "";
    if (!state.graph.chapters.some((item) => item.id === chapter)) return toast("章节 ID 不存在", "error");
    const description = window.prompt("描述", `待补充：${name}`) || `待补充：${name}`;
    let formula = null;
    if (type === "formula") {
      formula = window.prompt("LaTeX 公式（不要 $ 定界符）", "");
      if (!formula) return toast("formula 节点必须填写公式", "error");
    }
    const evidence = (state.graph.evidence || [])[0];
    if (!evidence) return toast("图谱没有 evidence，无法新增节点", "error");

    let index = 1;
    while (state.graph.nodes.some((node) => node.id === `manual_${index}`)) index += 1;
    const node = {
      id: `manual_${index}`,
      name,
      type,
      description,
      chapter,
      aliases: [],
      formula_latex: type === "formula" ? formula : null,
      conditions: [],
      evidence_ids: [evidence.id],
      review: { status: "pending", reviewer_id: null, reviewed_at: null, note: null },
      extensions: {},
    };
    pushHistory();
    state.graph.nodes.push(node);
    state.selection = { type: "node", id: node.id };
    state.merge = [node.id];
    render();
    toast("已新增节点（默认引用第一条证据，请补充准确证据）", "ok");
  }

  function addEdge() {
    if (!state.graph) return;
    const nodeIds = state.graph.nodes.map((node) => node.id);
    if (nodeIds.length < 2) return toast("至少需要两个节点", "error");
    const source = window.prompt("起点节点 ID", state.selection?.type === "node" ? state.selection.id : nodeIds[0]);
    if (!source || !nodeIds.includes(source)) return toast("起点不存在", "error");
    const target = window.prompt("终点节点 ID", nodeIds.find((id) => id !== source));
    if (!target || !nodeIds.includes(target)) return toast("终点不存在", "error");
    if (source === target) return toast("起点和终点不能相同", "error");
    const relation = window.prompt("关系：prerequisite / derives / related_to", "related_to");
    if (!relation || !REL_LABELS[relation]) return toast("关系类型不合法", "error");
    const description = window.prompt("关系描述", "人工补充的关系") || "人工补充的关系";
    const evidence = (state.graph.evidence || [])[0];
    if (!evidence) return toast("图谱没有 evidence，无法新增边", "error");

    let first = source;
    let second = target;
    if (relation === "related_to" && first > second) [first, second] = [second, first];
    const duplicate = state.graph.edges.some((edge) => {
      if (edge.relation !== relation) return false;
      if (relation === "related_to") {
        return (edge.source === first && edge.target === second) || (edge.source === second && edge.target === first);
      }
      return edge.source === first && edge.target === second;
    });
    if (duplicate) return toast("已存在相同的关系", "error");

    let index = 1;
    while (state.graph.edges.some((edge) => edge.id === `edge_manual_${index}`)) index += 1;
    const edge = {
      id: `edge_manual_${index}`,
      source: first,
      target: second,
      relation,
      description,
      evidence_ids: [evidence.id],
      review: { status: "pending", reviewer_id: null, reviewed_at: null, note: null },
      extensions: {},
    };
    pushHistory();
    state.graph.edges.push(edge);
    state.selection = { type: "edge", id: edge.id };
    render();
    toast("已新增边（默认引用第一条证据）", "ok");
  }

  function deleteNode(id) {
    const node = state.graph.nodes.find((item) => item.id === id);
    if (!node) return;
    if (!window.confirm(`确定删除节点“${node.name}”及其所有关联边吗？`)) return;
    pushHistory();
    state.graph.nodes = state.graph.nodes.filter((item) => item.id !== id);
    state.graph.edges = state.graph.edges.filter((edge) => edge.source !== id && edge.target !== id);
    state.graph.item_mappings = (state.graph.item_mappings || [])
      .map((mapping) => ({
        ...mapping,
        skill_ids: (mapping.skill_ids || []).filter((skillId) => skillId !== id),
      }))
      .filter((mapping) => mapping.skill_ids.length > 0);
    if (state.graph.redirects) {
      for (const [oldId, newId] of Object.entries(state.graph.redirects)) {
        if (newId === id) delete state.graph.redirects[oldId];
      }
      delete state.graph.redirects[id];
    }
    state.selection = null;
    state.merge = [];
    render();
    toast("节点已删除");
  }

  function deleteEdge(id) {
    const edge = state.graph.edges.find((item) => item.id === id);
    if (!edge) return;
    if (!window.confirm("确定删除这条关系吗？")) return;
    pushHistory();
    state.graph.edges = state.graph.edges.filter((item) => item.id !== id);
    state.selection = null;
    render();
    toast("关系已删除");
  }

  function mergeSelected() {
    if (state.merge.length !== 2) return toast("请先 Ctrl+点击两个节点", "error");
    const [keepId, mergeId] = state.merge;
    const keep = state.graph.nodes.find((item) => item.id === keepId);
    const merged = state.graph.nodes.find((item) => item.id === mergeId);
    if (!keep || !merged) return;
    if (!window.confirm(`把“${merged.name}”合并进“${keep.name}”？合并后保留前者。`)) return;

    pushHistory();
    if (merged.name && merged.name !== keep.name && !(keep.aliases || []).includes(merged.name)) {
      keep.aliases = [...(keep.aliases || []), merged.name];
    }
    keep.aliases = [...new Set([...(keep.aliases || []), ...(merged.aliases || [])])].filter(
      (alias) => alias !== keep.name
    );
    keep.evidence_ids = [...new Set([...(keep.evidence_ids || []), ...(merged.evidence_ids || [])])];
    keep.conditions = [...new Set([...(keep.conditions || []), ...(merged.conditions || [])])];

    const seen = new Set();
    const edges = [];
    for (const edge of state.graph.edges) {
      let source = edge.source === mergeId ? keepId : edge.source;
      let target = edge.target === mergeId ? keepId : edge.target;
      if (source === target) continue;
      if (edge.relation === "related_to" && source > target) [source, target] = [target, source];
      const key = edge.relation === "related_to" ? `related_to|${[source, target].sort().join("|")}` : `${edge.relation}|${source}|${target}`;
      if (seen.has(key)) continue;
      seen.add(key);
      edge.source = source;
      edge.target = target;
      edges.push(edge);
    }
    state.graph.edges = edges;
    state.graph.nodes = state.graph.nodes.filter((item) => item.id !== mergeId);
    state.graph.item_mappings = (state.graph.item_mappings || [])
      .map((mapping) => ({
        ...mapping,
        skill_ids: [
          ...new Set((mapping.skill_ids || []).map((skillId) => (skillId === mergeId ? keepId : skillId))),
        ],
      }))
      .filter((mapping) => mapping.skill_ids.length > 0);

    state.graph.redirects = state.graph.redirects || {};
    for (const [oldId, newId] of Object.entries(state.graph.redirects)) {
      if (newId === mergeId) state.graph.redirects[oldId] = keepId;
    }
    state.graph.redirects[mergeId] = keepId;

    state.selection = { type: "node", id: keepId };
    state.merge = [keepId];
    render();
    toast("合并完成", "ok");
  }

  // ---------------------------------------------------------------- 导出

  function validateGraph(graph) {
    const issues = [];
    const nodeIds = new Set();
    const chapterIds = new Set((graph.chapters || []).map((item) => item.id));
    const evidenceIds = new Set((graph.evidence || []).map((item) => item.id));

    for (const node of graph.nodes) {
      if (nodeIds.has(node.id)) issues.push(`节点 ID 重复：${node.id}`);
      nodeIds.add(node.id);
      if (!node.name) issues.push(`节点 ${node.id} 缺少名称`);
      if (!TYPE_LABELS[node.type]) issues.push(`节点 ${node.id} 类型不合法`);
      if (!chapterIds.has(node.chapter)) issues.push(`节点 ${node.id} 章节不存在`);
      if (!node.evidence_ids || !node.evidence_ids.length) issues.push(`节点 ${node.id} 没有证据`);
      for (const evidenceId of node.evidence_ids || []) {
        if (!evidenceIds.has(evidenceId)) issues.push(`节点 ${node.id} 引用不存在的证据 ${evidenceId}`);
      }
      if (node.type === "formula" && !node.formula_latex) issues.push(`公式节点 ${node.id} 缺少 formula_latex`);
      if (node.type !== "formula" && node.formula_latex) issues.push(`非公式节点 ${node.id} 不应有 formula_latex`);
    }

    const edgeKeys = new Set();
    for (const edge of graph.edges) {
      if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) issues.push(`边 ${edge.id} 端点不存在`);
      if (edge.source === edge.target) issues.push(`边 ${edge.id} 是自环`);
      if (!REL_LABELS[edge.relation]) issues.push(`边 ${edge.id} 关系类型不合法`);
      if (edge.relation === "related_to" && edge.source > edge.target) {
        issues.push(`边 ${edge.id} 的 related_to 未按升序存储`);
      }
      if (!edge.evidence_ids || !edge.evidence_ids.length) issues.push(`边 ${edge.id} 没有证据`);
      const key =
        edge.relation === "related_to"
          ? `related_to|${[edge.source, edge.target].sort().join("|")}`
          : `${edge.relation}|${edge.source}|${edge.target}`;
      if (edgeKeys.has(key)) issues.push(`边 ${edge.id} 与其他边重复`);
      edgeKeys.add(key);
    }

    for (const [oldId, newId] of Object.entries(graph.redirects || {})) {
      if (nodeIds.has(oldId)) issues.push(`redirects 的旧 ID ${oldId} 仍在 nodes 中`);
      if (!nodeIds.has(newId)) issues.push(`redirects 目标 ${newId} 不存在`);
      if ((graph.redirects || {})[newId]) issues.push(`redirects 成链：${oldId} → ${newId}`);
    }
    return issues;
  }

  function exportGraph() {
    if (!state.graph) return;
    const issues = validateGraph(state.graph);
    if (issues.length) {
      const preview = issues.slice(0, 12).join("\n");
      const proceed = window.confirm(
        `发现 ${issues.length} 个问题：\n\n${preview}\n\n仍然导出吗？导出后可用 validate_graph.py 再校验。`
      );
      if (!proceed) return;
    }
    const payload = JSON.parse(JSON.stringify(state.graph));
    for (const node of payload.nodes || []) delete node.__dim;
    const blob = new Blob([JSON.stringify(payload, null, 2) + "\n"], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "graph.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    toast(issues.length ? "已导出（仍有问题，请再校验）" : "已导出 graph.json", issues.length ? "error" : "ok");
  }

  // ---------------------------------------------------------------- 历史 / 工具

  function pushHistory() {
    state.history.push(JSON.stringify(state.graph));
    if (state.history.length > 30) state.history.shift();
  }

  function undo() {
    if (!state.history.length) return;
    state.graph = JSON.parse(state.history.pop());
    state.selection = null;
    state.merge = [];
    render();
    toast("已撤销");
  }

  function toast(message, kind = "") {
    els.toast.textContent = message;
    els.toast.className = `toast show ${kind}`;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
      els.toast.className = "toast";
    }, 2600);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replaceAll("\n", " ");
  }
})();
