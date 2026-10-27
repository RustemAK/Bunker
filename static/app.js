// БУНКЕР 3.3 — Клиентская логика терминала
(function () {
  'use strict';

  // --- AUDIO SYNTHESIZER (Web Audio API) ---
  let audioCtx = null;
  let soundEnabled = true;

  function initAudio() {
    if (!audioCtx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) audioCtx = new AudioContext();
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
  }

  function playTone(freq, type, duration, gainVal = 0.1) {
    if (!soundEnabled || !audioCtx) return;
    try {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
      gain.gain.setValueAtTime(gainVal, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + duration);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + duration);
    } catch (e) {}
  }

  function soundClick() {
    playTone(800, 'sine', 0.04, 0.08);
  }

  function soundReveal() {
    if (!soundEnabled || !audioCtx) return;
    try {
      // Pneumatic whoosh + low thud
      playTone(220, 'triangle', 0.25, 0.2);
      setTimeout(() => playTone(110, 'sine', 0.3, 0.25), 100);
    } catch (e) {}
  }

  function soundAlarm() {
    if (!soundEnabled || !audioCtx) return;
    try {
      playTone(660, 'sawtooth', 0.2, 0.15);
      setTimeout(() => playTone(880, 'sawtooth', 0.2, 0.15), 180);
    } catch (e) {}
  }

  // --- APPLICATION STATE ---
  let ws = null;
  let myId = localStorage.getItem('bunker_player_id') || null;
  let currentRoomCode = localStorage.getItem('bunker_room_code') || null;
  let gameState = null;
  let selectedVoteCandidateId = null;
  let timerInterval = null;

  // DOM Elements
  const screenLobby = document.getElementById('screenLobby');
  const screenWaiting = document.getElementById('screenWaiting');
  const screenGame = document.getElementById('screenGame');

  const playerNameInput = document.getElementById('playerNameInput');
  const roomCodeInput = document.getElementById('roomCodeInput');
  const avatarPicker = document.getElementById('avatarPicker');
  const createRoomBtn = document.getElementById('createRoomBtn');
  const joinRoomBtn = document.getElementById('joinRoomBtn');
  const soundToggleBtn = document.getElementById('soundToggleBtn');

  const roomBadge = document.getElementById('roomBadge');
  const roomCodeDisplay = document.getElementById('roomCodeDisplay');
  const waitRoomCode = document.getElementById('waitRoomCode');
  const roomCodeBig = document.getElementById('roomCodeBig');
  const playerCount = document.getElementById('playerCount');
  const lobbyPlayersList = document.getElementById('lobbyPlayersList');
  const startGameBtn = document.getElementById('startGameBtn');
  const waitHostNotice = document.getElementById('waitHostNotice');

  // HUD
  const currentRoundDisplay = document.getElementById('currentRoundDisplay');
  const phaseDisplay = document.getElementById('phaseDisplay');
  const catastropheName = document.getElementById('catastropheName');
  const catastropheIcon = document.getElementById('catastropheIcon');
  const speechTimerNum = document.getElementById('speechTimerNum');

  // Tabs
  const tabButtons = document.querySelectorAll('.tab-btn');
  const tabSurvivors = document.getElementById('tabSurvivors');
  const tabMyDeck = document.getElementById('tabMyDeck');
  const tabBunker = document.getElementById('tabBunker');
  const survivorsGrid = document.getElementById('survivorsGrid');
  const myCardsGrid = document.getElementById('myCardsGrid');
  const myTurnAlert = document.getElementById('myTurnAlert');
  const liveLogList = document.getElementById('liveLogList');
  const hostControlsRow = document.getElementById('hostControlsRow');
  const hostStartVotingBtn = document.getElementById('hostStartVotingBtn');

  // Debate & Host Command Bar
  const debateBanner = document.getElementById('debateBanner');
  const debateCountdownNum = document.getElementById('debateCountdownNum');
  const hostCommandBar = document.getElementById('hostCommandBar');
  const hostTimerStatus = document.getElementById('hostTimerStatus');
  const hostSkipDebateBtn = document.getElementById('hostSkipDebateBtn');
  const hostExtendTimerBtn = document.getElementById('hostExtendTimerBtn');
  const hostPauseTimerBtn = document.getElementById('hostPauseTimerBtn');
  const hostNextTurnBtn = document.getElementById('hostNextTurnBtn');


  // Special Card
  const mySpecialName = document.getElementById('mySpecialName');
  const mySpecialDesc = document.getElementById('mySpecialDesc');
  const mySpecialTiming = document.getElementById('mySpecialTiming');
  const playSpecialBtn = document.getElementById('playSpecialBtn');

  // Special Card Target Modal
  const specialTargetModal = document.getElementById('specialTargetModal');
  const specialModalTitle = document.getElementById('specialModalTitle');
  const specialModalPrompt = document.getElementById('specialModalPrompt');
  const specialTargetsList = document.getElementById('specialTargetsList');
  const confirmSpecialTargetBtn = document.getElementById('confirmSpecialTargetBtn');
  const closeSpecialModalBtn = document.getElementById('closeSpecialModalBtn');
  let selectedSpecialTargetId = null;

  // Bunker Tab
  const catFullIcon = document.getElementById('catFullIcon');
  const catFullBadge = document.getElementById('catFullBadge');
  const catFullName = document.getElementById('catFullName');
  const catFullDesc = document.getElementById('catFullDesc');
  const catFullTip = document.getElementById('catFullTip');
  const bunkerPairsList = document.getElementById('bunkerPairsList');

  // Modals
  const dossierModal = document.getElementById('dossierModal');
  const closeDossierBtn = document.getElementById('closeDossierBtn');
  const dosAvatar = document.getElementById('dosAvatar');
  const dosName = document.getElementById('dosName');
  const dosStatusBadge = document.getElementById('dosStatusBadge');
  const dosRevealedCount = document.getElementById('dosRevealedCount');
  const dosTurnStatus = document.getElementById('dosTurnStatus');
  const dosCardsList = document.getElementById('dosCardsList');

  const votingModal = document.getElementById('votingModal');
  const voteRoundNum = document.getElementById('voteRoundNum');
  const candidatesList = document.getElementById('candidatesList');
  const submitVoteBtn = document.getElementById('submitVoteBtn');

  const voteResultsModal = document.getElementById('voteResultsModal');
  const exileTitle = document.getElementById('exileTitle');
  const exileDesc = document.getElementById('exileDesc');
  const votesBreakdownBox = document.getElementById('votesBreakdownBox');
  const hostNextRoundBtnBox = document.getElementById('hostNextRoundBtnBox');
  const confirmNextRoundBtn = document.getElementById('confirmNextRoundBtn');

  const finaleModal = document.getElementById('finaleModal');
  const aiLaunchPrompt = document.getElementById('aiLaunchPrompt');
  const triggerAiBtn = document.getElementById('triggerAiBtn');
  const aiHostActionRow = document.getElementById('aiHostActionRow');
  const aiWaitNotice = document.getElementById('aiWaitNotice');
  const aiLoadingScanner = document.getElementById('aiLoadingScanner');
  const aiResultsDisplay = document.getElementById('aiResultsDisplay');
  const aiScoreGauge = document.getElementById('aiScoreGauge');
  const aiScorePercent = document.getElementById('aiScorePercent');
  const aiStatusPill = document.getElementById('aiStatusPill');
  const aiTitleHeader = document.getElementById('aiTitleHeader');
  const aiVerdictParagraph = document.getElementById('aiVerdictParagraph');
  const aiTimelineGrid = document.getElementById('aiTimelineGrid');
  const aiMvpName = document.getElementById('aiMvpName');
  const aiMvpReason = document.getElementById('aiMvpReason');
  const aiTroubleName = document.getElementById('aiTroubleName');
  const aiTroubleReason = document.getElementById('aiTroubleReason');
  const aiEpilogueText = document.getElementById('aiEpilogueText');
  const newGameHostBtn = document.getElementById('newGameHostBtn');


  const toastContainer = document.getElementById('toastContainer');

  // --- TOAST NOTIFICATIONS ---
  function showToast(text) {
    const el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = text;
    toastContainer.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      el.style.transition = 'opacity 0.4s';
      setTimeout(() => el.remove(), 400);
    }, 4000);
  }

  // --- WEBSOCKET CONNECTION ---
  function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('WS connected');
      // Auto-reconnect to room if saved
      if (currentRoomCode && myId) {
        ws.send(jsonStr({
          action: 'join_room',
          room_code: currentRoomCode,
          saved_player_id: myId
        }));
      }
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleServerMessage(msg);
      } catch (e) {
        console.error('Error parsing WS message:', e);
      }
    };

    ws.onclose = () => {
      console.log('WS closed, reconnecting in 2s...');
      setTimeout(connectWebSocket, 2000);
    };
  }

  function jsonStr(obj) {
    return JSON.stringify(obj);
  }

  function getSelectedAvatar() {
    const sel = avatarPicker.querySelector('.avatar-opt.selected');
    return sel ? sel.dataset.av : '👨‍🔬';
  }

  // --- SOUND TOGGLE ---
  soundToggleBtn.addEventListener('click', () => {
    initAudio();
    soundEnabled = !soundEnabled;
    soundToggleBtn.textContent = soundEnabled ? '🔊' : '🔇';
    soundClick();
  });

  // Avatar Picker Selection
  avatarPicker.addEventListener('click', (e) => {
    const opt = e.target.closest('.avatar-opt');
    if (!opt) return;
    initAudio();
    soundClick();
    avatarPicker.querySelectorAll('.avatar-opt').forEach(el => el.classList.remove('selected'));
    opt.classList.add('selected');
  });

  // --- LOBBY ACTIONS ---
  createRoomBtn.addEventListener('click', () => {
    initAudio();
    soundClick();
    const name = playerNameInput.value.trim() || 'Командир';
    const avatar = getSelectedAvatar();
    ws.send(jsonStr({ action: 'create_room', name, avatar }));
  });

  joinRoomBtn.addEventListener('click', () => {
    initAudio();
    soundClick();
    const roomCode = roomCodeInput.value.trim().toUpperCase();
    const name = playerNameInput.value.trim() || 'Выживший';
    const avatar = getSelectedAvatar();

    if (!roomCode) {
      alert('Пожалуйста, введите 4-буквенный код бункера!');
      return;
    }

    ws.send(jsonStr({ action: 'join_room', room_code: roomCode, name, avatar }));
  });

  startGameBtn.addEventListener('click', () => {
    initAudio();
    soundAlarm();
    ws.send(jsonStr({ action: 'start_game' }));
  });

  // Tabs switching
  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      initAudio();
      soundClick();
      tabButtons.forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

      btn.classList.add('active');
      const targetId = btn.dataset.tab;
      document.getElementById(targetId).classList.add('active');
    });
  });

  // --- SERVER MESSAGE DISPATCHER ---
  function handleServerMessage(msg) {
    if (msg.type === 'error') {
      alert(msg.message);
      return;
    }

    if (msg.type === 'timer_tick') {
      const sec = msg.seconds;
      if (speechTimerNum) speechTimerNum.textContent = sec;
      if (debateCountdownNum) debateCountdownNum.textContent = sec;
      if (hostTimerStatus) {
        hostTimerStatus.textContent = msg.paused ? '⏸️ Таймер на паузе' : `⏱️ Осталось: ${sec}с`;
        hostTimerStatus.className = msg.paused ? 'host-timer-status text-danger' : 'host-timer-status text-amber';
      }
      if (sec <= 5 && sec > 0) {
        soundClick();
      }
      return;
    }

    if (msg.type === 'room_joined') {

      myId = msg.my_id;
      currentRoomCode = msg.room_code;
      localStorage.setItem('bunker_player_id', myId);
      localStorage.setItem('bunker_room_code', currentRoomCode);
      gameState = msg.state;
      renderApp();
      return;
    }

    if (msg.type === 'state_update') {
      const prevPhase = gameState ? gameState.phase : null;
      gameState = msg.state;
      renderApp();

      // Sound alerts on phase shifts
      if (prevPhase !== gameState.phase) {
        if (gameState.phase === 'voting') {
          soundAlarm();
          showToast('🗳️ <strong>Началось тайное голосование!</strong>');
        } else if (gameState.phase === 'vote_results') {
          soundReveal();
        }
      }
    }
  }

  // --- RENDER APPLICATION ---
  function renderApp() {
    if (!gameState) return;

    // Room badge
    if (gameState.room_code) {
      roomBadge.classList.remove('hidden');
      roomCodeDisplay.textContent = gameState.room_code;
    }

    // Screen Router
    if (gameState.status === 'lobby') {
      showScreen(screenWaiting);
      renderWaitingRoom();
    } else {
      showScreen(screenGame);
      renderInGame();
    }
  }

  function showScreen(screenEl) {
    [screenLobby, screenWaiting, screenGame].forEach(s => s.classList.remove('active'));
    screenEl.classList.add('active');
  }

  // --- WAITING ROOM ---
  function renderWaitingRoom() {
    waitRoomCode.textContent = gameState.room_code;
    roomCodeBig.textContent = gameState.room_code;
    playerCount.textContent = gameState.players.length;

    const n = gameState.players.length;
    const capacity = Math.max(1, Math.floor(n / 2));
    const lobbyCapNum = document.getElementById('lobbyCapacityNum');
    if (lobbyCapNum) lobbyCapNum.textContent = `${capacity} из ${n}`;

    lobbyPlayersList.innerHTML = '';
    gameState.players.forEach(p => {
      const card = document.createElement('div');
      card.className = 'player-lobby-card';
      card.innerHTML = `
        <span class="p-avatar">${p.avatar}</span>
        <div>
          <div class="p-name">${escapeHtml(p.name)} ${p.id === gameState.my_id ? '(Вы)' : ''}</div>
          <div class="p-role">${p.is_host ? '👑 Создатель бункера' : 'Выживший'}</div>
        </div>
      `;
      lobbyPlayersList.appendChild(card);
    });

    const isHost = (gameState.host_id === gameState.my_id);
    if (isHost) {
      startGameBtn.classList.remove('hidden');
      waitHostNotice.classList.add('hidden');
    } else {
      startGameBtn.classList.add('hidden');
      waitHostNotice.classList.remove('hidden');
    }
  }

  // --- IN-GAME SCREEN ---
  function renderInGame() {
    // Top HUD
    currentRoundDisplay.textContent = gameState.round;
    const phaseLabels = {
      turns: 'ФАЗА: ВСКРЫТИЕ КАРТ',
      debate: 'ФАЗА: ОБСУЖДЕНИЕ (ДЕБАТЫ)',
      voting: 'ФАЗА: ТАЙНОЕ ГОЛОСОВАНИЕ',
      vote_results: 'ФАЗА: ИТОГИ ИЗГНАНИЯ',
      finale: 'ФАЗА: ФИНАЛ ВЫЖИВАНИЯ'
    };
    phaseDisplay.textContent = phaseLabels[gameState.phase] || gameState.phase.toUpperCase();

    if (gameState.catastrophe) {
      catastropheName.textContent = gameState.catastrophe.name;
      catastropheIcon.textContent = gameState.catastrophe.icon || '☢️';

      catFullIcon.textContent = gameState.catastrophe.icon || '☢️';
      catFullBadge.textContent = gameState.catastrophe.badge || 'ГЛОБАЛЬНАЯ КАТАСТРОФА';
      catFullName.textContent = gameState.catastrophe.name;
      catFullDesc.textContent = gameState.catastrophe.desc;
      catFullTip.textContent = gameState.catastrophe.survive_tip || 'Нужна слаженная работа команды.';
    }

    // Timer display
    const currentSec = gameState.timer_seconds || 0;
    speechTimerNum.textContent = currentSec;

    // Bunker Capacity HUD
    const hudCapEl = document.getElementById('hudCapacityDisplay');
    if (hudCapEl) {
      const cap = gameState.bunker_capacity || Math.max(1, Math.floor(gameState.players.length / 2));
      hudCapEl.textContent = `${cap} из ${gameState.total_players || gameState.players.length}`;
    }

    // Debate Banner visibility & dynamic description
    if (gameState.phase === 'debate') {
      debateBanner.classList.remove('hidden');
      debateCountdownNum.textContent = currentSec;

      const debateBadgeTitle = document.getElementById('debateBadgeTitle');
      const debateHeading = document.getElementById('debateHeading');
      const debateHint = document.getElementById('debateHint');

      if (gameState.round_has_voting) {
        if (debateBadgeTitle) debateBadgeTitle.textContent = '⚖️ ФАЗА ДЕБАТОВ (ПЕРЕД ГОЛОСОВАНИЕМ)';
        if (debateHeading) debateHeading.textContent = `Дискуссия перед голосованием Раунда ${gameState.round}`;
        if (debateHint) debateHint.textContent = `Все карты раунда вскрыты! Обсудите, кто должен покинуть убежище (будет изгнан: ${gameState.round_exiles_count || 1}).`;
      } else {
        if (debateBadgeTitle) debateBadgeTitle.textContent = '⚖️ ФАЗА ДЕБАТОВ (БЕЗ ИЗГНАНИЯ)';
        if (debateHeading) debateHeading.textContent = `Знакомство и анализ шансов (Раунд ${gameState.round})`;
        if (debateHint) debateHint.textContent = `По правилам в Раунде ${gameState.round} изгнания нет! Все выжившие гарантированно переходят в следующий раунд.`;
      }
    } else {
      debateBanner.classList.add('hidden');
    }

    // Host Command Bar visibility (always available to host during active game rounds)
    const isHost = (gameState.host_id === gameState.my_id);
    if (isHost && gameState.status === 'in_game') {
      hostCommandBar.classList.remove('hidden');
      if (hostTimerStatus) {
        hostTimerStatus.textContent = gameState.timer_paused ? '⏸️ Таймер на паузе' : `⏱️ Осталось: ${currentSec}с`;
        hostTimerStatus.className = gameState.timer_paused ? 'host-timer-status text-danger' : 'host-timer-status text-amber';
      }

      if (gameState.phase === 'debate') {
        if (gameState.round_has_voting) {
          hostSkipDebateBtn.textContent = '⏩ Пропустить дебаты / Голосовать';
        } else {
          hostSkipDebateBtn.textContent = `⏩ Завершить Раунд ${gameState.round} и продолжить`;
        }
        hostSkipDebateBtn.classList.remove('hidden');
        hostNextTurnBtn.classList.add('hidden');
      } else if (gameState.phase === 'turns') {
        if (gameState.round_has_voting) {
          hostSkipDebateBtn.textContent = '🗳️ Начать голосование досрочно';
        } else {
          hostSkipDebateBtn.textContent = `⏩ Завершить Раунд ${gameState.round} досрочно`;
        }
        hostSkipDebateBtn.classList.remove('hidden');
        hostNextTurnBtn.classList.remove('hidden');
      } else {
        hostSkipDebateBtn.classList.add('hidden');
        hostNextTurnBtn.classList.add('hidden');
      }
    } else {
      hostCommandBar.classList.add('hidden');
    }

    // Tabs info
    const survivorsCountEl = document.getElementById('tabSurvivorsCount');
    if (survivorsCountEl) survivorsCountEl.textContent = (gameState.players || []).length;
    const revPairs = (gameState.bunker_threat_pairs || []).filter(p => p.revealed).length;
    const bunkerRevEl = document.getElementById('tabBunkerRevealed');
    if (bunkerRevEl) bunkerRevEl.textContent = `${revPairs}/5`;

    renderSurvivorsGrid();
    renderMyDeck();
    renderBunkerTab();
    renderLiveLog();

    // Modal triggers based on phase
    if (gameState.phase === 'voting') {
      renderVotingModal();
    } else {
      votingModal.classList.add('hidden');
    }

    if (gameState.phase === 'vote_results') {
      renderVoteResultsModal();
    } else {
      voteResultsModal.classList.add('hidden');
    }

    if (gameState.status === 'finale') {
      renderFinaleModal();
    } else {
      finaleModal.classList.add('hidden');
    }
  }

  // --- TAB 1: SURVIVORS GRID (ALL PLAYERS) ---
  function renderSurvivorsGrid() {
    survivorsGrid.innerHTML = '';

    gameState.players.forEach(p => {
      const tile = document.createElement('div');
      tile.className = 'survivor-tile';
      if (p.is_active_turn) tile.classList.add('is-active-turn');
      if (p.is_exiled) tile.classList.add('is-exiled');

      // Count revealed cards
      const handValues = Object.values(p.hand);
      const revealedCards = handValues.filter(c => c.revealed);
      const hiddenCount = 6 - revealedCards.length;

      let statusHtml = '<span class="tile-status alive">Жив в бункере</span>';
      if (p.is_exiled) {
        statusHtml = '<span class="tile-status exiled">Изгнан</span>';
      } else if (p.is_active_turn) {
        statusHtml = '<span class="tile-status turn">🎤 ВЫСТУПАЕТ СЕЙЧАС</span>';
      }
      if (p.immunity_this_round) {
        statusHtml += ' <span class="tile-status" style="background: rgba(245, 158, 11, 0.2); border-color: var(--color-amber); color: var(--color-amber);">🛡️ Иммунитет</span>';
      }
      if (p.triple_vote) {
        statusHtml += ' <span class="tile-status" style="background: rgba(16, 185, 129, 0.2); border-color: var(--color-emerald); color: var(--color-emerald);">🧪 Голос x3</span>';
      }
      if (p.retaliation_active) {
        statusHtml += ' <span class="tile-status" style="background: rgba(239, 68, 68, 0.2); border-color: var(--color-danger); color: var(--color-danger);">🐶 Возмездие</span>';
      }
      if (p.is_silenced) {
        statusHtml += ' <span class="tile-status" style="background: rgba(148, 163, 184, 0.2); border-color: #94a3b8; color: #94a3b8;">🔇 Молчание</span>';
      }

      // Revealed pills
      let pillsHtml = '';
      revealedCards.slice(0, 3).forEach(c => {
        pillsHtml += `
          <div class="revealed-pill">
            <span class="pill-category">${translateCategory(c.category)}:</span>
            <strong>${escapeHtml(c.name || 'Раскрыто')}</strong> ${c.icon || ''}
          </div>
        `;
      });
      if (revealedCards.length > 3) {
        pillsHtml += `<div class="revealed-pill text-amber">+ ещё ${revealedCards.length - 3} в досье</div>`;
      }

      tile.innerHTML = `
        <div class="tile-header">
          <span class="tile-avatar">${p.avatar}</span>
          <div class="tile-info">
            <div class="tile-name">
              ${escapeHtml(p.name)} ${p.id === gameState.my_id ? '<em>(Вы)</em>' : ''}
            </div>
            ${statusHtml}
          </div>
        </div>
        <div class="tile-revealed-tags">
          ${pillsHtml || '<div class="hint-text">Карты ещё не вскрыты</div>'}
        </div>
        <div class="tile-hidden-counter">
          <span>🔒 Засекречено: ${hiddenCount}</span>
          <span class="text-amber">Открыть досье 🔍</span>
        </div>
      `;

      // TAP ON PLAYER OPENS THEIR DETAILED DOSSIER MODAL
      tile.addEventListener('click', () => {
        initAudio();
        soundClick();
        openPlayerDossier(p);
      });

      survivorsGrid.appendChild(tile);
    });
  }

  // Host manual voting starter
  hostStartVotingBtn.addEventListener('click', () => {
    initAudio();
    soundAlarm();
    ws.send(jsonStr({ action: 'start_voting' }));
  });

  // --- DOSSIER MODAL (DETAILED CARDS OF ANY PLAYER) ---
  function openPlayerDossier(player) {
    dosAvatar.textContent = player.avatar;
    dosName.textContent = player.name + (player.id === gameState.my_id ? ' (Вы)' : '');
    
    if (player.is_exiled) {
      dosStatusBadge.textContent = 'ИЗГНАН ИЗ БУНКЕРА';
      dosStatusBadge.className = 'status-pill exiled';
    } else {
      dosStatusBadge.textContent = 'ЖИВ В БУНКЕРЕ';
      dosStatusBadge.className = 'status-pill alive';
    }

    const handList = Object.entries(player.hand);
    const revCount = handList.filter(([_, c]) => c.revealed).length;
    dosRevealedCount.textContent = `${revCount}/6`;
    dosTurnStatus.textContent = player.is_active_turn ? 'Открывает карту' : 'Ожидает';

    dosCardsList.innerHTML = '';
    const categoryOrder = ['profession', 'biology', 'health', 'hobby', 'luggage', 'fact'];

    categoryOrder.forEach(cat => {
      const card = player.hand[cat];
      if (!card) return;

      const row = document.createElement('div');
      row.className = 'dossier-card-row ' + (card.revealed ? 'is-open' : 'is-locked');

      if (card.revealed) {
        row.innerHTML = `
          <div class="row-cat">👁️ ${translateCategory(cat)} (${card.badge || 'Характеристика'})</div>
          <div class="row-title">${escapeHtml(card.name)} ${card.icon || ''}</div>
          <div class="row-desc">${escapeHtml(card.desc || '')}</div>
          ${card.quote ? `<div class="card-quote">${escapeHtml(card.quote)}</div>` : ''}
        `;
      } else {
        row.innerHTML = `
          <div class="row-cat">🔒 ${translateCategory(cat)}</div>
          <div class="row-title">Засекречено владельцем</div>
          <div class="row-desc">Эта характеристика ещё не была открыта на голосованиях бункера.</div>
        `;
      }
      dosCardsList.appendChild(row);
    });

    dossierModal.classList.remove('hidden');
  }

  closeDossierBtn.addEventListener('click', () => {
    initAudio();
    soundClick();
    dossierModal.classList.add('hidden');
  });

  // --- TAB 2: MY DECK (SECRET CARDS) ---
  function renderMyDeck() {
    const me = gameState.players.find(p => p.id === gameState.my_id);
    if (!me) return;

    const isMyTurn = (gameState.active_player_id === gameState.my_id && gameState.phase === 'turns');
    const myDeckNotice = document.getElementById('myDeckNotice');

    if (isMyTurn) {
      myTurnAlert.classList.remove('hidden');
      myDeckNotice.classList.remove('hidden');
    } else {
      myTurnAlert.classList.add('hidden');
      myDeckNotice.classList.add('hidden');
    }

    myCardsGrid.innerHTML = '';
    const categoryOrder = ['profession', 'biology', 'health', 'hobby', 'luggage', 'fact'];

    categoryOrder.forEach(cat => {
      const card = me.hand[cat];
      if (!card) return;

      const cardEl = document.createElement('div');
      cardEl.className = 'game-card ' + (card.revealed ? 'revealed' : 'secret');

      const isEligibleToReveal = isMyTurn && !card.revealed && (!me.is_exiled) &&
        (gameState.round > 1 || cat === 'profession');

      cardEl.innerHTML = `
        <div class="card-top">
          <span class="card-category-tag">${translateCategory(cat)}</span>
          <span class="card-status-badge ${card.revealed ? 'open' : 'locked'}">
            ${card.revealed ? '👁️ Открыта всем' : '🔒 Только для вас'}
          </span>
        </div>
        <div class="card-title">${escapeHtml(card.name)} ${card.icon || ''}</div>
        <div class="card-desc">${escapeHtml(card.desc || '')}</div>
        ${card.quote ? `<div class="card-quote">${escapeHtml(card.quote)}</div>` : ''}
        ${isEligibleToReveal ? `<button class="reveal-btn" data-cat="${cat}">👁️ ВСКРЫТЬ КАРТУ ВСЕМ</button>` : ''}
      `;

      if (isEligibleToReveal) {
        const btn = cardEl.querySelector('.reveal-btn');
        btn.addEventListener('click', () => {
          initAudio();
          soundReveal();
          ws.send(jsonStr({ action: 'reveal_card', category: cat }));
        });
      }

      myCardsGrid.appendChild(cardEl);
    });

    // Special Condition card
    if (me.special_condition) {
      mySpecialName.textContent = me.special_condition.name;
      mySpecialDesc.textContent = me.special_condition.desc;
      mySpecialTiming.textContent = me.special_condition.timing || 'В любой момент';

      if (me.special_condition.played) {
        playSpecialBtn.disabled = true;
        playSpecialBtn.textContent = 'УЖЕ СЫГРАНО';
      } else {
        playSpecialBtn.disabled = false;
        playSpecialBtn.textContent = 'РАЗЫГРАТЬ КОЗЫРЬ';
      }
    }
  }

  playSpecialBtn.addEventListener('click', () => {
    const me = gameState.players.find(p => p.id === gameState.my_id);
    if (!me || !me.special_condition || me.special_condition.played) return;

    const spc = me.special_condition;
    const needsTarget = [
      'spc_swap_luggage',
      'spc_lie_detector',
      'spc_silence',
      'spc_steal_profession',
      'spc_swap_health'
    ].includes(spc.id);
    const aliveOpponents = gameState.players.filter(p => !p.is_exiled && p.id !== gameState.my_id);

    if (needsTarget) {
      if (aliveOpponents.length === 0) {
        showToast('⚠️ Нет доступных соперников для применения этой карты!');
        return;
      }
      if (aliveOpponents.length === 1) {
        if (confirm(`Разыграть козырь «${spc.name}» против игрока ${aliveOpponents[0].name}?`)) {
          initAudio();
          soundAlarm();
          ws.send(jsonStr({ action: 'play_special', target_id: aliveOpponents[0].id }));
        }
        return;
      }

      // Open target modal
      specialModalTitle.textContent = spc.name;
      specialModalPrompt.textContent = spc.desc;
      specialTargetsList.innerHTML = '';
      selectedSpecialTargetId = null;
      confirmSpecialTargetBtn.disabled = true;

      aliveOpponents.forEach(opp => {
        const item = document.createElement('div');
        item.className = 'candidate-item';
        item.innerHTML = `
          <span style="font-size: 1.8rem;">${opp.avatar}</span>
          <div>
            <strong style="color: #fff;">${escapeHtml(opp.name)}</strong>
            <div style="font-size: 0.8rem; color: var(--color-amber);">
              ${opp.hand.profession && opp.hand.profession.revealed ? opp.hand.profession.name : 'Выживший'}
            </div>
          </div>
        `;
        item.addEventListener('click', () => {
          initAudio();
          soundClick();
          specialTargetsList.querySelectorAll('.candidate-item').forEach(el => el.classList.remove('selected'));
          item.classList.add('selected');
          selectedSpecialTargetId = opp.id;
          confirmSpecialTargetBtn.disabled = false;
        });
        specialTargetsList.appendChild(item);
      });

      specialTargetModal.classList.remove('hidden');
    } else {
      // Direct activation
      if (confirm(`Вы уверены, что хотите разыграть «${spc.name}» прямо сейчас?\n\nДействие: ${spc.desc}`)) {
        initAudio();
        soundAlarm();
        ws.send(jsonStr({ action: 'play_special' }));
      }
    }
  });

  if (confirmSpecialTargetBtn) {
    confirmSpecialTargetBtn.addEventListener('click', () => {
      if (!selectedSpecialTargetId) return;
      initAudio();
      soundAlarm();
      ws.send(jsonStr({ action: 'play_special', target_id: selectedSpecialTargetId }));
      specialTargetModal.classList.add('hidden');
    });
  }

  if (closeSpecialModalBtn) {
    closeSpecialModalBtn.addEventListener('click', () => {
      specialTargetModal.classList.add('hidden');
    });
  }

  // --- TAB 3: BUNKER AND THREATS ---
  function renderBunkerTab() {
    bunkerPairsList.innerHTML = '';

    gameState.bunker_threat_pairs.forEach(pair => {
      const card = document.createElement('div');
      card.className = 'pair-card ' + (pair.revealed ? '' : 'locked');

      if (pair.revealed) {
        card.innerHTML = `
          <div class="bunker-slot">
            <div class="slot-label">📦 Раунд ${pair.round}: Отсек Бункера</div>
            <div class="slot-title">${escapeHtml(pair.bunker.name)}</div>
            <div class="slot-desc">${escapeHtml(pair.bunker.desc)}</div>
          </div>
          <div class="threat-slot">
            <div class="slot-label">⚠️ Раунд ${pair.round}: Угроза Бункера</div>
            <div class="slot-title">${escapeHtml(pair.threat.name)}</div>
            <div class="slot-desc">${escapeHtml(pair.threat.needed || pair.threat.desc)}</div>
          </div>
        `;
      } else {
        card.innerHTML = `
          <div class="bunker-slot" style="grid-column: 1 / -1; text-align: center;">
            <div class="slot-label">🔒 Раунд ${pair.round}: Запечатано</div>
            <div class="slot-title">Отсек Бункера и Угроза ещё не исследованы</div>
          </div>
        `;
      }

      bunkerPairsList.appendChild(card);
    });
  }

  // --- VOTING MODAL ---
  function renderVotingModal() {
    voteRoundNum.textContent = gameState.round;
    candidatesList.innerHTML = '';
    selectedVoteCandidateId = null;
    submitVoteBtn.disabled = true;

    const me = gameState.players.find(p => p.id === gameState.my_id);
    if (me && me.is_exiled) {
      candidatesList.innerHTML = `
        <div class="tab-hint" style="text-align: center; color: var(--color-danger); padding: 25px 15px;">
          <div style="font-size: 2.5rem; margin-bottom: 8px;">🚫</div>
          <strong style="font-size: 1.1rem; color: #fff;">ВЫ ИЗГНАНЫ ИЗ БУНКЕРА</strong>
          <p style="margin-top: 8px; color: var(--text-dim); font-size: 0.9rem;">
            Вы лишены права голоса и больше не влияете на выбор оставшихся претендентов на бункер.
          </p>
        </div>
      `;
      submitVoteBtn.classList.add('hidden');
      votingModal.classList.remove('hidden');
      return;
    }

    if (me && me.is_silenced) {
      candidatesList.innerHTML = `
        <div class="tab-hint" style="text-align: center; color: var(--color-amber); padding: 25px 15px;">
          <div style="font-size: 2.5rem; margin-bottom: 8px;">🔇</div>
          <strong style="font-size: 1.1rem; color: #fff;">НА ВАС НАЛОЖЕН ОБЕТ МОЛЧАНИЯ</strong>
          <p style="margin-top: 8px; color: var(--text-dim); font-size: 0.9rem;">
            В этом раунде вы лишены права голоса особой картой соперника.
          </p>
        </div>
      `;
      submitVoteBtn.classList.add('hidden');
      votingModal.classList.remove('hidden');
      return;
    }

    if (me && me.has_voted) {
      candidatesList.innerHTML = `
        <div class="tab-hint" style="text-align: center;">
          ✅ <strong>Ваш голос принят!</strong> Ожидаем остальных выживших...
        </div>
      `;
      submitVoteBtn.classList.add('hidden');
      votingModal.classList.remove('hidden');
      return;
    }

    submitVoteBtn.classList.remove('hidden');

    // Eligible candidates (alive players)
    const candidates = gameState.players.filter(p => !p.is_exiled && p.id !== gameState.my_id);

    candidates.forEach(cand => {
      const isImmune = !!cand.immunity_this_round;
      const item = document.createElement('div');
      item.className = 'candidate-item' + (isImmune ? ' disabled-immune' : '');
      item.innerHTML = `
        <span style="font-size: 1.8rem;">${cand.avatar}</span>
        <div>
          <strong style="color: #fff;">${escapeHtml(cand.name)}</strong>
          ${isImmune ? '<span class="hazard-badge" style="background: rgba(245, 158, 11, 0.2); border-color: var(--color-amber); color: var(--color-amber); margin-left: 6px;">🛡️ ИММУНИТЕТ</span>' : ''}
          <div style="font-size: 0.8rem; color: var(--color-amber);">
            ${cand.hand.profession && cand.hand.profession.revealed ? cand.hand.profession.name : 'Профессия скрыта'}
          </div>
        </div>
      `;

      if (!isImmune) {
        item.addEventListener('click', () => {
          initAudio();
          soundClick();
          candidatesList.querySelectorAll('.candidate-item').forEach(el => el.classList.remove('selected'));
          item.classList.add('selected');
          selectedVoteCandidateId = cand.id;
          submitVoteBtn.disabled = false;
        });
      } else {
        item.style.opacity = '0.5';
        item.style.cursor = 'not-allowed';
      }

      candidatesList.appendChild(item);
    });

    votingModal.classList.remove('hidden');
  }

  submitVoteBtn.addEventListener('click', () => {
    if (!selectedVoteCandidateId) return;
    initAudio();
    soundClick();
    ws.send(jsonStr({ action: 'cast_vote', target_id: selectedVoteCandidateId }));
  });

  // --- VOTE RESULTS MODAL ---
  function renderVoteResultsModal() {
    exileTitle.textContent = gameState.last_exiled ? `Игрок ${gameState.last_exiled} изгнан!` : 'Голоса равны!';
    
    votesBreakdownBox.innerHTML = '<strong>Итоги тайного подсчёта:</strong><br>';
    if (gameState.votes_summary) {
      for (const [candName, info] of Object.entries(gameState.votes_summary)) {
        votesBreakdownBox.innerHTML += `• ${escapeHtml(candName)}: ${info.count} голосов (голоса от: ${info.voters.join(', ')})<br>`;
      }
    }

    const isHost = (gameState.host_id === gameState.my_id);
    if (isHost) {
      hostNextRoundBtnBox.classList.remove('hidden');
    } else {
      hostNextRoundBtnBox.classList.add('hidden');
    }

    voteResultsModal.classList.remove('hidden');
  }

  confirmNextRoundBtn.addEventListener('click', () => {
    initAudio();
    soundClick();
    ws.send(jsonStr({ action: 'next_round_confirm' }));
  });

  // --- FINALE MODAL (AI OVERSEER) ---
  function renderFinaleModal() {
    const isHost = (gameState.host_id === gameState.my_id);

    if (gameState.ai_loading) {
      aiLaunchPrompt.classList.add('hidden');
      aiLoadingScanner.classList.remove('hidden');
      aiResultsDisplay.classList.add('hidden');
    } else if (gameState.ai_analysis) {
      aiLaunchPrompt.classList.add('hidden');
      aiLoadingScanner.classList.add('hidden');
      aiResultsDisplay.classList.remove('hidden');

      const a = gameState.ai_analysis;
      const pct = a.survival_percent || 50;
      aiScorePercent.textContent = `${pct}%`;
      aiTitleHeader.textContent = a.title || 'Итог экспедиции';
      aiVerdictParagraph.textContent = a.verdict || '';

      // Colorize gauge based on survival percentage
      if (pct >= 70) {
        aiScoreGauge.style.borderColor = 'var(--color-emerald)';
        aiScoreGauge.style.boxShadow = '0 0 25px rgba(16, 185, 129, 0.4)';
        aiStatusPill.className = 'status-pill alive';
        aiStatusPill.textContent = a.status || 'ПОЛНЫЙ УСПЕХ';
      } else if (pct >= 40) {
        aiScoreGauge.style.borderColor = 'var(--color-amber)';
        aiScoreGauge.style.boxShadow = '0 0 25px rgba(245, 158, 11, 0.4)';
        aiStatusPill.className = 'status-pill locked';
        aiStatusPill.textContent = a.status || 'ЧАСТИЧНЫЙ УСПЕХ';
      } else {
        aiScoreGauge.style.borderColor = 'var(--color-danger)';
        aiScoreGauge.style.boxShadow = '0 0 25px rgba(239, 68, 68, 0.4)';
        aiStatusPill.className = 'status-pill exiled';
        aiStatusPill.textContent = a.status || 'КОЛОНИЯ ВЫМЕРЛА';
      }

      // Render timeline cards
      aiTimelineGrid.innerHTML = '';
      (a.timeline || []).forEach(item => {
        const card = document.createElement('div');
        card.className = 'timeline-quarter-card';
        card.innerHTML = `
          <div class="timeline-period">${escapeHtml(item.period)}</div>
          <div class="timeline-event">${escapeHtml(item.event)}</div>
        `;
        aiTimelineGrid.appendChild(card);
      });

      // MVP and Troublemaker
      aiMvpName.textContent = a.mvp ? a.mvp.name : 'Не определён';
      aiMvpReason.textContent = a.mvp ? a.mvp.reason : '';

      aiTroubleName.textContent = a.troublemaker ? a.troublemaker.name : 'Не определён';
      aiTroubleReason.textContent = a.troublemaker ? a.troublemaker.reason : '';

      // Epilogue
      aiEpilogueText.textContent = a.epilogue || '';

      if (isHost) {
        newGameHostBtn.classList.remove('hidden');
      } else {
        newGameHostBtn.classList.add('hidden');
      }

    } else {
      // Launch state
      aiLaunchPrompt.classList.remove('hidden');
      aiLoadingScanner.classList.add('hidden');
      aiResultsDisplay.classList.add('hidden');

      if (isHost) {
        aiHostActionRow.classList.remove('hidden');
        aiWaitNotice.classList.add('hidden');
      } else {
        aiHostActionRow.classList.add('hidden');
        aiWaitNotice.classList.remove('hidden');
      }
    }

    finaleModal.classList.remove('hidden');
  }

  triggerAiBtn.addEventListener('click', () => {
    initAudio();
    soundAlarm();
    ws.send(jsonStr({ action: 'run_ai_analysis' }));
  });


  newGameHostBtn.addEventListener('click', () => {
    initAudio();
    soundAlarm();
    ws.send(jsonStr({ action: 'reset_game' }));
  });

  // --- HOST COMMAND BAR EVENT LISTENERS ---
  if (hostSkipDebateBtn) {
    hostSkipDebateBtn.addEventListener('click', () => {
      initAudio();
      soundAlarm();
      ws.send(jsonStr({ action: 'skip_debate' }));
    });
  }

  if (hostExtendTimerBtn) {
    hostExtendTimerBtn.addEventListener('click', () => {
      initAudio();
      soundClick();
      ws.send(jsonStr({ action: 'extend_timer', seconds: 30 }));
    });
  }

  if (hostPauseTimerBtn) {
    hostPauseTimerBtn.addEventListener('click', () => {
      initAudio();
      soundClick();
      ws.send(jsonStr({ action: 'toggle_pause_timer' }));
    });
  }

  if (hostNextTurnBtn) {
    hostNextTurnBtn.addEventListener('click', () => {
      initAudio();
      soundClick();
      ws.send(jsonStr({ action: 'force_next_turn' }));
    });
  }

  // --- LIVE LOG ---
  function renderLiveLog() {
    liveLogList.innerHTML = '';
    (gameState.log || []).forEach(msg => {
      const line = document.createElement('div');
      line.textContent = msg;
      liveLogList.appendChild(line);
    });
    liveLogList.scrollTop = liveLogList.scrollHeight;
  }

  function translateCategory(cat) {
    const map = {
      profession: 'Профессия',
      biology: 'Биология',
      health: 'Здоровье',
      hobby: 'Хобби',
      luggage: 'Багаж',
      fact: 'Факт'
    };
    return map[cat] || cat;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Quick view catastrophe button in HUD
  document.getElementById('viewCatastropheBtn').addEventListener('click', () => {
    initAudio();
    soundClick();
    tabButtons.forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelector('[data-tab="tabBunker"]').classList.add('active');
    tabBunker.classList.add('active');
  });

  // Start WS on load
  connectWebSocket();

})();
