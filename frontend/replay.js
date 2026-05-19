// Copyright 2026 中山大学智能工程学院谭晓军教授课题组
// SPDX-License-Identifier: Apache-2.0

/**
 * Replay playback logic for recorded game sessions.
 * Works with renderer.js (included before this script) which provides
 * render(), updateUI(), computeViewTransform(), loadBackgroundImage(), etc.
 */

const RECORDING_SERVER = `http://${window.location.hostname || 'localhost'}:8766`;

// DOM elements
const recordingSelect = document.getElementById('recording-select');
const btnPlay = document.getElementById('btn-play');
const speedSelect = document.getElementById('speed-select');
const scrubber = document.getElementById('scrubber');
const replayTime = document.getElementById('replay-time');
const replayStatus = document.getElementById('replay-status-text');
const btnFitReplay = document.getElementById('btn-fit-replay');

// Playback state
let recording = null;
let frameIndex = 0;
let playing = false;
let playSpeed = 1;
let lastFrameTime = 0;
let animationId = null;

// --- Recording list ---

async function loadRecordingList() {
    try {
        const resp = await fetch(`${RECORDING_SERVER}/list`);
        const files = await resp.json();
        recordingSelect.innerHTML = '<option value="">选择录像...</option>';
        for (const f of files) {
            const opt = document.createElement('option');
            opt.value = f;
            // Extract timestamp from filename: game_YYYYMMDD_HHMMSS.json
            const match = f.match(/game_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
            if (match) {
                const [, y, mo, d, h, mi, s] = match;
                opt.textContent = `${y}-${mo}-${d} ${h}:${mi}:${s}`;
            } else {
                opt.textContent = f;
            }
            recordingSelect.appendChild(opt);
        }
    } catch (e) {
        recordingSelect.innerHTML = '<option value="">无法连接录像服务器</option>';
        replayStatus.textContent = '录像服务器未启动 (端口 8766)';
    }
}

// --- Loading ---

async function loadRecording(filename) {
    if (!filename) return;
    replayStatus.textContent = '加载中...';
    try {
        const resp = await fetch(`${RECORDING_SERVER}/${filename}`);
        recording = await resp.json();

        graphInfo = recording.graph_info;
        collisionRadius = graphInfo.collision_radius || 0.3;
        interactionRadius = graphInfo.zone_interaction_radius || 3.0;
        computeViewTransform();
        loadBackgroundImage();

        frameIndex = 0;
        playing = false;
        btnPlay.textContent = '播放';
        btnPlay.disabled = false;
        scrubber.max = recording.frames.length - 1;
        scrubber.value = 0;
        scrubber.disabled = false;

        showFrame(0);
        replayStatus.textContent = `已加载: ${recording.frames.length} 帧, ${recording.commands.length} 条指令`;
    } catch (e) {
        replayStatus.textContent = '加载失败: ' + e.message;
    }
}

// --- Frame display ---

function showFrame(index) {
    if (!recording || index < 0 || index >= recording.frames.length) return;
    frameIndex = index;
    gameState = recording.frames[index];

    // Remove internal _tick field from display
    delete gameState._tick;

    updateUI();
    render();

    // Update scrubber and time display
    scrubber.value = index;
    const t = gameState.time || 0;
    const total = recording.metadata.duration || 0;
    replayTime.textContent = `${t.toFixed(1)}s / ${total.toFixed(1)}s`;
}

// --- Playback loop ---

let timeAccumulator = 0;

function playbackLoop(timestamp) {
    if (!playing || !recording) return;

    if (!lastFrameTime) lastFrameTime = timestamp;
    const delta = timestamp - lastFrameTime;
    lastFrameTime = timestamp;

    const tickRate = recording.metadata.tick_rate || 30;
    const frameInterval = 1000 / (tickRate * playSpeed);

    timeAccumulator += delta;

    // Advance one frame at a time for smooth visual motion
    if (timeAccumulator >= frameInterval) {
        timeAccumulator -= frameInterval;

        const newIndex = frameIndex + 1;
        if (newIndex >= recording.frames.length) {
            playing = false;
            btnPlay.textContent = '播放';
            replayStatus.textContent = '回放结束';
            return;
        }
        showFrame(newIndex);
    }

    animationId = requestAnimationFrame(playbackLoop);
}

function togglePlay() {
    if (!recording) return;

    if (playing) {
        playing = false;
        btnPlay.textContent = '播放';
        if (animationId) cancelAnimationFrame(animationId);
    } else {
        if (frameIndex >= recording.frames.length - 1) {
            frameIndex = 0;
        }
        playing = true;
        playSpeed = parseInt(speedSelect.value);
        btnPlay.textContent = '暂停';
        lastFrameTime = 0;
        timeAccumulator = 0;
        animationId = requestAnimationFrame(playbackLoop);
    }
}

// --- Event handlers ---

recordingSelect.addEventListener('change', () => {
    if (playing) {
        playing = false;
        btnPlay.textContent = '播放';
        if (animationId) cancelAnimationFrame(animationId);
    }
    if (recordingSelect.value) {
        loadRecording(recordingSelect.value);
    }
});

btnPlay.addEventListener('click', togglePlay);

speedSelect.addEventListener('change', () => {
    playSpeed = parseInt(speedSelect.value);
});

scrubber.addEventListener('input', () => {
    if (playing) {
        playing = false;
        btnPlay.textContent = '播放';
        if (animationId) cancelAnimationFrame(animationId);
    }
    showFrame(parseInt(scrubber.value));
});

btnFitReplay.addEventListener('click', () => {
    zoomLevel = 1;
    panX = 0;
    panY = 0;
    computeViewTransform();
    if (graphInfo && gameState) render();
});

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (!recording) return;
    if (e.code === 'Space') {
        e.preventDefault();
        togglePlay();
    } else if (e.code === 'ArrowLeft') {
        e.preventDefault();
        if (playing) {
            playing = false;
            btnPlay.textContent = '播放';
            if (animationId) cancelAnimationFrame(animationId);
        }
        showFrame(Math.max(0, frameIndex - 1));
    } else if (e.code === 'ArrowRight') {
        e.preventDefault();
        if (playing) {
            playing = false;
            btnPlay.textContent = '播放';
            if (animationId) cancelAnimationFrame(animationId);
        }
        showFrame(Math.min(recording.frames.length - 1, frameIndex + 1));
    }
});

// Also support local file loading via drag-and-drop or file input
document.addEventListener('dragover', (e) => e.preventDefault());
document.addEventListener('drop', async (e) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file || !file.name.endsWith('.json')) return;
    const text = await file.text();
    recording = JSON.parse(text);
    recordingSelect.value = '';

    graphInfo = recording.graph_info;
    collisionRadius = graphInfo.collision_radius || 0.3;
    interactionRadius = graphInfo.zone_interaction_radius || 3.0;
    computeViewTransform();
    loadBackgroundImage();

    frameIndex = 0;
    playing = false;
    btnPlay.textContent = '播放';
    btnPlay.disabled = false;
    scrubber.max = recording.frames.length - 1;
    scrubber.value = 0;
    scrubber.disabled = false;

    showFrame(0);
    replayStatus.textContent = `已加载: ${recording.frames.length} 帧, ${recording.commands.length} 条指令 (本地文件)`;
});

// --- Init ---
loadRecordingList();
