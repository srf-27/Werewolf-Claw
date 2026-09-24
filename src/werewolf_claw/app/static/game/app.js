// 对局看板：可收起的对局栏、座位、大屏（含狼频道）、法官悬停播报、人类接管面板。

const KIND_LABELS = {
  opening: "开场", role: "身份", wake: "睁眼", phase_over: "闭眼", ask: "询问",
  receipt: "回执", team_talk: "狼人频道", phase_target: "狼刀", result: "出局",
  alive: "存活", order: "顺序", statement: "发言", vote_notice: "投票通知",
  ballot: "票型", vote: "计票", death: "出局", elimination: "放逐",
  hunter_shot: "开枪", continue: "继续", game_over: "结束",
};

// 前端展示统一用中文，后台（协议、板子、存储）保留英文身份名
const ROLE_LABELS = {
  Werewolf: "狼人", Seer: "预言家", Witch: "女巫", Hunter: "猎人", Villager: "村民",
};
const CAMP_LABELS = {
  "Werewolf 阵营": "狼人阵营", "好人阵营": "好人阵营",
};
// 板子组成用「emoji×数量」直观展示
const ROLE_EMOJI = {
  Werewolf: "🐺", Seer: "🔮", Witch: "🧪", Hunter: "🔫", Villager: "🧑‍🌾",
};

function roleLabel(role) {
  return ROLE_LABELS[role] || role || "";
}

function campLabel(camp) {
  return CAMP_LABELS[camp] || camp || "";
}

// 会显示在法官悬停框里的播报
const JUDGE_KINDS = new Set([
  "opening", "wake", "phase_over", "result", "alive", "order", "vote_notice",
  "vote", "death", "elimination", "hunter_shot", "continue", "game_over",
]);

const STATUS_LABELS = {
  ready: "准备中", running: "进行中", finished: "已结束", failed: "出错",
};

const SPEEDS = [1, 1.5, 2];
const FLOAT_MS = 5000; // 法官每一句悬停 5 秒
const AVATARS = [
  "/static/avatars/user.svg",
  "/static/avatars/assistant.svg",
  "/static/avatars/system.svg",
  "/static/avatars/tool.svg",
];
const WOLF_AVATAR = "/static/avatars/tool.svg";
const PRIVATE_AVATAR = "/static/avatars/user.svg";
const API = "/api/game";
const THEME_KEY = "werewolf-demo-theme";
const SIDEBAR_KEY = "werewolf-demo-sidebar";
const LIST_REFRESH_POLLS = 4;

const el = (id) => document.getElementById(id);

let gameId = "";
let snapshot = null;
let boards = [];
let profiles = [];
let followLatest = true;
let polling = false;
let pollCount = 0;
let speedIndex = 0;
let floatSeq = 0;
let floatTimer = null;
let floatShownAt = 0;
let pickedTarget = null;

function seatAvatar(seat) {
  return AVATARS[(seat - 1) % AVATARS.length];
}

function isWolfChannel(message) {
  return message.channel === "private" && message.audience.length > 1;
}

function api(path, options) {
  return fetch(path, options).then((response) => {
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  });
}

function post(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function fetchSnapshot(id) {
  const god = el("god-view").checked ? "?god=1" : "";
  return api(`${API}/games/${id}${god}`);
}

// ------------------------------------------------------------------ 对局栏

function applySidebar(collapsed) {
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  el("sidebar-toggle").textContent = collapsed ? "展开" : "收起";
  localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
}

function renderGameList(list) {
  const box = el("game-list");
  box.textContent = "";
  if (!list.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "还没有对局";
    box.append(empty);
  }
  for (const game of list) {
    const item = document.createElement("li");
    item.className = `game-item ${game.id === gameId ? "active" : ""}`;
    item.dataset.id = game.id;
    item.tabIndex = 0;
    const row = document.createElement("div");
    row.className = "row";
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = game.board_name;
    const state = document.createElement("span");
    state.className = "meta";
    state.textContent = game.winner
      ? `${STATUS_LABELS[game.status] || game.status}·${campLabel(game.winner)}胜`
      : STATUS_LABELS[game.status] || game.status;
    row.append(name, state);
    const meta = document.createElement("div");
    meta.className = "row meta";
    meta.textContent = `第 ${game.day} 天${game.stopped ? " · 已结束" : ""}`;
    const del = document.createElement("button");
    del.className = "game-delete";
    del.textContent = "删除";
    del.title = "删掉这一局";
    del.addEventListener("click", (event) => {
      event.stopPropagation();
      api(`${API}/games/${game.id}`, { method: "DELETE" })
        .then(() => {
          if (game.id === gameId) {
            // 删掉的是当前这局：切到还在跑的那局，没有就回房间，别停在被删的对局上
            gameId = "";
            location.hash = "";
            return api(`${API}/live`).then((live) => {
              if (live.latest) {
                gameId = live.latest;
                location.hash = gameId;
                followLatest = true;
                return fetchSnapshot(gameId).then(render);
              }
              snapshot = null;
              openRoom();
              return null;
            });
          }
          return null;
        })
        .then(loadGames)
        .catch(() => {});
    });
    const foot = document.createElement("div");
    foot.className = "row";
    foot.append(meta, del);
    item.append(row, foot);
    box.append(item);
  }
}

function loadGames() {
  return api("/api/game/games").then(renderGameList);
}

function onGameListClick(event) {
  const item = event.target.closest(".game-item");
  if (item && item.dataset.id) switchGame(item.dataset.id);
}

function switchGame(id) {
  if (!id || id === gameId) return;
  followLatest = false;
  location.hash = id;
  const previous = gameId;
  const stop =
    previous && snapshot && snapshot.status === "running"
      ? post(`/api/game/games/${previous}/stop`).catch(() => {})
      : Promise.resolve();
  stop.then(() => fetchSnapshot(id)).then(render).then(loadGames).catch(() => {});
}

// ------------------------------------------------------------------ 房间设置

function boardText(board) {
  const counts = new Map();
  for (const role of board.distribution) counts.set(role, (counts.get(role) || 0) + 1);
  const roles = [...counts]
    .map(([role, count]) => {
      const emoji = ROLE_EMOJI[role] || roleLabel(role);
      return count > 1 ? `${emoji}×${count}` : emoji;
    })
    .join("+");
  return `${board.size} 人：${roles} · 夜晚 ${board.night_phases.map(roleLabel).join("→") || "无"}`;
}

function profileOptions(select, selected) {
  select.textContent = "";
  for (const profile of profiles) {
    const option = document.createElement("option");
    option.value = profile.id;
    option.textContent = `${profile.name}${profile.model ? `（${profile.model}）` : ""}`;
    if (profile.id === selected) option.selected = true;
    select.append(option);
  }
  const rules = document.createElement("option");
  rules.value = "rules";
  rules.textContent = "纯规则（不联网）";
  select.append(rules);
  const add = document.createElement("option");
  add.value = "__new__";
  add.textContent = "＋ 新增模型配置…";
  select.append(add);
  select.dataset.prev = select.value;
  select.addEventListener("change", () => {
    if (select.value !== "__new__") {
      select.dataset.prev = select.value;
      return;
    }
    // 选了“新增配置”就弹表单，自身先回到原来的选择
    select.value = select.dataset.prev || (profiles[0] ? profiles[0].id : "rules");
    el("profile-hint").textContent = "";
    el("profile-form").hidden = false;
  });
}

function renderRoomSeats() {
  const board = boards.find((item) => item.id === el("room-board").value);
  const box = el("room-seats");
  box.textContent = "";
  if (!board) return;
  const lead = document.createElement("div");
  lead.className = "room-lead";
  lead.textContent = "勾选座位前的框：开局就由你亲自扮演这个位置（最多选一个，之后也能在座位卡上接管 / 退出）";
  box.append(lead);
  const rows = [{ key: "judge", label: "法官" }];
  for (let seat = 1; seat <= board.size; seat += 1) {
    rows.push({ key: String(seat), label: `${seat} 号` });
  }
  const all = el("room-all").value;
  for (const row of rows) {
    if (row.key === "1") {
      const sep = document.createElement("div");
      sep.className = "room-sep";
      sep.textContent = "玩家";
      box.append(sep);
    }
    const line = document.createElement("label");
    line.className = "seat-model";
    const name = document.createElement("span");
    name.className = "seat-label";
    name.textContent = row.label;
    const select = document.createElement("select");
    select.dataset.seat = row.key;
    profileOptions(select, all);
    if (row.key === "judge") {
      line.append(name, select);
    } else {
      const human = document.createElement("input");
      human.type = "checkbox";
      human.className = "seat-human";
      human.dataset.seat = row.key;
      human.title = "开局就由人来玩这个位置";
      line.append(name, human, select);
    }
    box.append(line);
  }
  // 只能有一个位置由人来玩
  for (const box of el("room-seats").querySelectorAll(".seat-human")) {
    box.addEventListener("change", () => {
      if (!box.checked) return;
      for (const other of el("room-seats").querySelectorAll(".seat-human")) {
        if (other !== box) other.checked = false;
      }
    });
  }
}

function loadBoards() {
  return api("/api/game/boards").then((list) => {
    boards = list;
    const select = el("room-board");
    select.textContent = "";
    for (const board of list) {
      const option = document.createElement("option");
      option.value = board.id;
      option.textContent = board.name;
      select.append(option);
    }
    // 只有一种板子：组成直接以文本展示，不再显示锁定的下拉框
    select.hidden = true;
    const text = el("room-board-text");
    if (text) {
      text.textContent = list.length ? boardText(list[0]) : "";
    }
    renderRoomSeats();
    updateRoomHint();
  });
}

function loadModels() {
  return api("/api/game/models").then((data) => {
    profiles = data.profiles || [];
    profileOptions(el("room-all"), data.active);
    renderRoomSeats();
    updateRoomHint();
  });
}

function updateRoomHint() {
  const board = boards.find((item) => item.id === el("room-board").value);
  el("room-hint").textContent = board ? "每个 Agent 都能单独选模型；选「纯规则」的座位不联网。" : "";
}

function openRoom() {
  el("room").hidden = false;
  updateRoomHint();
}

function startGame() {
  const button = el("room-start");
  button.disabled = true;
  const profilesBySeat = {};
  const humans = [];
  let useModel = false;
  for (const select of el("room-seats").querySelectorAll("select")) {
    const value = select.value;
    // 直接传 select.value：profile id 或 "rules"。后端识别 "rules" 走纯规则。
    profilesBySeat[select.dataset.seat] = value;
    if (value !== "rules") useModel = true;
  }
  for (const box of el("room-seats").querySelectorAll(".seat-human")) {
    if (box.checked) humans.push(Number(box.dataset.seat));
  }
  post("/api/game/games", {
    board: el("room-board").value,
    model: useModel,
    // profile 留空：全局兜底用当前生效的配置；各座位/法官各自的选择走 profiles。
    // 之前传 judge 会让后端把法官配置当成全局默认，导致没单独配的座位全用法官那套。
    profile: "",
    profiles: profilesBySeat,
    humans,
  })
    .then((data) => {
      gameId = data.id;
      followLatest = true;
      location.hash = data.id;
      render(data);
      el("room").hidden = true;
      return loadGames();
    })
    .catch((error) => {
      el("room-hint").textContent = `开局失败：${error.message}`;
    })
    .finally(() => {
      button.disabled = false;
    });
}

// ------------------------------------------------------------------ 顶栏

function renderStatus(data) {
  el("chip-day").textContent = `第 ${data.day} 天`;
  el("chip-phase").textContent = data.phase === "night" ? "夜晚" : "白天";
  el("chip-paused").hidden = !data.paused;

  const state = el("chip-state");
  state.className = `chip ${data.status}`;
  state.textContent = STATUS_LABELS[data.status] || data.status;
  if (data.status === "finished" && data.winner) {
    state.textContent = `已结束：${campLabel(data.winner)}获胜`;
  }
  if (data.status === "failed") state.textContent = `出错：${data.error}`;
  el("chip-alive").textContent = `存活 ${data.alive.length}：${data.alive.join("、") || "无"}`;
  el("chip-time").textContent = `${data.elapsed.toFixed(1)}s`;
  el("chip-board").textContent = `${data.board.name} · ${data.board.size} 人`;
  el("pause").textContent = data.paused ? "继续" : "暂停";
  el("pause").disabled = data.status !== "running";
  el("speed").textContent = `${data.speed}×`;

  // 法官模型名提前给足空间：显示配置名，纯规则显示「无模型」
  const judgeModel = data.judge_model || "无模型";
  el("model-name").textContent = `1 名法官（${judgeModel}） + ${data.seats.length} 名玩家`;
}

function togglePause() {
  if (!gameId || !snapshot || snapshot.status !== "running") return;
  post(`/api/game/games/${gameId}/${snapshot.paused ? "resume" : "pause"}`).then(render).catch(() => {});
}

function cycleSpeed() {
  if (!gameId) return;
  speedIndex = (speedIndex + 1) % SPEEDS.length;
  post(`/api/game/games/${gameId}/speed`, { speed: SPEEDS[speedIndex] }).then(render).catch(() => {});
}

// ------------------------------------------------------------------ 座位

function seatAction(seat) {
  if (!gameId || !snapshot || snapshot.status !== "running") return;
  const path = seat.human
    ? `/api/game/games/${gameId}/seats/${seat.seat}/release`
    : `/api/game/games/${gameId}/seats/${seat.seat}/takeover`;
  post(path).then(render).catch(() => {});
}

function buildSeat(seat) {
  const card = document.createElement("div");
  card.className = `seat ${seat.alive ? "" : "dead"} ${seat.human ? "human" : ""}`;
  const avatar = document.createElement("img");
  avatar.className = "avatar";
  avatar.src = seatAvatar(seat.seat);
  avatar.alt = seat.name;
  card.append(avatar);

  const info = document.createElement("div");
  info.className = "info";
  const head = document.createElement("div");
  head.className = "line";
  const no = document.createElement("span");
  no.className = "no";
  no.textContent = String(seat.seat);
  const name = document.createElement("span");
  name.className = "seat-name";
  name.textContent = seat.name;
  head.append(no, name);
  if (!seat.alive) {
    const dead = document.createElement("span");
    dead.className = "badge muted";
    dead.textContent = "出局";
    head.append(dead);
  }
  info.append(head);
  // 身份直接显示在名字下方：上帝视角下所有人可见，人类接管者看自己的
  const roleLine = document.createElement("div");
  roleLine.className = `seat-role ${seat.camp && seat.camp.includes("Werewolf") ? "wolf" : "good"}`;
  if (seat.role) {
    roleLine.textContent = `身份：${roleLabel(seat.role)}`;
  } else {
    roleLine.classList.add("placeholder"); // 占位：身份出现时座位卡不会突然撑开
  }
  info.append(roleLine);
  const model = document.createElement("div");
  model.className = "model";
  model.textContent = seat.human ? "人类接管" : seat.model || "无模型";
  model.title = model.textContent;
  info.append(model);
  card.append(info);

  const button = document.createElement("button");
  button.className = "seat-takeover";
  button.textContent = seat.human ? "退出" : "接管";
  button.addEventListener("click", () => seatAction(seat));
  card.append(button);
  return card;
}

function renderSeats(data) {
  // 固定 9 人布局：1-4 号在左列，5-9 号在右列。
  // 只有一种板子，座位位置固定下来不再随人数动态切分。
  const seats = [...data.seats].sort((a, b) => a.seat - b.seat);
  const left = el("seats-left");
  const right = el("seats-right");
  left.textContent = "";
  right.textContent = "";
  for (const seat of seats) {
    if (seat.seat <= 4) left.append(buildSeat(seat));
    else right.append(buildSeat(seat));
  }
}

// ------------------------------------------------------------------ 大屏

function buildMessage(message, names) {
  const wolf = isWolfChannel(message);
  const isJudge = message.channel === "public" && JUDGE_KINDS.has(message.kind);
  const speech = message.kind === "statement" || message.kind === "ballot";
  const row = document.createElement("li");
  row.className = `msg-row ${wolf ? "wolf" : speech ? "statement" : isJudge ? "judge" : "night"}`;
  const avatar = document.createElement("img");
  avatar.className = "avatar";
  avatar.alt = "";
  avatar.src = wolf
    ? WOLF_AVATAR
    : message.channel === "private"
      ? PRIVATE_AVATAR
      : seatAvatar(Number((message.text.match(/^(\d+)\s*号/) || [])[1]) || 1);
  row.append(avatar);
  const stack = document.createElement("div");
  stack.className = "msg-stack";
  // 玩家消息：序号和昵称放头像旁边，正文里不再重复
  const match = message.text.match(/^(\d+)\s*号[：:]\s*(.*)$/s);
  const body = match ? match[2] : message.text;
  if (match && message.channel === "public") {
    const seat = Number(match[1]);
    const head = document.createElement("div");
    head.className = "msg-head";
    head.textContent = `${seat} 号 · ${names.get(seat) || ""}`;
    stack.append(head);
  }
  const tag = document.createElement("span");
  tag.className = "tag";
  const label = KIND_LABELS[message.kind] || message.kind || "消息";
  if (wolf) tag.textContent = `狼频道 ${message.audience.join("、")} · ${label}`;
  else if (message.channel === "private") tag.textContent = `私聊 ${message.audience.join("、")} · ${label}`;
  else tag.textContent = label;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = body;
  stack.append(tag, bubble);
  row.append(stack);
  return row;
}

function renderMessages(data) {
  const list = el("messages");
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
  const names = new Map(data.seats.map((seat) => [seat.seat, seat.name]));
  const reveal = el("god-view").checked; // 身份只在上帝视角下公开
  const onlyPublic = el("only-public").checked;
  const rows = data.messages.filter((message) =>
    message.channel === "public" ? true : reveal && !onlyPublic,
  );
  list.textContent = "";
  if (!rows.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "点右上角「新对局」选好板子和模型就能开一局。";
    list.append(empty);
  }
  for (const message of rows) list.append(buildMessage(message, names));
  // 最新的停在 70% 高度，下面留白给法官悬停框和人类输入面板
  if (atBottom) list.scrollTop = Math.max(0, list.scrollHeight - list.clientHeight * 0.7);
}

// 法官播报：悬停框显示 5 秒，等上一句消失服务端才发下一句
function renderJudgeFloat(data) {
  const latest = [...data.messages]
    .reverse()
    .find((message) => message.channel === "public" && JUDGE_KINDS.has(message.kind));
  const box = el("judge-float");
  if (!latest) {
    box.hidden = true;
    return;
  }
  // 同一句只弹一次：暂停时定住不收，恢复后再补上剩下的时间
  if (latest.seq !== floatSeq) {
    floatSeq = latest.seq;
    el("judge-float-text").textContent = latest.text;
    box.hidden = false;
    floatShownAt = Date.now();
  }
  if (floatTimer) {
    clearTimeout(floatTimer);
    floatTimer = null;
  }
  if (data.paused) return;
  const shown = (Date.now() - floatShownAt) / 1000;
  const left = Math.max(0.2, FLOAT_MS / 1000 / Math.max(1, data.speed || 1) - shown);
  floatTimer = setTimeout(() => {
    box.hidden = true;
  }, left * 1000);
}

// ------------------------------------------------------------------ 人类接管

function humanIdentity(pending) {
  const team = pending.allies && pending.allies.length ? ` · 队友 ${pending.allies.join("、")} 号` : "";
  return `${pending.seat} 号 ${pending.name} · ${roleLabel(pending.role)}${team}`;
}

// 面板只在这个 key 变化时重建：同一个请求里每秒的轮询只更新倒计时，
// 不再重建输入框，否则人正在打字就被清空了
let humanKey = "";
let humanInput = null;

function renderHuman(data) {
  const panel = el("human-panel");
  const pending = data.pending;
  if (!pending) {
    panel.hidden = true;
    humanKey = "";
    humanInput = null;
    pickedTarget = null;
    return;
  }
  panel.hidden = false;
  const key = `${pending.seat}:${pending.kind}`;
  el("human-title").textContent = `${humanIdentity(pending)} · 轮到${pending.kind}`;
  el("human-left").textContent = `剩余 ${Math.max(0, pending.left).toFixed(0)}s`;

  if (key !== humanKey) {
    humanKey = key;
    pickedTarget = null;
    buildHumanBody(pending);
  }
}

function buildWitchBody(pending, body) {
  const ctx = pending.context;
  const attacked = ctx.attacked;
  const hasSave = !ctx.used_save;
  const hasPoison = !ctx.used_poison;
  const seats = [...snapshot.seats].filter((s) => s.alive);

  // 没药了：自动跳过
  if (!hasSave && !hasPoison) {
    const hint = document.createElement("div");
    hint.className = "hint";
    hint.textContent = "解药和毒药都已用完，这一夜没有动作。";
    body.append(hint);
    setTimeout(() => submitHuman({ target: null, text: "", effect: "" }), 600);
    return;
  }

  // 有解药且有人被袭：可以救
  if (hasSave && attacked != null) {
    const targetSeat = seats.find((s) => s.seat === attacked);
    const info = document.createElement("div");
    info.className = "hint";
    info.textContent = `今晚 ${attacked} 号${targetSeat ? "（" + targetSeat.name + "）" : ""}被狼人袭击。`;
    body.append(info);

    const actions = document.createElement("div");
    actions.className = "witch-actions";
    const saveBtn = document.createElement("button");
    saveBtn.className = "primary";
    saveBtn.textContent = `使用解药救 ${attacked} 号`;
    saveBtn.addEventListener("click", () => {
      submitHuman({ target: attacked, text: "", effect: "save" });
    });
    const noSaveBtn = document.createElement("button");
    noSaveBtn.className = "ghost";
    noSaveBtn.textContent = hasPoison ? "不救，看看毒谁" : "不救";
    noSaveBtn.addEventListener("click", () => {
      if (hasPoison) {
        info.remove();
        actions.remove();
        buildWitchPoison(body, seats);
      } else {
        submitHuman({ target: null, text: "", effect: "" });
      }
    });
    actions.append(saveBtn, noSaveBtn);
    body.append(actions);
    return;
  }

  // 有解药但没人被袭，或已用解药：直接进毒药
  if (hasPoison) {
    if (hasSave && attacked == null) {
      const hint = document.createElement("div");
      hint.className = "hint";
      hint.textContent = "今晚没有人被袭击，解药用不上。";
      body.append(hint);
    }
    buildWitchPoison(body, seats);
    return;
  }

  // 有解药但没人被袭，没毒药
  const hint = document.createElement("div");
  hint.className = "hint";
  hint.textContent = "今晚没有人被袭击，也没有毒药可用。";
  body.append(hint);
  setTimeout(() => submitHuman({ target: null, text: "", effect: "" }), 600);
}

function buildWitchPoison(body, seats) {
  const label = document.createElement("div");
  label.className = "hint";
  label.textContent = "选择要毒的人：";
  body.append(label);
  const picker = document.createElement("div");
  picker.className = "pick-grid";
  let picked = null;
  for (const seat of seats) {
    const button = document.createElement("button");
    button.className = "pick";
    button.textContent = `${seat.seat} ${seat.name}`;
    button.addEventListener("click", () => {
      picked = seat.seat;
      for (const other of picker.querySelectorAll(".pick")) other.classList.remove("on");
      button.classList.add("on");
    });
    picker.append(button);
  }
  const confirm = document.createElement("button");
  confirm.className = "primary";
  confirm.textContent = "确定毒杀";
  confirm.addEventListener("click", () => {
    if (picked === null) return;
    submitHuman({ target: picked, text: "", effect: "poison" });
  });
  const skip = document.createElement("button");
  skip.className = "ghost";
  skip.textContent = "不使用毒药";
  skip.addEventListener("click", () => {
    submitHuman({ target: null, text: "", effect: "" });
  });
  picker.append(confirm, skip);
  body.append(picker);
}

function buildHumanBody(pending) {
  const bar = el("human-bar");
  bar.style.transition = "none";
  bar.style.width = "100%";
  requestAnimationFrame(() => {
    bar.style.transition = `width ${Math.max(0.2, pending.timeout || pending.left)}s linear`;
    bar.style.width = "0%";
  });

  const body = el("human-body");
  body.textContent = "";
  // 女巫技能面板：救/毒/不用三选，比通用目标选择器清晰
  if (pending.kind === "技能" && pending.role === "Witch" && pending.context) {
    buildWitchBody(pending, body);
    return;
  }
  if (pending.kind === "投票" || pending.kind === "技能" || pending.kind === "出局技能") {
    const seats = [...snapshot.seats].filter((seat) => seat.alive);
    const picker = document.createElement("div");
    picker.className = "pick-grid";
    for (const seat of seats) {
      const button = document.createElement("button");
      button.className = "pick";
      button.textContent = `${seat.seat} ${seat.name}`;
      button.addEventListener("click", () => {
        pickedTarget = seat.seat;
        for (const other of picker.querySelectorAll(".pick")) other.classList.remove("on");
        button.classList.add("on");
      });
      picker.append(button);
    }
    const confirm = document.createElement("button");
    confirm.className = "primary";
    confirm.textContent = "确定";
    confirm.addEventListener("click", () => {
      if (pickedTarget === null) return;
      submitHuman({ target: pickedTarget, text: "" });
    });
    picker.append(confirm);
    // 技能可以主动不用（女巫捏着药）：空目标提交为明确的弃权
    if (pending.kind === "技能") {
      const pass = document.createElement("button");
      pass.className = "ghost";
      pass.textContent = "不使用技能";
      pass.addEventListener("click", () => {
        pickedTarget = null;
        for (const other of picker.querySelectorAll(".pick")) other.classList.remove("on");
        submitHuman({ target: null, text: "" });
      });
      picker.append(pass);
    }
    if (pending.kind !== "投票") {
      const hint = document.createElement("div");
      hint.className = "hint";
      hint.textContent = `你的身份：${roleLabel(pending.role)}`;
      body.append(hint);
    }
    body.append(picker);
    return;
  }

  const input = document.createElement("textarea");
  input.id = "human-text";
  input.rows = 3;
  input.placeholder = pending.kind === "发言" ? "写你的公开发言（不超过 200 字）" : "说一句你的意见";
  const send = document.createElement("button");
  send.className = "primary";
  send.textContent = "发送";
  send.addEventListener("click", () => {
    if (!input.value.trim()) return;
    submitHuman({ text: input.value.trim(), target: null });
  });
  const actions = document.createElement("div");
  actions.className = "human-actions";
  actions.append(send);
  body.append(input, actions);
  humanInput = input;
  input.focus();
}

function submitHuman(payload) {
  if (!gameId || !snapshot || !snapshot.pending) return;
  const seat = snapshot.pending.seat;
  post(`/api/game/games/${gameId}/seats/${seat}/input`, payload).then((data) => {
    pickedTarget = null;
    render(data);
  });
}

function render(data) {
  snapshot = data;
  renderStatus(data);
  renderSeats(data);
  renderMessages(data);
  renderJudgeFloat(data);
  renderHuman(data);
  renderAssistant(data);
}

// ------------------------------------------------------------------ 玩家助手

// 接管座位后右下角出现助手按钮：小窗可拖动、可隐藏、半透明，
// 内容只装这个玩家位置能掌握的信息（身份、队友、查验记录）+ 向量库建议。

let assistantSeat = 0;
let assistantDrag = null;

function renderAssistant(data) {
  const button = el("assistant-toggle");
  // 页面被缓存成旧版 HTML 时会缺助手元素：跳过，别让轮询整条崩掉
  if (!button) return;
  assistantSeat = data.humans && data.humans.length ? data.humans[0] : 0;
  // 只在人类接管且对局进行中时出现
  button.hidden = !assistantSeat || data.status !== "running";
  const win = el("assistant-win");
  if (button.hidden && win) win.hidden = true;
}

function openAssistant() {
  const win = el("assistant-win");
  win.hidden = false;
  renderAssistantBody();
  loadAssistantMemory();
}

function renderAssistantBody() {
  const body = el("assistant-body");
  body.textContent = "";
  const pending = snapshot && snapshot.pending;
  const isMe = pending && pending.seat === assistantSeat;

  const identity = document.createElement("div");
  identity.className = "assistant-sec";
  identity.id = "assistant-identity";
  const role = isMe ? roleLabel(pending.role) : "？";
  const camp = isMe ? campLabel(pending.camp) : "从私聊身份卡同步";
  identity.textContent = `你接管了 ${assistantSeat} 号 · ${role}（${camp}）`;
  body.append(identity);

  // 队友（狼人）：优先用挂起请求里的队友表，退回私聊记录
  const allies = (isMe && pending.allies) || [];
  const mateSec = document.createElement("div");
  mateSec.className = "assistant-sec";
  mateSec.textContent = allies.length ? `你的队友：${allies.join("、")} 号` : "暂无队友情报";
  body.append(mateSec);

  // 预言家的查验记录（占位，私聊记录到了之后填充）
  const checkSec = document.createElement("div");
  checkSec.className = "assistant-sec";
  checkSec.id = "assistant-checks";
  checkSec.textContent = "查验记录加载中…";
  body.append(checkSec);

  const adviceSec = document.createElement("div");
  adviceSec.className = "assistant-sec";
  const question = document.createElement("textarea");
  question.id = "assistant-question";
  question.rows = 2;
  question.placeholder = "（可选）想问什么？留空就让助手按当前形势给建议";
  const ask = document.createElement("button");
  ask.className = "primary";
  ask.id = "assistant-ask";
  ask.textContent = "求助（检索相似对局）";
  ask.addEventListener("click", requestAdvice);
  const output = document.createElement("div");
  output.className = "assistant-advice";
  output.id = "assistant-advice";
  output.textContent = "";
  adviceSec.append(question, ask, output);
  body.append(adviceSec);
}

function loadAssistantMemory() {
  if (!gameId || !assistantSeat) return;
  api(`${API}/games/${gameId}/seats/${assistantSeat}/memory`)
    .then((rows) => {
      const checks = [];
      const allies = new Set();
      let role = "";
      let camp = "";
      for (const row of rows) {
        const facts = row.facts || {};
        if (facts.check && facts.check.target != null) {
          checks.push(`第 ${row.day} 天查验 ${facts.check.target} 号：${campLabel(facts.check.camp)}`);
        }
        if (row.kind === "role" && facts.role) {
          role = facts.role;
          camp = facts.camp || "";
        }
        if (row.kind === "phase" && facts.seats) {
          for (const seat of facts.seats) if (Number(seat) !== assistantSeat) allies.add(Number(seat));
        }
      }
      const identity = el("assistant-identity");
      if (identity && role) {
        identity.textContent = `你接管了 ${assistantSeat} 号 · ${roleLabel(role)}（${campLabel(camp)}）`;
      }
      const checkSec = el("assistant-checks");
      if (checkSec) {
        checkSec.textContent = checks.length ? `查验记录：\n${checks.join("\n")}` : "查验记录：暂无";
      }
      const mateSec = el("assistant-win").querySelector(".assistant-sec:nth-of-type(2)");
      if (mateSec && allies.size) {
        mateSec.textContent = `你的队友：${[...allies].sort((a, b) => a - b).join("、")} 号`;
      }
    })
    .catch(() => {});
}

function requestAdvice() {
  const output = el("assistant-advice");
  const ask = el("assistant-ask");
  const question = (el("assistant-question").value || "").trim();
  ask.disabled = true;
  output.textContent = "检索中，第一次调用要加载 embedding 模型，可能要等一会儿…";
  post(`${API}/games/${gameId}/seats/${assistantSeat}/advice`, { query: question })
    .then((data) => {
      if (data.status) {
        output.textContent = `向量检索不可用：${data.status}`;
      } else if (data.advice) {
        output.textContent = data.advice;
      } else {
        output.textContent = "没有检索到相似的历史对局。";
      }
    })
    .catch((error) => {
      output.textContent = `求助失败：${error.message}`;
    })
    .finally(() => {
      ask.disabled = false;
    });
}

function setupAssistantDrag() {
  const win = el("assistant-win");
  const head = el("assistant-head");
  head.addEventListener("pointerdown", (event) => {
    if (event.target.id === "assistant-close") return;
    const rect = win.getBoundingClientRect();
    assistantDrag = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
    head.setPointerCapture(event.pointerId);
  });
  head.addEventListener("pointermove", (event) => {
    if (!assistantDrag) return;
    const width = win.offsetWidth;
    const height = win.offsetHeight;
    const left = Math.min(
      Math.max(0, event.clientX - assistantDrag.offsetX),
      window.innerWidth - width,
    );
    const top = Math.min(
      Math.max(0, event.clientY - assistantDrag.offsetY),
      window.innerHeight - height,
    );
    // 拖动后就脱离默认的 right/bottom 定位，改用 left/top
    win.style.left = `${left}px`;
    win.style.top = `${top}px`;
    win.style.right = "auto";
    win.style.bottom = "auto";
  });
  head.addEventListener("pointerup", () => {
    assistantDrag = null;
  });
}

// ------------------------------------------------------------------ 轮询

function poll() {
  if (polling) return;
  polling = true;
  pollCount += 1;
  const refreshList = pollCount % LIST_REFRESH_POLLS === 0;
  // 用 /api/game/live 判断有没有在跑的对局：历史/中断的对局不算
  api(`${API}/live`)
    .then((health) => {
      if (followLatest && health.latest && health.latest !== gameId) {
        gameId = health.latest;
        location.hash = gameId;
      }
      return gameId ? fetchSnapshot(gameId).then(render) : null;
    })
    .then(() => (refreshList ? loadGames() : null))
    .catch(() => {})
    .finally(() => {
      polling = false;
    });
}

function applyTheme(dark) {
  document.body.classList.toggle("dark", dark);
  el("theme").textContent = dark ? "浅色" : "深色";
  localStorage.setItem(THEME_KEY, dark ? "dark" : "light");
}

let toastTimer = 0;
function toast(text) {
  let box = document.getElementById("toast");
  if (!box) {
    box = document.createElement("div");
    box.id = "toast";
    document.body.append(box);
  }
  box.textContent = text;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    box.hidden = true;
  }, 3000);
}

// 导出这一局的完整数据：身份、私聊、法官台账全包含，可导入聊天页让机器人复盘
function exportGame() {
  if (!gameId) {
    toast("还没有对局，先开一局再导出");
    return;
  }
  api(`${API}/games/${gameId}/export`)
    .then((data) => {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `werewolf-game-${gameId}.json`;
      link.click();
      URL.revokeObjectURL(url);
      toast("已导出对局数据");
    })
    .catch((error) => toast(`导出失败：${error.message}`));
}

function boot() {
  applyTheme(localStorage.getItem(THEME_KEY) === "dark");
  applySidebar(localStorage.getItem(SIDEBAR_KEY) === "1");
  el("sidebar-toggle").addEventListener("click", () =>
    applySidebar(!document.body.classList.contains("sidebar-collapsed")),
  );
  el("theme").addEventListener("click", () =>
    applyTheme(!document.body.classList.contains("dark")),
  );
  el("new-game").addEventListener("click", openRoom);
  el("room-cancel").addEventListener("click", () => {
    el("room").hidden = true;
  });
  el("room-start").addEventListener("click", startGame);
  el("room-board").addEventListener("change", () => {
    renderRoomSeats();
    updateRoomHint();
  });
  el("room-fill").addEventListener("click", () => {
    const value = el("room-all").value;
    for (const select of el("room-seats").querySelectorAll("select")) select.value = value;
  });
  // 改「全部用」下拉时自动同步到每个座位，不用再手动点「全部用下面这套」。
  // 选「新增配置」交给 profileOptions 处理，这里不干预。
  el("room-all").addEventListener("change", () => {
    const value = el("room-all").value;
    if (value === "__new__") return;
    for (const select of el("room-seats").querySelectorAll("select")) select.value = value;
  });
  el("room-add-model").addEventListener("click", () => {
    el("profile-hint").textContent = "";
    el("profile-form").hidden = false;
  });
  el("profile-cancel").addEventListener("click", () => {
    el("profile-form").hidden = true;
  });
  el("profile-save").addEventListener("click", () => {
    post(`${API}/models`, {
      name: el("profile-name").value,
      api_key: el("profile-key").value,
      base_url: el("profile-url").value,
      model: el("profile-model").value,
    })
      .then((data) => {
        el("profile-form").hidden = true;
        el("profile-name").value = "";
        el("profile-key").value = "";
        el("profile-url").value = "";
        el("profile-model").value = "";
        profiles = data.profiles || [];
        profileOptions(el("room-all"), data.active);
        renderRoomSeats();
      })
      .catch((error) => {
        el("profile-hint").textContent = `保存失败：${error.message}`;
      });
  });
  el("pause").addEventListener("click", togglePause);
  el("go-home").addEventListener("click", () => (location.href = "/"));
  el("export-game").addEventListener("click", exportGame);
  el("speed").addEventListener("click", cycleSpeed);
  // 助手元素在旧版缓存 HTML 里不存在：缺了就跳过绑定，别让 boot 整条崩掉
  if (el("assistant-toggle")) {
    el("assistant-toggle").addEventListener("click", openAssistant);
    el("assistant-close").addEventListener("click", () => {
      el("assistant-win").hidden = true;
    });
    setupAssistantDrag();
  }
  el("god-view").addEventListener("change", () => {
    // 切视角要重新取一次快照：身份是服务端按 god 决定给不给的
    if (gameId) fetchSnapshot(gameId).then(render).catch(() => {});
  });
  el("only-public").addEventListener("change", () => snapshot && render(snapshot));
  el("game-list").addEventListener("click", onGameListClick);
  el("game-list").addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onGameListClick(event);
    }
  });

  loadBoards()
    .then(loadModels)
    .then(loadGames)
    .then(() => api(`${API}/live`))
    .then((health) => {
      const fromHash = location.hash.replace(/^#/, "");
      gameId = /^[0-9a-f]{6,}$/.test(fromHash) ? fromHash : health.latest || "";
      if (gameId) {
        followLatest = false;
        return fetchSnapshot(gameId).then(render);
      }
      openRoom();
      return null;
    })
    .catch(() => openRoom());
  setInterval(poll, 1000);
}

boot();
