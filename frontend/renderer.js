// Copyright 2026 中山大学智能工程学院谭晓军教授课题组
// SPDX-License-Identifier: Apache-2.0

/**
 * Canvas renderer for the multi-agent supply chain experiment.
 */

const SERVER_URL = `ws://${window.location.hostname || 'localhost'}:8765`;

const canvas = document.getElementById('game-canvas');
const ctx = canvas.getContext('2d');

// State
let ws = null;
let graphInfo = null;
let gameState = null;
let gameStatus = 'waiting';

// Auto-scale: map coords → canvas pixels
let viewScale = 1;
let viewOffX = 0;
let viewOffY = 0;
const VIEW_PAD = 40; // padding around map in canvas pixels
let bgImageEl = null;
let collisionRadius = 0.3;
let interactionRadius = 3.0;
const DPR = window.devicePixelRatio || 1;

// Zoom state
let zoomLevel = 1;
let panX = 0;
let panY = 0;
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 5;

function computeViewTransform() {
    if (!graphInfo) return;
    const mapW = graphInfo.map_width || 16;
    const mapH = graphInfo.map_height || 16;

    const cw = canvas.width / DPR;
    const ch = canvas.height / DPR;

    const baseScale = Math.min(cw / mapW, ch / mapH);
    viewScale = baseScale * zoomLevel;
    viewOffX = (cw - mapW * baseScale) / 2 + panX;
    viewOffY = (ch - mapH * baseScale) / 2 + panY;
}

function loadBackgroundImage() {
    if (!graphInfo || !graphInfo.background_image) { bgImageEl = null; return; }
    const img = new Image();
    img.onload = () => { bgImageEl = img; render(); };
    img.onerror = () => { bgImageEl = null; };
    img.src = graphInfo.background_image;
}

// Convert map coordinate to canvas pixel
function mapToCanvas(mx, my) {
    return [mx * viewScale + viewOffX, my * viewScale + viewOffY];
}

// Scale a size value (radius, lineWidth, font) from map units to screen
function mapSizeToCanvas(size) {
    return size * viewScale;
}

// Colors
const COLORS = {
    road: '#1a3a5c',
    roadLine: '#2a5a8c',
    node: '#3a6a9c',
    rawZone: '#27ae60',
    procZone: '#2980b9',
    consZone: '#e94560',
    vehicle: ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6'],
    pathPreview: 'rgba(255, 255, 255, 0.2)',
    carrying: '#f1c40f',
    orderWarning: '#f39c12',
    orderDanger: '#e94560',
    ITEM_BOX: {
        have:         { fill: '#0f3460', border: '#4ecca3', text: '#4ecca3' },
        missing:      { fill: '#1a1a2e', border: '#333333', text: '#555555' },
        outputReady:  { fill: '#1a3a20', border: '#f1c40f', text: '#f1c40f' },
        outputPending:{ fill: '#1a1a2e', border: '#555555', text: '#888888' },
        required:     { fill: '#2a1520', border: '#e94560', text: '#e94560' },
    },
};

// UI Elements
const btnStart = document.getElementById('btn-start');
const btnReset = document.getElementById('btn-reset');
const btnFit = document.getElementById('btn-fit');
const timeDisplay = document.getElementById('time-display');
const scoreDisplay = document.getElementById('score-display');
const completedDisplay = document.getElementById('completed-display');
const dropRewardDisplay = document.getElementById('drop-reward-display');
const orderRewardDisplay = document.getElementById('order-reward-display');
const collisionDisplay = document.getElementById('collision-display');
const overtimeDisplay = document.getElementById('overtime-display');
const seedDisplay = document.getElementById('seed-display');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const ordersList = document.getElementById('orders-list');
const processingList = document.getElementById('processing-list');
const vehiclesList = document.getElementById('vehicles-list');

// --- WebSocket ---

function connect() {
    ws = new WebSocket(SERVER_URL);
    ws.onopen = () => {
        ws.send(JSON.stringify({ role: 'viewer' }));
        console.log('Connected to server');
    };
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleMessage(data);
    };
    ws.onclose = () => {
        console.log('Disconnected');
        updateStatus('waiting', '已断开，尝试重连...');
        setTimeout(connect, 3000);
    };
    ws.onerror = (err) => {
        console.error('WebSocket error', err);
    };
}

function handleMessage(data) {
    switch (data.type) {
        case 'game_status':
            gameStatus = data.status;
            updateStatusUI(data.status);
            break;
        case 'graph_info':
            graphInfo = data.data;
            collisionRadius = data.data.collision_radius || 0.3;
            interactionRadius = data.data.zone_interaction_radius || 3.0;
            computeViewTransform();
            loadBackgroundImage();
            break;
        case 'state':
            gameState = data;
            updateUI();
            render();
            break;
        case 'game_over':
            gameState = data;
            updateUI();
            render();
            updateStatus('ended', '游戏结束!');
            break;
    }
}

function updateStatusUI(status) {
    const labels = {
        waiting: '等待学生连接...',
        ready: '学生已连接，点击开始',
        running: '游戏进行中',
        ended: '游戏结束',
    };
    updateStatus(status, labels[status] || status);
    btnStart.disabled = status !== 'ready';
}

function updateStatus(dotClass, text) {
    statusDot.className = dotClass;
    statusText.textContent = text;
}

// --- UI Updates ---

function updateUI() {
    if (!gameState) return;

    const s = gameState;
    timeDisplay.textContent = s.time.toFixed(1) + 's';
    scoreDisplay.textContent = s.score.toFixed(0);
    collisionDisplay.textContent = (s.collision_penalty || 0).toFixed(0);
    overtimeDisplay.textContent = (s.overtime_penalty || 0).toFixed(0);

    // Completed orders count
    completedDisplay.textContent = s.completed_orders_count || 0;

    // Drop reward total
    dropRewardDisplay.textContent = (s.drop_reward_total || 0).toFixed(0);

    // Order reward
    orderRewardDisplay.textContent = (s.completed_orders_value || 0).toFixed(0);

    // Random seed
    seedDisplay.textContent = s.random_seed != null ? s.random_seed : '-';

    // Orders panel
    updateOrdersPanel(s.orders || []);
    // Processing panel
    updateProcessingPanel(s.zones || {});
    // Vehicles panel
    updateVehiclesPanel(s.vehicles || {});
}

function updateOrdersPanel(orders) {
    let html = '';
    if (orders.length === 0) {
        html = '<div class="panel-item"><span class="item-detail">暂无订单</span></div>';
    }
    for (const order of orders) {
        const remaining = Math.max(0, order.deadline - (gameState ? gameState.time : 0));
        const isWarning = remaining < 15;
        const isDanger = remaining < 5;
        const cls = isDanger ? 'danger' : isWarning ? 'warning' : '';
        html += `<div class="panel-item ${cls}">
            <div class="item-title">${order.consumer}: 需要 ${order.product}</div>
            <div class="item-detail">剩余 ${remaining.toFixed(1)}s</div>
        </div>`;
    }
    ordersList.innerHTML = html;
}

function getZoneTotalTime(zid, zone) {
    if (!graphInfo) return 5;
    if (zone.type === 'raw_material') return graphInfo.raw_material_production_time || 3;
    if (zone.type === 'processing') {
        const rid = zone.outputs ? zone.outputs[0] : null;
        return (rid && graphInfo.recipes && graphInfo.recipes[rid])
            ? graphInfo.recipes[rid].processing_time : 5;
    }
    if (zone.type === 'consumer') return graphInfo.orders_timeout_base || 45;
    return 5;
}

function updateProcessingPanel(zones) {
    let html = '';
    for (const [zid, z] of Object.entries(zones)) {
        if (z.type !== 'processing') continue;

        const statusLabels = {
            idle: '空闲',
            collecting: '收集材料中',
            processing: '生产中',
            product_ready: '成品待取',
        };

        let inventoryHtml = '';
        if (z.items) {
            for (const [mat, count] of Object.entries(z.items)) {
                const cls = count > 0 ? 'have' : 'missing';
                inventoryHtml += `<span class="material-tag ${cls}">${mat}:${count}</span>`;
            }
        }

        let progressHtml = '';
        if (z.status === 'processing' && z.progress > 0) {
            const total = getZoneTotalTime(zid, z);
            const pct = Math.max(0, (1 - z.progress / total) * 100);
            progressHtml = `<div class="progress-bar"><div class="fill" style="width:${pct}%"></div></div>`;
        }

        const outputName = z.outputs ? z.outputs[0] : zid;
        html += `<div class="panel-item">
            <div class="item-title">${zid} (${outputName})</div>
            <div class="item-detail">${statusLabels[z.status] || z.status}</div>
            <div>${inventoryHtml}</div>
            ${progressHtml}
        </div>`;
    }
    processingList.innerHTML = html;
}

function updateVehiclesPanel(vehicles) {
    let html = '';
    for (const [vid, v] of Object.entries(vehicles)) {
        const idx = parseInt(vid.replace('v', '')) - 1;
        const colorDot = `<span style="color:${COLORS.vehicle[idx % COLORS.vehicle.length]}">●</span>`;
        const carrying = v.carrying ? `[${v.carrying}]` : '空';
        const statusLabel = v.status === 'moving' ? '移动中' : '空闲';
        html += `<div class="panel-item">
            <div class="item-title">${colorDot} ${vid} - ${statusLabel}</div>
            <div class="item-detail">携带: ${carrying}</div>
        </div>`;
    }
    vehiclesList.innerHTML = html;
}

// --- Canvas Rendering ---

function render() {
    if (!graphInfo || !gameState) return;

    const w = canvas.width / DPR;
    const h = canvas.height / DPR;
    ctx.clearRect(0, 0, w, h);

    // Background
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, w, h);

    drawBackground();
    drawRoads();
    drawZones();
    drawVehicles();
}

function drawBackground() {
    if (!bgImageEl) return;
    const mapW = graphInfo.map_width || 16;
    const mapH = graphInfo.map_height || 16;
    const [x1, y1] = mapToCanvas(0, 0);
    const [x2, y2] = mapToCanvas(mapW, mapH);
    ctx.globalAlpha = 0.35;
    ctx.drawImage(bgImageEl, x1, y1, x2 - x1, y2 - y1);
    ctx.globalAlpha = 1.0;
}

function drawRoads() {
    const nodes = graphInfo.nodes;

    // Intersection nodes
    const zoneNodes = new Set();
    if (graphInfo.zones) {
        for (const z of Object.values(graphInfo.zones)) {
            zoneNodes.add(z.node);
        }
    }

    for (const [nid, node] of Object.entries(nodes)) {
        if (zoneNodes.has(nid)) continue;
        ctx.fillStyle = COLORS.node;
        const [nx, ny] = mapToCanvas(node.x, node.y);
        ctx.beginPath();
        ctx.arc(nx, ny, Math.max(3, 4 * zoomLevel), 0, Math.PI * 2);
        ctx.fill();
    }
}

function drawRoundedRect(x, y, w, h, r, fillColor, strokeColor, strokeWidth) {
    ctx.beginPath();
    if (ctx.roundRect) {
        ctx.roundRect(x, y, w, h, r);
    } else {
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
        ctx.closePath();
    }
    if (fillColor) {
        ctx.fillStyle = fillColor;
        ctx.fill();
    }
    if (strokeColor) {
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = strokeWidth || 1;
        ctx.stroke();
    }
}

function drawItemPill(x, y, w, h, label, state, fontSize) {
    const colors = COLORS.ITEM_BOX[state] || COLORS.ITEM_BOX.missing;
    const r = h / 2;
    drawRoundedRect(x, y, w, h, r, colors.fill, colors.border, 1);

    ctx.fillStyle = colors.text;
    ctx.font = `bold ${fontSize}px monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, x + w / 2, y + h / 2 + 0.5);
}

function drawZonePanel(cx, cy, zone, color) {
    if (zoomLevel < 0.6) return;
    const zoneR = mapSizeToCanvas(interactionRadius);
    const pad = Math.max(2, 4 * zoomLevel);
    const pillW = Math.max(8, 22 * zoomLevel);
    const pillH = Math.max(5, 13 * zoomLevel);
    const pillGap = Math.max(1, 2 * zoomLevel);
    const fontBig = Math.max(8, Math.round(12 * zoomLevel));
    const fontSmall = Math.max(6, Math.round(9 * zoomLevel));

    let line1 = '';
    let pills = []; // [{label, state}]

    if (zone.type === 'processing') {
        const outName = zone.outputs ? zone.outputs[0] : '';
        const sec = zone.progress != null ? `${zone.progress.toFixed(1)}s` : '';
        const sm = { idle: '', collecting: '收集中', processing: `生产${sec}`, product_ready: '成品!' };
        line1 = `${outName} ${sm[zone.status] || ''}`.trim();
        const inputs = zone.inputs || [];
        const items = zone.items || {};
        for (const name of inputs) {
            pills.push({ label: name, state: (items[name] || 0) > 0 ? 'have' : 'missing' });
        }
    } else if (zone.type === 'raw_material') {
        const outName = zone.outputs ? zone.outputs[0] : '';
        const cnt = (zone.items && zone.items[outName]) || 0;
        if (zone.progress != null && zone.progress > 0) {
            line1 = `${outName} ${zone.progress.toFixed(0)}s`;
        } else {
            line1 = outName;
        }
        for (let i = 0; i < cnt; i++) {
            pills.push({ label: outName, state: 'have' });
        }
    } else if (zone.type === 'consumer') {
        if (zone.order) {
            const rem = Math.max(0, zone.order.deadline - gameState.time);
            line1 = `${zone.order.required} ${rem.toFixed(0)}s`;
        } else {
            line1 = '等待订单';
        }
    }

    if (!line1 && pills.length === 0) return;

    // Measure text width
    ctx.font = `bold ${fontBig}px sans-serif`;
    const textW = ctx.measureText(line1).width;
    const pillsRowW = pills.length > 0 ? pills.length * pillW + (pills.length - 1) * pillGap : 0;
    const contentW = Math.max(textW, pillsRowW);
    const panelW = contentW + pad * 2;
    const row1H = line1 ? fontBig + pad : 0;
    const row2H = pills.length > 0 ? pillH + pad : 0;
    const panelH = row1H + row2H + pad;

    const px = cx - panelW / 2;
    const py = cy + zoneR + 4 * zoomLevel;

    // Background panel
    const bg = color + '22';
    drawRoundedRect(px, py, panelW, panelH, Math.max(2, 4 * zoomLevel), bg, color + '66', 1);

    // Line 1: status text
    if (line1) {
        ctx.fillStyle = '#ddd';
        ctx.font = `bold ${fontBig}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(line1, cx, py + pad);
    }

    // Line 2: material pills
    if (pills.length > 0) {
        const pillStartX = cx - pillsRowW / 2;
        const pillStartY = py + row1H + pad / 2;
        for (let i = 0; i < pills.length; i++) {
            drawItemPill(pillStartX + i * (pillW + pillGap), pillStartY, pillW, pillH, pills[i].label, pills[i].state, fontSmall);
        }
    }
}

function drawZones() {
    const zones = gameState.zones;
    const zoneR = mapSizeToCanvas(interactionRadius);

    for (const [zid, zone] of Object.entries(zones)) {
        const [mx, my] = zone.position;
        const [x, y] = mapToCanvas(mx, my);
        let color, label;

        if (zone.type === 'raw_material') {
            color = COLORS.rawZone;
            label = zid.replace('raw_', '').toUpperCase();
        } else if (zone.type === 'processing') {
            color = COLORS.procZone;
            label = zid.replace('proc_', '').toUpperCase();
        } else if (zone.type === 'consumer') {
            color = COLORS.consZone;
            label = zid.replace('cons_', '').toUpperCase();
        }

        // Zone circle
        ctx.fillStyle = color + '33';
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, zoneR, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        const ringOffset = 3 * zoomLevel;
        const ringWidth = Math.max(2, 3 * zoomLevel);

        // Progress ring (raw_material producing or processing)
        if (zone.progress != null && zone.progress > 0) {
            const total = getZoneTotalTime(zid, zone);
            const pct = Math.max(0, 1 - zone.progress / total);
            ctx.strokeStyle = '#4ecca3';
            ctx.lineWidth = ringWidth;
            ctx.beginPath();
            ctx.arc(x, y, zoneR + ringOffset, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * pct);
            ctx.stroke();
        }

        // Countdown ring for consumer zones with active order
        if (zone.type === 'consumer' && zone.order) {
            const totalDuration = getZoneTotalTime(zid, zone);
            const remaining = Math.max(0, zone.order.deadline - gameState.time);
            const progress = Math.max(0, Math.min(1, remaining / totalDuration));
            const isOvertime = remaining <= 0;
            if (isOvertime) {
                // Blink red ring when overtime
                if (Math.floor(gameState.time * 2) % 2 === 0) {
                    ctx.strokeStyle = '#e94560';
                    ctx.lineWidth = ringWidth;
                    ctx.beginPath();
                    ctx.arc(x, y, zoneR + ringOffset, 0, Math.PI * 2);
                    ctx.stroke();
                }
            } else {
                ctx.strokeStyle = remaining < 10 ? '#f39c12' : '#4ecca3';
                ctx.lineWidth = ringWidth;
                ctx.beginPath();
                ctx.arc(x, y, zoneR + ringOffset, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress);
                ctx.stroke();
            }
        }

        // Label inside circle
        ctx.fillStyle = '#fff';
        ctx.font = `bold ${Math.max(10, Math.round(15 * zoomLevel))}px monospace`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(label, x, y);

        // Unified info panel below circle
        drawZonePanel(x, y, zone, color);
    }
}

function drawVehicles() {
    const vehicles = gameState.vehicles;

    for (const [vid, v] of Object.entries(vehicles)) {
        const [mx, my] = v.position;
        const [x, y] = mapToCanvas(mx, my);
        const idx = parseInt(vid.replace('v', '')) - 1;
        const color = COLORS.vehicle[idx % COLORS.vehicle.length];

        // Path preview
        if (v.path_preview && v.path_preview.length > 0) {
            ctx.strokeStyle = color + '40';
            ctx.lineWidth = Math.max(1, 2 * zoomLevel);
            ctx.setLineDash([4 * zoomLevel, 4 * zoomLevel]);
            ctx.beginPath();
            ctx.moveTo(x, y);
            for (const pt of v.path_preview) {
                const [px, py] = mapToCanvas(pt[0], pt[1]);
                ctx.lineTo(px, py);
            }
            ctx.stroke();
            ctx.setLineDash([]);
        }

        // Vehicle body (TurtleBot-style circle + direction line)
        const angle = v.angle || 0;
        const radius = mapSizeToCanvas(collisionRadius);
        const dirLineLen = radius * 0.7;

        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(angle);

        // Circle body
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.fill();

        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 1;
        ctx.stroke();

        // Direction indicator line (center → front)
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(dirLineLen, 0);
        ctx.stroke();

        ctx.restore();

        // Carrying indicator
        if (v.carrying) {
            ctx.fillStyle = COLORS.carrying;
            ctx.font = `bold ${Math.max(9, Math.round(12 * zoomLevel))}px monospace`;
            ctx.textAlign = 'center';
            ctx.fillText(v.carrying, x, y - 14 * zoomLevel);

            // Small dot
            ctx.beginPath();
            ctx.arc(x, y - 20 * zoomLevel, Math.max(2, 4 * zoomLevel), 0, Math.PI * 2);
            ctx.fill();
        }

        // Vehicle label
        ctx.fillStyle = color;
        ctx.font = `bold ${Math.max(9, Math.round(13 * zoomLevel))}px monospace`;
        ctx.textAlign = 'center';
        ctx.fillText(vid, x, y + 16 * zoomLevel);
    }
}

// --- Event Handlers ---

if (!window.REPLAY_MODE) {
    btnStart.addEventListener('click', () => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'start_game' }));
            btnStart.disabled = true;
        }
    });

    btnReset.addEventListener('click', () => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'reset_game' }));
        }
    });
}

if (btnFit) {
    btnFit.addEventListener('click', () => {
        zoomLevel = 1;
        panX = 0;
        panY = 0;
        computeViewTransform();
        if (graphInfo && gameState) render();
    });
}

// --- Zoom & Pan ---

canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (!graphInfo) return;

    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    // Map point under cursor before zoom
    const mapXBefore = (mx - viewOffX) / viewScale;
    const mapYBefore = (my - viewOffY) / viewScale;

    // Apply zoom
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    zoomLevel = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, zoomLevel * factor));

    // Recompute base transform (without pan adjustment)
    computeViewTransform();

    // Map point under cursor after zoom (pan still old)
    const mapXAfter = (mx - viewOffX) / viewScale;
    const mapYAfter = (my - viewOffY) / viewScale;

    // Adjust pan so the map point under cursor stays fixed
    panX += (mapXAfter - mapXBefore) * viewScale;
    panY += (mapYAfter - mapYBefore) * viewScale;

    computeViewTransform();
    if (graphInfo && gameState) render();
}, { passive: false });

// Pan (drag)
let isDragging = false;
let dragLastX = 0;
let dragLastY = 0;

canvas.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    isDragging = true;
    dragLastX = e.clientX;
    dragLastY = e.clientY;
    canvas.style.cursor = 'grabbing';
});

window.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    panX += e.clientX - dragLastX;
    panY += e.clientY - dragLastY;
    dragLastX = e.clientX;
    dragLastY = e.clientY;
    computeViewTransform();
    if (graphInfo && gameState) render();
});

window.addEventListener('mouseup', () => {
    if (isDragging) {
        isDragging = false;
        canvas.style.cursor = 'grab';
    }
});

canvas.style.cursor = 'grab';

// --- Init ---

function init() {
    // Resize canvas to fit container
    function resize() {
        const container = document.getElementById('canvas-container');
        canvas.width = container.clientWidth * DPR;
        canvas.height = container.clientHeight * DPR;
        canvas.style.width = container.clientWidth + 'px';
        canvas.style.height = container.clientHeight + 'px';
        ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
        zoomLevel = 1;
        panX = 0;
        panY = 0;
        computeViewTransform();
        if (graphInfo && gameState) render();
    }

    window.addEventListener('resize', resize);
    resize();

    if (!window.REPLAY_MODE) {
        connect();
    }
}

init();
