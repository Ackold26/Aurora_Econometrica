<script>
  /**
   * @type {{
   *   steps: Array<any>,
   *   onStepClick?: (step: any) => void,
   *   onRemoveStep?: (stepId: string) => void
   * }}
   */
  let { steps = [], onStepClick, onRemoveStep } = $props();

  let panX = $state(60);
  let panY = $state(40);
  let zoom = $state(1);
  let isPanning = $state(false);
  let panStartX = $state(0);
  let panStartY = $state(0);
  let spaceHeld = $state(false);

  /** @type {any} */
  let draggingNodeId = $state(null);
  let dragOffsetX = $state(0);
  let dragOffsetY = $state(0);

  /** @type {any} */
  let drawingFrom = $state(null);
  let mouseX = $state(0);
  let mouseY = $state(0);

  /** @type {any} */
  let selectedNodeId = $state(null);

  const NODE_W = 220;
  const NODE_H = 64;
  const H_GAP = 80;
  const V_GAP = 48;

  /** @type {Map<string, {id: string, x: number, y: number, label: string, cabinetId: string, command: string|null, status: string, stepType: string}>} */
  let nodeMap = $state(new Map());
  /** @type {Array<{id: string, from: string, to: string, label: string}>} */
  let edges = $state([]);
  /** @type {Map<string, {x: number, y: number}>} */
  let positionOverrides = $state(new Map());

  import { getMeta } from './cabinetMeta.js';

  $effect(() => {
    const nm = new Map();
    /** @type {Array<{id: string, from: string, to: string, label: string}>} */
    const ed = [];

    /**
     * @param {Array<any>} items
     * @param {number} startCol
     * @param {number} row
     * @param {string|null} prevId
     * @returns {string|null}
     */
    function layout(items, startCol, row, prevId) {
      let currentCol = startCol;
      let lastId = prevId;

      for (const step of items) {
        if (step.type === 'single') {
          const override = positionOverrides.get(step.id);
          const x = override?.x ?? currentCol * (NODE_W + H_GAP);
          const y = override?.y ?? row * (NODE_H + V_GAP);
          nm.set(step.id, {
            id: step.id, x, y,
            label: step.label,
            cabinetId: step.cabinet_id,
            command: step.command,
            status: step.status || 'idle',
            stepType: 'single',
          });
          if (lastId) {
            ed.push({ id: `e-${lastId}-${step.id}`, from: lastId, to: step.id, label: '' });
          }
          lastId = step.id;
          currentCol++;
        } else if (step.type === 'parallel') {
          const branchLastIds = [];
          let maxCols = 0;
          for (let bi = 0; bi < step.branches.length; bi++) {
            const branchLast = layout(step.branches[bi], currentCol, row + bi, null);
            if (branchLast) branchLastIds.push(branchLast);
            const firstInBranch = step.branches[bi]?.[0];
            if (lastId && firstInBranch) {
              ed.push({ id: `e-fork-${lastId}-${firstInBranch.id}`, from: lastId, to: firstInBranch.id, label: '' });
            }
            maxCols = Math.max(maxCols, step.branches[bi].length);
          }
          currentCol += maxCols;
          lastId = branchLastIds[0] || lastId;
          for (let k = 1; k < branchLastIds.length; k++) {
            ed.push({ id: `e-join-${branchLastIds[k]}-deferred`, from: branchLastIds[k], to: '__NEXT__', label: '' });
          }
        } else if (step.type === 'loop') {
          const bodyLast = layout(step.body, currentCol, row, lastId);
          const bodyLen = step.body.length;
          const reviewLast = layout(step.review, currentCol, row + 1, bodyLast);
          const firstBody = step.body[0];
          if (reviewLast && firstBody) {
            ed.push({ id: `e-loop-${step.id}`, from: reviewLast, to: firstBody.id, label: `x${step.max_iterations}` });
          }
          currentCol += Math.max(bodyLen, step.review.length);
          lastId = reviewLast || bodyLast;
        }
      }
      return lastId;
    }

    layout(steps, 0, 0, null);

    for (const edge of ed) {
      if (edge.to === '__NEXT__') {
        const fromNode = nm.get(edge.from);
        if (!fromNode) continue;
        let closestId = null;
        let closestX = Infinity;
        for (const [nid, n] of nm) {
          if (n.x > fromNode.x + NODE_W && n.x < closestX) {
            closestX = n.x;
            closestId = nid;
          }
        }
        if (closestId) {
          edge.to = closestId;
          edge.id = `e-join-${edge.from}-${closestId}`;
        }
      }
    }

    nodeMap = nm;
    edges = ed.filter(e => e.to !== '__NEXT__');
  });

  /** @param {WheelEvent} e */
  function handleWheel(e) {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    zoom = Math.max(0.25, Math.min(3, zoom + delta));
  }

  /** @param {PointerEvent} e */
  function handlePointerDown(e) {
    if (e.button === 1 || spaceHeld) {
      isPanning = true;
      panStartX = e.clientX - panX;
      panStartY = e.clientY - panY;
      /** @type {any} */ (e.currentTarget).setPointerCapture(e.pointerId);
      e.preventDefault();
    }
  }

  /** @param {PointerEvent} e */
  function handlePointerMove(e) {
    mouseX = (e.clientX - panX) / zoom;
    mouseY = (e.clientY - panY) / zoom;

    if (isPanning) {
      panX = e.clientX - panStartX;
      panY = e.clientY - panStartY;
    } else if (draggingNodeId) {
      const worldX = (e.clientX - panX) / zoom - dragOffsetX;
      const worldY = (e.clientY - panY) / zoom - dragOffsetY;
      positionOverrides.set(draggingNodeId, { x: worldX, y: worldY });
      positionOverrides = new Map(positionOverrides);
    }
  }

  function handlePointerUp() {
    isPanning = false;
    draggingNodeId = null;
  }

  /** @param {KeyboardEvent} e */
  function handleKeyDown(e) {
    if (e.code === 'Space' && !/** @type {any} */ (e.target).closest('input, textarea')) {
      spaceHeld = true;
      e.preventDefault();
    }
    if (e.key === 'Backspace' && selectedNodeId && onRemoveStep) {
      onRemoveStep(selectedNodeId);
      selectedNodeId = null;
    }
    if (e.key === 'f' || e.key === 'F') fitAll();
    if (e.key === 'Escape') {
      selectedNodeId = null;
      drawingFrom = null;
    }
  }

  /** @param {KeyboardEvent} e */
  function handleKeyUp(e) {
    if (e.code === 'Space') spaceHeld = false;
  }

  /**
   * @param {string} nodeId
   * @param {PointerEvent} e
   */
  function startNodeDrag(nodeId, e) {
    if (spaceHeld || isPanning) return;
    const node = nodeMap.get(nodeId);
    if (!node) return;
    draggingNodeId = nodeId;
    dragOffsetX = (e.clientX - panX) / zoom - node.x;
    dragOffsetY = (e.clientY - panY) / zoom - node.y;
    selectedNodeId = nodeId;
    e.stopPropagation();
  }

  /**
   * @param {any} fromNode
   * @param {any} toNode
   */
  function edgePath(fromNode, toNode) {
    const sx = fromNode.x + NODE_W;
    const sy = fromNode.y + NODE_H / 2;
    const ex = toNode.x;
    const ey = toNode.y + NODE_H / 2;
    const dx = Math.max(Math.abs(ex - sx) * 0.4, 30);
    return `M ${sx} ${sy} C ${sx + dx} ${sy}, ${ex - dx} ${ey}, ${ex} ${ey}`;
  }

  function fitAll() {
    const nodes = Array.from(nodeMap.values());
    if (nodes.length === 0) return;
    const minX = Math.min(...nodes.map(n => n.x));
    const minY = Math.min(...nodes.map(n => n.y));
    const maxX = Math.max(...nodes.map(n => n.x + NODE_W));
    const maxY = Math.max(...nodes.map(n => n.y + NODE_H));
    const w = maxX - minX + 120;
    const h = maxY - minY + 120;
    const vw = 800;
    const vh = 500;
    zoom = Math.min(vw / w, vh / h, 1.5);
    panX = 60 - minX * zoom;
    panY = 40 - minY * zoom;
  }

  function resetLayout() {
    positionOverrides = new Map();
  }

  export function zoomIn() { zoom = Math.min(3, zoom + 0.15); }
  export function zoomOut() { zoom = Math.max(0.25, zoom - 0.15); }
  export function getZoom() { return zoom; }
  export { fitAll, resetLayout };

  /** @type {Record<string, string>} */
  const statusColor = {
    idle: 'var(--border-subtle, rgba(255,255,255,0.07))',
    running: 'var(--accent-primary)',
    done: 'var(--success)',
    error: 'var(--danger)',
  };
</script>

<svelte:window onkeydown={handleKeyDown} onkeyup={handleKeyUp} />

<div
  class="canvas-viewport"
  class:panning={isPanning || spaceHeld}
  onwheel={handleWheel}
  onpointerdown={handlePointerDown}
  onpointermove={handlePointerMove}
  onpointerup={handlePointerUp}
  role="application"
>
  <div class="canvas-grid" style="background-position: {panX}px {panY}px; background-size: {20 * zoom}px {20 * zoom}px"></div>

  <svg class="edge-layer" style="transform: translate({panX}px, {panY}px) scale({zoom})">
    {#each edges as edge (edge.id)}
      {@const fromNode = nodeMap.get(edge.from)}
      {@const toNode = nodeMap.get(edge.to)}
      {#if fromNode && toNode}
        {@const d = edgePath(fromNode, toNode)}
        <path class="edge-line" {d} />
        {#if edge.label}
          {@const mx = (fromNode.x + NODE_W + toNode.x) / 2}
          {@const my = (fromNode.y + toNode.y) / 2 + NODE_H / 2 - 10}
          <text x={mx} y={my} class="edge-label">{edge.label}</text>
        {/if}
      {/if}
    {/each}

    {#if drawingFrom}
      {@const fn = nodeMap.get(drawingFrom)}
      {#if fn}
        <line x1={fn.x + NODE_W} y1={fn.y + NODE_H / 2} x2={mouseX} y2={mouseY} class="edge-drawing" />
      {/if}
    {/if}
  </svg>

  <div class="node-layer" style="transform: translate({panX}px, {panY}px) scale({zoom}); transform-origin: 0 0">
    {#each Array.from(nodeMap.values()) as node (node.id)}
      {@const meta = getMeta(node.cabinetId)}
      <div
        class="cn-node"
        class:selected={selectedNodeId === node.id}
        class:running={node.status === 'running'}
        class:done={node.status === 'done'}
        style="left: {node.x}px; top: {node.y}px; --node-color: {meta.color}; border-color: {selectedNodeId === node.id ? meta.color : statusColor[node.status] || statusColor.idle}"
        role="button"
        tabindex="0"
        aria-label={node.label}
        onpointerdown={(e) => startNodeDrag(node.id, e)}
        ondblclick={() => onStepClick?.(node)}
        onkeydown={(e) => e.key === 'Enter' && onStepClick?.(node)}
      >
        <div class="cn-accent" style="background: {meta.color}"></div>
        <div class="cn-body">
          <span class="cn-icon">{meta.icon}</span>
          <div class="cn-info">
            <span class="cn-label">{node.label}</span>
            <span class="cn-sub">{meta.name}{node.command ? ` ${node.command}` : ''}</span>
          </div>
        </div>
        <div class="cn-port cn-port-in" role="none"
          onpointerup={() => { if (drawingFrom && drawingFrom !== node.id) drawingFrom = null; }}
        ></div>
        <div class="cn-port cn-port-out" role="none"
          onpointerdown={(e) => { e.stopPropagation(); drawingFrom = node.id; }}
        ></div>
      </div>
    {/each}
  </div>

  {#if nodeMap.size > 2}
    {@const nodes = Array.from(nodeMap.values())}
    {@const minX = Math.min(...nodes.map(n => n.x))}
    {@const minY = Math.min(...nodes.map(n => n.y))}
    {@const maxX = Math.max(...nodes.map(n => n.x + NODE_W))}
    {@const maxY = Math.max(...nodes.map(n => n.y + NODE_H))}
    {@const mmW = 150}
    {@const mmH = 100}
    {@const scale = Math.min(mmW / (maxX - minX + 80), mmH / (maxY - minY + 80))}
    <div class="minimap">
      <svg width={mmW} height={mmH}>
        {#each nodes as n}
          {@const mx = (n.x - minX + 40) * scale}
          {@const my = (n.y - minY + 40) * scale}
          {@const meta = getMeta(n.cabinetId)}
          <rect x={mx} y={my} width={NODE_W * scale} height={NODE_H * scale} rx="3" fill={meta.color} opacity="0.6" />
        {/each}
        <rect
          x={(-panX / zoom - minX + 40) * scale}
          y={(-panY / zoom - minY + 40) * scale}
          width={800 / zoom * scale}
          height={500 / zoom * scale}
          fill="none" stroke="white" stroke-width="1" opacity="0.4" rx="2"
        />
      </svg>
    </div>
  {/if}
</div>

<style>
  .canvas-viewport { position: relative; width: 100%; height: 100%; overflow: hidden; cursor: default; user-select: none; }
  .canvas-viewport.panning { cursor: grab; }
  .canvas-grid { position: absolute; inset: 0; background-image: radial-gradient(circle, var(--hover-bg) 1px, transparent 1px); pointer-events: none; }
  .edge-layer { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; overflow: visible; }
  .edge-line { fill: none; stroke: var(--border); stroke-width: 2; }
  .edge-label { font-size: 10px; fill: var(--accent-primary); text-anchor: middle; }
  .edge-drawing { stroke: var(--accent-primary); stroke-width: 2; stroke-dasharray: 6 4; opacity: 0.6; }
  .node-layer { position: absolute; top: 0; left: 0; pointer-events: none; }

  .cn-node {
    position: absolute; width: 220px;
    background: var(--bg-glass, rgba(255,255,255,0.04));
    backdrop-filter: var(--blur-quiet); -webkit-backdrop-filter: var(--blur-quiet);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.07)); border-radius: 14px;
    overflow: hidden; cursor: grab; pointer-events: auto; transition: box-shadow 0.15s ease;
  }
  .cn-node:hover { box-shadow: var(--shadow-glow); }
  .cn-node.selected { box-shadow: 0 0 0 1px var(--node-color), var(--shadow-glow); }
  .cn-node.running { animation: cn-pulse 2s ease-in-out infinite; }
  .cn-node.done { border-color: var(--success) !important; }
  @keyframes cn-pulse { 0%, 100% { box-shadow: 0 0 0 0 var(--accent-glow-strong); } 50% { box-shadow: var(--shadow-glow); } }

  .cn-accent { height: 3px; }
  .cn-body { display: flex; align-items: center; gap: 10px; padding: 10px 14px; }
  .cn-icon { font-size: 18px; flex-shrink: 0; }
  .cn-info { flex: 1; min-width: 0; }
  .cn-label { display: block; font-size: 12px; font-weight: 600; color: var(--text-primary, #fff); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cn-sub { display: block; font-size: 10px; color: var(--text-secondary, #aaa); margin-top: 1px; }

  .cn-port { position: absolute; width: 10px; height: 10px; border-radius: 50%; background: var(--hover-bg); border: 2px solid var(--border); top: 50%; transform: translateY(-50%); cursor: crosshair; transition: all 0.12s ease; pointer-events: auto; z-index: 2; }
  .cn-port-in { left: -5px; }
  .cn-port-out { right: -5px; }
  .cn-port:hover { background: var(--node-color); border-color: var(--node-color); transform: translateY(-50%) scale(1.3); }

  .minimap { position: absolute; bottom: 16px; right: 16px; background: var(--overlay-bg); backdrop-filter: var(--blur-quiet); border: 1px solid var(--border-subtle, rgba(255,255,255,0.07)); border-radius: 10px; padding: 6px; pointer-events: none; opacity: 0.8; }
</style>
