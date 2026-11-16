/* Public Tims Hockey Challenge page.
   Reads static JSON only (data/today.json, data/season.json, data/days/...).
   data/seasons.json lists seasons. The page picks one by id and loads that
   row's base path. A season id in the query is used only when it is in the
   manifest. The base path never comes from the query. ?data= still names a
   single folder ([A-Za-z0-9_-]) when the manifest is missing.
   A method is {id, label, kind} on the payload. kind "probability"
   reads player.probability[id] (0 to 1). kind "rank" reads
   player.rank[id] (1 is the top) and player.style for the public-stat
   line. The selector, the bars, and the compare table follow the JSON.
   A player tile opens that player's inputs for the day. Missing inputs
   say "not recorded". There is no second source and nothing here submits a pick. */
(function () {
  var params = new URLSearchParams(location.search);
  var fallbackRoot = (params.get("data") || "data").replace(/[^a-zA-Z0-9_-]/g, "");
  if (!fallbackRoot) fallbackRoot = "data";
  var root = fallbackRoot;
  var loadToken = 0;

  var BACKTEST_NOTE = "Backtest: replayed on the 2025-26 regular season using each morning's lists. The logistic model here was trained on 2024-25 only. The scoring-rate estimate uses today's parameters. Graded on non-shootout NHL goals.";

  var state = {
    view: "today",
    method: "model",
    today: null,
    season: null,
    index: null,
    past: null,
    pastDate: null,
    seasons: null,
    seasonId: null,
    backtest: false,
    allSeasons: false,
    mix: null,
    evalMode: "morning",
    phaseFilter: "combined",
    dayCache: {},
    dayLoads: {},
    catalog: [],
    summaryDoc: null
  };
  var lastPlayerButton = null;

  var views = ["today", "past", "season"];

  function h(tag, props) {
    var node = document.createElement(tag);
    var kids = Array.prototype.slice.call(arguments, 2);
    if (props) {
      Object.keys(props).forEach(function (key) {
        var value = props[key];
        if (value == null || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key.slice(0, 2) === "on" && typeof value === "function") {
          node.addEventListener(key.slice(2).toLowerCase(), value);
        } else node.setAttribute(key, value);
      });
    }
    kids.forEach(function (kid) { appendChild(node, kid); });
    return node;
  }

  function appendChild(node, kid) {
    if (kid == null || kid === false) return;
    if (Object.prototype.toString.call(kid) === "[object Array]") {
      kid.forEach(function (item) { appendChild(node, item); });
      return;
    }
    if (typeof kid === "string" || typeof kid === "number") {
      node.appendChild(document.createTextNode(String(kid)));
      return;
    }
    node.appendChild(kid);
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function load(name) {
    return fetch(root + "/" + name, {cache: "no-store"}).then(function (res) {
      if (!res.ok) throw new Error("Missing " + name);
      return res.json();
    });
  }

  // Manifest bases are data/ or data/seasons/<id>/. Anything else is ignored.
  function baseForSeason(row) {
    var id = String(row && row.id || "");
    if (!/^[0-9]{4}-[0-9]{2}$/.test(id)) return "";
    var base = String(row.base || "").replace(/\/+$/, "");
    if (base === "data") return "data";
    if (base === "data/seasons/" + id) return base;
    return "";
  }

  function seasonIdFromQuery() {
    var raw = params.get("season") || "";
    if (raw === "all") return "all";
    if (!/^[0-9]{4}-[0-9]{2}$/.test(raw)) return "";
    return raw;
  }

  function seasonById(seasons, id) {
    if (!id) return null;
    for (var i = 0; i < seasons.length; i++) {
      if (seasons[i].id === id) return seasons[i];
    }
    return null;
  }

  function defaultSeason(seasons) {
    var i;
    for (i = 0; i < seasons.length; i++) {
      if (!seasons[i].backtest && seasons[i].base === "data") return seasons[i];
    }
    for (i = 0; i < seasons.length; i++) {
      if (!seasons[i].backtest) return seasons[i];
    }
    return seasons[0];
  }

  function loadManifest() {
    return fetch("data/seasons.json", {cache: "no-store"}).then(function (res) {
      if (!res.ok) throw new Error("no manifest");
      return res.json();
    }).then(function (doc) {
      var seasons = [];
      (doc || []).forEach(function (row) {
        if (!row) return;
        var base = baseForSeason(row);
        if (!base) return;
        seasons.push({
          id: String(row.id),
          label: row.label ? String(row.label) : String(row.id),
          base: base,
          backtest: !!row.backtest
        });
      });
      if (!seasons.length) throw new Error("empty manifest");
      return seasons;
    });
  }

  function writeSeasonQuery(id) {
    var url = new URL(location.href);
    if (id) url.searchParams.set("season", id);
    else url.searchParams.delete("season");
    var next = url.pathname + url.search + url.hash;
    if (next !== location.pathname + location.search + location.hash) {
      history.replaceState(null, "", next);
    }
  }

  function noteTexts() {
    var seen = {};
    var out = [];
    function add(doc) {
      var notes = doc && doc.notes;
      if (!notes || !notes.length) return;
      notes.forEach(function (note) {
        if (typeof note !== "string") return;
        var text = note.replace(/^\s+|\s+$/g, "");
        if (!text || seen[text]) return;
        seen[text] = true;
        out.push(text);
      });
    }
    add(state.season);
    add(state.index);
    return out;
  }

  function renderSeasonNote() {
    var note = document.getElementById("season-note");
    if (!note) return;
    clear(note);
    if (!state.backtest) {
      note.hidden = true;
      return;
    }
    var notes = noteTexts();
    if (!notes.length) notes = [BACKTEST_NOTE];
    notes.forEach(function (text) {
      note.appendChild(h("p", {text: text}));
    });
    note.hidden = false;
  }

  function updateChrome() {
    var todayBtn = document.querySelector('[data-view="today"]');
    if (todayBtn) todayBtn.hidden = !!state.backtest;
    var label = document.getElementById("season-label");
    if (label) label.hidden = !(state.seasons && state.seasons.length > 1);
    renderSeasonNote();
  }

  function fillSeasonSelect() {
    var sel = document.getElementById("season");
    if (!sel) return;
    clear(sel);
    (state.seasons || []).forEach(function (season) {
      var opt = document.createElement("option");
      opt.value = season.id;
      opt.textContent = season.label;
      sel.appendChild(opt);
    });
    if (state.seasons && state.seasons.length) {
      var all = document.createElement("option");
      all.value = "all";
      all.textContent = "All seasons";
      sel.appendChild(all);
    }
    if (state.seasonId) sel.value = state.seasonId;
  }

  function isAvailable(player) {
    if (!player) return false;
    if (player.available === false) return false;
    var start = player.start ? new Date(player.start).getTime() : NaN;
    if (!isNaN(start) && Date.now() >= start) return false;
    return true;
  }

  function gameStartedFirst(player, now) {
    var start = player && player.start ? new Date(player.start).getTime() : NaN;
    if (isNaN(start)) return false;
    if (player.unavailable_reason === "removed") return false;
    var removed = player.removed_at ? new Date(player.removed_at).getTime() : NaN;
    if (!isNaN(removed) && removed < start) return false;
    var clock = now == null ? Date.now() : now;
    if (player.unavailable_reason === "game_started" || player.game_started) return true;
    return player.available === false || clock >= start;
  }

  function torontoGameTime(iso) {
    if (!iso) return "";
    var date = new Date(iso);
    if (isNaN(date.getTime())) return "";
    try {
      var text = new Intl.DateTimeFormat("en-US", {
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
        timeZone: "America/Toronto"
      }).format(date);
      return String(text).replace(/[\u00a0\u202f]/g, " ").replace(/\s+/g, " ").replace(/^\s+|\s+$/g, "");
    } catch (err) {
      return "";
    }
  }

  function startIso(source, group, day) {
    if (!source) return "";
    if (source.start || source.startTimeUTC) return source.start || source.startTimeUTC;
    var pid = source.pid != null ? source.pid : (source.pids && source.pids.length ? source.pids[0] : null);
    var player = null;
    if (pid != null && group && group.players) {
      var i;
      for (i = 0; i < group.players.length; i++) {
        if (group.players[i].pid === pid) {
          player = group.players[i];
          break;
        }
      }
    }
    if (player && (player.start || player.startTimeUTC)) return player.start || player.startTimeUTC;
    var team = source.team || (player && player.team) || "";
    var games = day && day.games;
    var value = team && games ? games[team] : "";
    if (typeof value === "string") return value;
    if (value && typeof value === "object") return value.start || value.startTimeUTC || "";
    return "";
  }

  function teamsAndTime(source, group, day) {
    if (!source || !source.team || !source.opp) return "";
    var where = source.home ? "vs" : "@";
    var line = source.team + " " + where + " " + source.opp;
    var time = torontoGameTime(startIso(source, group, day));
    if (time) line += " \u00b7 " + time;
    return line;
  }

  function torontoClock(iso) {
    if (!iso) return "";
    var date = new Date(iso);
    if (isNaN(date.getTime())) return "";
    try {
      var text = new Intl.DateTimeFormat("en-CA", {
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
        timeZone: "America/Toronto"
      }).format(date);
      var match = String(text).match(/(\d{2}):(\d{2})/);
      return match ? match[1] + ":" + match[2] : "";
    } catch (err) {
      return "";
    }
  }

  function removedNote(player) {
    if (!player || isAvailable(player)) return "";
    if (gameStartedFirst(player)) {
      var started = torontoClock(player.start || player.game_started_at);
      return started ? "Game started " + started : "Game started";
    }
    var when = torontoClock(player.removed_at || player.last_seen);
    if (!when) return "Removed from the Tims list";
    return "Removed from the Tims list at " + when;
  }

  function morningGroup(day, groupId) {
    var groups = day && day.morning && day.morning.groups;
    if (!groups) return null;
    for (var i = 0; i < groups.length; i++) {
      if (groups[i].id === groupId) return groups[i];
    }
    return null;
  }

  function morningPick(day, groupId, methodId) {
    var block = morningGroup(day, groupId);
    if (!block) return null;
    var picks = block.method_picks || {};
    if (picks[methodId]) return picks[methodId];
    if (methodId === "model") return block.pick || null;
    return null;
  }

  function samePick(a, b) {
    function nums(block) {
      return ((block && block.pids) || []).map(Number).sort(function (x, y) { return x - y; });
    }
    var left = nums(a);
    var right = nums(b);
    if (left.length !== right.length || !left.length) return false;
    for (var i = 0; i < left.length; i++) {
      if (left[i] !== right[i]) return false;
    }
    return true;
  }

  function morningDiffers(day) {
    var methods = displayMethods(day);
    var found = false;
    (day.groups || []).forEach(function (group) {
      methods.forEach(function (method) {
        var earlier = morningPick(day, group.id, method.id);
        if (earlier && earlier.name && !samePick(pickOf(group, method.id), earlier)) found = true;
      });
    });
    return found;
  }

  function pickTint(id) {
    var n = Number(id);
    if (n === 1 || n === 2 || n === 3) return "g" + n;
    return "";
  }

  function groupChangeLines(snapshots) {
    var lines = [];
    (snapshots || []).forEach(function (snap) {
      [
        ["Added", snap.added],
        ["Removed", snap.removed],
        ["Game started", snap.started]
      ].forEach(function (pair) {
        var buckets = {};
        var order = [];
        (pair[1] || []).forEach(function (entry) {
          if (!entry) return;
          var gid = entry.group == null ? "" : String(entry.group);
          if (!buckets[gid]) {
            buckets[gid] = [];
            order.push(gid);
          }
          buckets[gid].push(entry.name || ("#" + entry.pid));
        });
        order.forEach(function (gid) {
          lines.push({time: snap.time || "", kind: pair[0], group: gid, names: buckets[gid]});
        });
      });
    });
    return lines;
  }

  function changeLineText(line, when) {
    var who = "Group " + (line.group || "?") + ": " + (line.names || []).join(", ");
    var bits = [];
    if (when) bits.push(when);
    bits.push(line.kind);
    bits.push(who);
    return bits.join(" \u00b7 ");
  }

  function renderListChanges(day) {
    var lines = groupChangeLines(day && day.snapshots);
    if (!lines.length) return null;
    var items = lines.map(function (line) {
      var when = torontoClock(line.time) || "";
      return h("li", {class: pickTint(line.group), text: changeLineText(line, when)});
    });
    var list = h("ul", {class: "list-changes"}, items);
    var body = lines.length > 6
      ? h("details", {class: "list-changes-fold"},
          h("summary", {text: "Show changes (" + lines.length + ")"}),
          list)
      : list;
    return h("section", {class: "card", id: "list-changes"},
      h("h2", {text: "List changes"}),
      h("p", {class: "muted small", text: "Anyone off the list is grayed out and cannot be picked. A scratch before the game says when Tims removed them. A game start says when that game began. The graded pick is the one whose game started while they were still the pick."}),
      body
    );
  }

  function renderMorningBanner(day) {
    if (!morningDiffers(day)) return null;
    var note = (day.morning && day.morning.note) || "Reference only. Season results use the current pick.";
    return h("p", {class: "muted small morning-banner", text: "Morning picks stay listed for reference. " + note});
  }

  function skippedNames(day) {
    var out = [];
    ((day && day.skipped) || []).forEach(function (entry) {
      var name = "";
      if (typeof entry === "string") name = entry;
      else if (entry && typeof entry === "object") name = entry.name || entry.fullName || "";
      name = String(name || "").replace(/^\s+|\s+$/g, "");
      if (name) out.push(name);
    });
    return out;
  }

  function renderSkipped(day) {
    var names = skippedNames(day);
    if (!names.length) return null;
    return h("p", {class: "muted small skipped", text: "Skipped: " + names.join(", ")});
  }

  function pretty(iso) {
    if (!iso) return "";
    var p = iso.split("-");
    var d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
    return d.toLocaleDateString("en-US", {
      weekday: "short", month: "short", day: "numeric", timeZone: "UTC"
    });
  }

  function pct(v) {
    if (v == null || isNaN(v)) return "\u2014";
    return (v * 100).toFixed(1) + "%";
  }

  function methodsOf(doc) {
    var list = doc && doc.methods && doc.methods.length ? doc.methods.slice() : [];
    if (!list.some(function (m) { return m.id === "model"; })) {
      list.unshift({
        id: "model",
        label: "Logistic model (player form + matchup)",
        kind: "probability"
      });
    }
    return list;
  }

  function knownMethods() {
    if (state.season && state.season.methods && state.season.methods.length) {
      return methodsOf(state.season);
    }
    return methodsOf(state.today || {methods: []});
  }

  function displayMethods(doc) {
    var byId = {};
    knownMethods().forEach(function (method) { byId[method.id] = method; });
    return methodsOf(doc).map(function (method) { return byId[method.id] || method; });
  }

  function pOf(player, method) {
    if (!player || !player.probability) return null;
    var v = player.probability[method];
    return typeof v === "number" ? v : null;
  }

  function methodMeta(doc) {
    var rules = mixApi();
    if (state.method === "custom" && rules) return rules.CUSTOM;
    var list = methodsOf(doc || state.today || state.season || {});
    var known = knownMethods();
    var pool = known.concat(list);
    for (var i = 0; i < pool.length; i++) {
      if (pool[i].id === state.method) return pool[i];
    }
    return list[0] || {id: "model", label: "Model", kind: "probability"};
  }

  function kindOf(method) {
    return method && method.kind === "rank" ? "rank" : "probability";
  }

  function rankOf(player, methodId) {
    if (!player || !player.rank) return null;
    var v = player.rank[methodId];
    return typeof v === "number" ? v : null;
  }

  function gpgOf(player) {
    var style = player && player.style;
    if (!style || typeof style.goals_per_game !== "number") return null;
    return style.goals_per_game;
  }

  function currentDayFor(group) {
    if (state.renderDay && (state.renderDay.groups || []).indexOf(group) !== -1) return state.renderDay;
    if (state.past && (state.past.groups || []).indexOf(group) !== -1) return state.past;
    return state.today || {date: "", status: "pending", groups: []};
  }

  function pickOf(group, methodId) {
    var rules = mixApi();
    var day = currentDayFor(group);
    if (rules && (state.evalMode === "full_day" || methodId === "custom")) {
      var pending = !group || group.status === "pending" || group.hit == null && day.status === "pending";
      if (methodId === "custom") {
        return rules.customPick(day, group, state.mix, knownMethods(), state.evalMode, pending, Date.now());
      }
      var view = rules.viewOf(day, group, state.evalMode);
      var block = view.method_picks && view.method_picks[methodId];
      if (block) return block;
      if (methodId === "model") return view.pick || null;
      return null;
    }
    var stored = group.method_picks && group.method_picks[methodId];
    if (stored) return stored;
    if (methodId === "model") return group.pick || null;
    return null;
  }

  function hitOf(group, methodId) {
    var rules = mixApi();
    if (rules && (methodId === "custom" || state.evalMode === "full_day")) {
      var day = currentDayFor(group);
      var pending = !group || group.status === "pending" || (group.hit == null && day.status === "pending");
      return rules.groupHit(day, group, methodId, state.mix, knownMethods(), state.evalMode, pending, Date.now());
    }
    if (methodId === "model") return group.hit;
    var block = group.method_picks && group.method_picks[methodId];
    return block ? block.hit : null;
  }

  function isStoredPick(player, group, methodId) {
    var block = pickOf(group, methodId);
    if (block && block.pids && block.pids.length) {
      return block.pids.indexOf(player.pid) !== -1;
    }
    return methodId === "model" && !!player.pick;
  }

  function ordered(players, method, kind) {
    return (players || []).slice().sort(function (a, b) {
      if (kind === "rank") {
        var ra = rankOf(a, method);
        var rb = rankOf(b, method);
        if (ra == null && rb == null) return a.name < b.name ? -1 : 1;
        if (ra == null) return 1;
        if (rb == null) return -1;
        if (ra !== rb) return ra - rb;
        return a.pid - b.pid;
      }
      var pa = pOf(a, method);
      var pb = pOf(b, method);
      if (pa == null && pb == null) return a.name < b.name ? -1 : 1;
      if (pa == null) return 1;
      if (pb == null) return -1;
      if (pb !== pa) return pb - pa;
      return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
    });
  }

  function bestOf(players, method, kind) {
    var best = null;
    (players || []).forEach(function (p) {
      if (!isAvailable(p)) return;
      var v = kind === "rank" ? rankOf(p, method) : pOf(p, method);
      if (v == null) return;
      if (best == null || (kind === "rank" ? v < best : v > best)) best = v;
    });
    return best;
  }

  function pickLockedNow(group, method) {
    var block = pickOf(group, method);
    if (!block || !(block.pids || []).length) return false;
    if (block.locked) return true;
    var players = group && group.players || [];
    return block.pids.every(function (pid) {
      var found = null;
      players.forEach(function (player) {
        if (player.pid === pid) found = player;
      });
      return found && gameStartedFirst(found);
    });
  }

  function highlighted(player, players, method, mode, kind, group) {
    if (method === "custom") {
      var block = pickOf(group, "custom");
      return !!(block && block.pids && block.pids.indexOf(player.pid) !== -1);
    }
    if (pickLockedNow(group, method)) return isStoredPick(player, group, method);
    if (!isAvailable(player)) return false;
    if (mode === "past") return isStoredPick(player, group, method);
    var best = bestOf(players, method, kind);
    var v = kind === "rank" ? rankOf(player, method) : pOf(player, method);
    if (best == null) return isStoredPick(player, group, method);
    return v === best;
  }

  function formatMethodValue(player, method) {
    if (kindOf(method) === "rank") {
      var rank = rankOf(player, method.id);
      var gpg = gpgOf(player);
      if (rank == null) return "\u2014";
      if (gpg == null) return "#" + rank;
      return "#" + rank + " \u00b7 " + gpg.toFixed(2);
    }
    return pct(pOf(player, method.id));
  }

  function formatBlock(block, method) {
    if (!block) return "\u2014";
    if (block.valueText) return block.valueText;
    if (kindOf(method) === "rank") {
      if (typeof block.goals_per_game === "number") {
        return "#" + (block.rank || 1) + " \u00b7 " + block.goals_per_game.toFixed(2);
      }
      if (block.rank != null) return "#" + block.rank;
      return "\u2014";
    }
    return pct(block.probability);
  }

  function barValue(player, players, method) {
    if (kindOf(method) !== "rank") return pOf(player, method.id);
    var gpg = gpgOf(player);
    if (gpg == null || gpg <= 0) return 0;
    var max = 0;
    (players || []).forEach(function (other) {
      var value = gpgOf(other);
      if (value != null && value > max) max = value;
    });
    if (max <= 0) return 0;
    return 0.45 * (gpg / max);
  }

  function styleLine(player) {
    var stats = player.style;
    if (!stats) return "";
    var bits = [];
    if (stats.gp != null) bits.push(stats.gp + " GP");
    if (stats.goals != null) bits.push(stats.goals + " G");
    if (typeof stats.goals_per_game === "number") bits.push(stats.goals_per_game.toFixed(2) + " G/GP");
    if (stats.shots != null) bits.push(stats.shots + " SOG");
    if (typeof stats.shooting_pct === "number") bits.push(stats.shooting_pct.toFixed(1) + " S%");
    if (typeof stats.toi_per_game === "number") bits.push(stats.toi_per_game.toFixed(2) + " TOI");
    if (typeof stats.pp_toi_per_game === "number") bits.push(stats.pp_toi_per_game.toFixed(2) + " PP");
    if (typeof stats.opp_ga_per_game === "number") bits.push("opp " + stats.opp_ga_per_game.toFixed(2));
    return bits.join(" \u00b7 ");
  }

  function matchup(player, day) {
    var line = teamsAndTime(player, null, day);
    if (!line) return "";
    var tag = player.home ? "Home" : "Away";
    return line + " \u00b7 " + tag;
  }

  function hitText(hit, status) {
    if (hit == null) return status === "graded" ? "not graded" : "Pending";
    if (hit >= 0.999) return "Hit";
    if (hit <= 0.001) return "Miss";
    return Math.round(hit * 100) + "% of tie";
  }

  function hitClass(hit) {
    if (hit == null) return "pending";
    if (hit >= 0.999) return "hit";
    if (hit <= 0.001) return "miss";
    return "hit";
  }

  function scoredText(player) {
    if (!player.scored) return "";
    if (player.goals > 1) return player.goals + " goals";
    return "Scored";
  }

  function barWidth(v) {
    if (v == null || isNaN(v) || v <= 0) return "0%";
    return Math.min(100, (v / 0.45) * 100).toFixed(1) + "%";
  }

  function setBanner(text) {
    var banner = document.getElementById("banner");
    if (!text) {
      banner.hidden = true;
      banner.textContent = "";
      return;
    }
    banner.hidden = false;
    banner.textContent = text;
  }

  function mixApi() {
    return window.HockeyMix;
  }

  function trackMethods(doc) {
    var methods = displayMethods(doc);
    var rules = mixApi();
    if (rules && !methods.some(function (method) { return method.id === "custom"; })) {
      methods.push(rules.CUSTOM);
    }
    return methods;
  }

  function fillMethodSelect() {
    var sel = document.getElementById("method");
    var methods = trackMethods(state.today || state.season || {});
    clear(sel);
    methods.forEach(function (method) {
      var opt = document.createElement("option");
      opt.value = method.id;
      opt.textContent = method.label;
      sel.appendChild(opt);
    });
    if (methods.length < 2) {
      var slot = document.createElement("option");
      slot.disabled = true;
      slot.value = "";
      slot.textContent = "More methods later";
      sel.appendChild(slot);
    }
    if (state.method !== "custom" && !methods.some(function (m) { return m.id === state.method; })) {
      state.method = "model";
    }
    sel.value = state.method === "custom" || methods.some(function (m) { return m.id === state.method; })
      ? state.method
      : "model";
  }

  function statusLine(day) {
    if (!day) return "";
    if (day.status === "graded") return "Final";
    if (day.status === "partial") return "Some games still going";
    return "Games not final yet. Results land after the slate is done.";
  }

  function renderSummary(day, mode) {
    var wrap = h("div", {class: "summary"});
    var methods = trackMethods(day);
    var selected = methodMeta(day);
    var multi = methods.length > 1;
    (day.groups || []).forEach(function (group) {
      var pick = pickOf(group, selected.id) || {};
      var hit = hitOf(group, selected.id);
      var bits = [
        h("div", {class: "ghead"},
          h("h3", {text: "Group " + group.id}),
          mode === "past" || day.status !== "pending"
            ? h("span", {class: "pill " + hitClass(hit), text: hitText(hit, group.status || day.status)})
            : null)
      ];
      if (!multi) {
        bits.push(h("div", {class: "who", text: pick.name || "No pick"}));
        bits.push(h("div", {class: "muted small", text: teamsAndTime(pick, group, day)}));
        bits.push(h("div", {class: "pct", text: pct(pick.probability)}));
      } else {
        bits.push(h("div", {class: "leaders"}, methods.map(function (method) {
          var block = pickOf(group, method.id);
          var who = block && block.name ? block.name : "\u2014";
          var game = teamsAndTime(block, group, day);
          if (block && block.name && game) who += " \u00b7 " + game;
          return h("div", {class: method.id === selected.id ? "on" : ""},
            h("span", {class: "lab", text: method.label}),
            h("span", {class: "who", text: who}),
            h("span", {class: "pct", text: formatBlock(block, method)})
          );
        })));
      }
      trackMethods(day).forEach(function (method) {
        var earlier = morningPick(day, group.id, method.id);
        if (!earlier || !earlier.name || samePick(pickOf(group, method.id), earlier)) return;
        var text = "Morning pick \u00b7 " + method.label + ": " + earlier.name;
        var morningGame = teamsAndTime(earlier, group, day);
        if (morningGame) text += " \u00b7 " + morningGame;
        if (earlier.hit != null) text += " \u00b7 " + hitText(earlier.hit);
        bits.push(h("p", {class: "pickline morning-pick", text: text}));
      });
      wrap.appendChild(h("article", {class: "card"}, bits));
    });
    return wrap;
  }

  function positionLabel(code) {
    var text = String(code == null ? "" : code).trim().toUpperCase();
    if (text === "L" || text === "LW") return "LW";
    if (text === "R" || text === "RW") return "RW";
    if (text === "LD" || text === "RD" || text === "D") return "D";
    if (text === "C" || text === "G" || text === "F") return text;
    return text;
  }

  function formatInput(value) {
    if (typeof value !== "number" || !isFinite(value)) return "not recorded";
    var rounded = Math.round(value * 10000) / 10000;
    if (Math.abs(rounded - Math.round(rounded)) < 1e-9) return String(Math.round(rounded));
    return String(rounded);
  }

  function slateRows(player) {
    player = player || {};
    var style = player.style || {};
    var estimate = (player.inputs && player.inputs.estimate) || {};
    var lines = (player.inputs && player.inputs.lines) || {};

    function count(styleKey, estimateKey) {
      if (typeof style[styleKey] === "number") return String(style[styleKey]);
      if (typeof estimate[estimateKey] === "number") return formatInput(estimate[estimateKey]);
      return "not recorded";
    }
    function shotsPer() {
      if (typeof style.shots_per_game === "number") return style.shots_per_game.toFixed(2);
      if (typeof estimate.cur_sog === "number" && typeof estimate.cur_gp === "number" && estimate.cur_gp > 0) {
        return (estimate.cur_sog / estimate.cur_gp).toFixed(2);
      }
      return "not recorded";
    }
    function shootPct() {
      if (typeof style.shooting_pct === "number") return style.shooting_pct.toFixed(1) + "%";
      if (typeof estimate.cur_g === "number" && typeof estimate.cur_sog === "number" && estimate.cur_sog > 0) {
        return (100 * estimate.cur_g / estimate.cur_sog).toFixed(1) + "%";
      }
      return "not recorded";
    }
    function toi(styleKey, estimateKey) {
      if (typeof style[styleKey] === "number") return style[styleKey].toFixed(2);
      if (typeof estimate[estimateKey] === "number" && typeof estimate.cur_gp === "number" && estimate.cur_gp > 0) {
        return (estimate[estimateKey] / estimate.cur_gp).toFixed(2);
      }
      return "not recorded";
    }
    function gpg() {
      if (typeof style.goals_per_game === "number") return style.goals_per_game.toFixed(2);
      if (typeof estimate.cur_g === "number" && typeof estimate.cur_gp === "number" && estimate.cur_gp > 0) {
        return (estimate.cur_g / estimate.cur_gp).toFixed(2);
      }
      return "not recorded";
    }
    function gaa() {
      if (typeof style.opp_ga_per_game === "number") return style.opp_ga_per_game.toFixed(2);
      if (typeof estimate.opp_ga_pg === "number") return formatInput(estimate.opp_ga_pg);
      return "not recorded";
    }
    function homeAway() {
      if (style.home_away === "HOME") return "Home";
      if (style.home_away === "AWAY") return "Away";
      var home = player.home;
      if (home == null && typeof estimate.home === "number") home = estimate.home;
      if (home === 1 || home === "1") return "Home";
      if (home === 0 || home === "0") return "Away";
      return "not recorded";
    }
    function line(key) {
      var value = lines[key];
      if (typeof value === "string" && value) return value;
      return "not recorded";
    }
    var pos = positionLabel(player.position);
    return [
      {label: "Pos", value: pos || "not recorded"},
      {label: "GP", value: count("gp", "cur_gp")},
      {label: "G", value: count("goals", "cur_g")},
      {label: "Shots/GP", value: shotsPer()},
      {label: "Shoot%", value: shootPct()},
      {label: "PP TOI/GP", value: toi("pp_toi_per_game", "cur_pptoi")},
      {label: "TOI/GP", value: toi("toi_per_game", "cur_toi")},
      {label: "Goals/GP", value: gpg()},
      {label: "EV line", value: line("ev")},
      {label: "PP line", value: line("pp")},
      {label: "Home/Away", value: homeAway()},
      {label: "Opponent GAA", value: gaa()}
    ];
  }

  function slateNote(rows) {
    var ev = "";
    var pp = "";
    (rows || []).forEach(function (row) {
      if (row.label === "EV line") ev = row.value;
      if (row.label === "PP line") pp = row.value;
    });
    if (ev === "not recorded" && pp === "not recorded") {
      return "Even-strength line and power-play line are not inputs to these calculations and are not recorded.";
    }
    return "";
  }

  function detailMethods(day) {
    var methods = day && day.methods;
    if (methods && methods.length) return methods;
    return [
      {id: "model", label: "Logistic model (player form + matchup)", kind: "probability"},
      {id: "estimate", label: "Scoring-rate estimate", kind: "probability"},
      {id: "goals", label: "Goals per game", kind: "rank"}
    ];
  }

  function inputSections(player, methods) {
    player = player || {};
    var inputs = player.inputs || {};
    var model = inputs.model || null;
    var estimate = inputs.estimate || null;
    var slate = slateRows(player);
    methods = methods && methods.length ? methods : detailMethods(null);

    function fromSlate(label) {
      for (var i = 0; i < slate.length; i++) {
        if (slate[i].label === label) return slate[i].value;
      }
      return "not recorded";
    }
    function raw(source, key) {
      if (!source || typeof source[key] !== "number") return "not recorded";
      return formatInput(source[key]);
    }
    function probabilityText(method) {
      var bag = player.probability || {};
      if (method.id && typeof bag[method.id] === "number") return (bag[method.id] * 100).toFixed(1) + "%";
      return "not recorded";
    }
    function modelRows() {
      var fields = [
        ["home", "Home (1) or away (0)"],
        ["is_d", "Defenseman (1) or forward (0)"],
        ["cur_gp", "Games this season"],
        ["prev_gp", "Games last season"],
        ["g60", "Shrunk goals per 60 minutes"],
        ["s60", "Shrunk shots per 60 minutes"],
        ["sh", "Shrunk shooting rate"],
        ["xg60", "Shrunk shots per 60 times shooting rate"],
        ["prior_g60", "Prior goals per 60 minutes"],
        ["prior_s60", "Prior shots per 60 minutes"],
        ["toi_hat", "Expected ice time (minutes)"],
        ["pp_hat", "Expected power-play ice time (minutes)"],
        ["l5_toi", "Ice time over the last 5 games (minutes)"],
        ["opp_ga", "Opponent goals against per game"],
        ["opp_sa", "Opponent shots against per game"],
        ["opp_sv", "Opponent save percentage"],
        ["tm_gf", "Own team goals per game"],
        ["b2b", "Back-to-back (1 if the team played yesterday)"],
        ["opp_b2b", "Opponent back-to-back"],
        ["lam_g", "Goal-rate baseline"],
        ["lam_x", "Shot-based baseline"],
        ["p_base", "Poisson baseline probability"]
      ];
      var logs = [
        ["log_g60", "Log of shrunk goals per 60"],
        ["log_s60", "Log of shrunk shots per 60"],
        ["log_sh", "Log of shrunk shooting rate"],
        ["log_xg60", "Log of shrunk shots per 60 times shooting rate"],
        ["log_prior_g60", "Log of prior goals per 60"],
        ["log_prior_s60", "Log of prior shots per 60"],
        ["log_lam_g", "Log of the goal-rate baseline"],
        ["log_lam_x", "Log of the shot-based baseline"],
        ["log_p_base", "Log of the Poisson baseline"],
        ["log1p_cur_gp", "Log1p of games this season (used instead of the raw count)"],
        ["log1p_prev_gp", "Log1p of games last season (used instead of the raw count)"]
      ];
      var rows = fields.map(function (pair) {
        return {group: "Player and matchup", label: pair[1], value: raw(model, pair[0])};
      });
      logs.forEach(function (pair) {
        rows.push({group: "Log transform", label: pair[1], value: raw(model, pair[0])});
      });
      return rows;
    }
    function estimateRows() {
      var seasons = [
        ["cur", "This season"],
        ["prev", "Last season"],
        ["prev2", "Two seasons ago"],
        ["prev3", "Three seasons ago"]
      ];
      var fields = [
        ["gp", "Games"],
        ["g", "Goals"],
        ["sog", "Shots"],
        ["toi", "Ice time (minutes)"],
        ["pptoi", "Power-play ice time (minutes)"],
        ["ppg", "Power-play goals"]
      ];
      var rows = [];
      seasons.forEach(function (season) {
        fields.forEach(function (field) {
          rows.push({
            group: season[1],
            label: field[1],
            value: raw(estimate, season[0] + "_" + field[0])
          });
        });
      });
      [
        ["is_d", "Defenseman (1) or forward (0)"],
        ["home", "Home (1) or away (0)"],
        ["opp_ga_pg", "Opponent goals against per game"],
        ["lg_ga_pg", "League goals against per game"],
        ["rest_t", "Rest days (1 means played yesterday)"]
      ].forEach(function (pair) {
        rows.push({group: "This game", label: pair[1], value: raw(estimate, pair[0])});
      });
      rows.push({group: "Not recorded", label: "Age", value: raw(estimate, "age")});
      rows.push({group: "Not recorded", label: "Individual expected goals", value: raw(estimate, "ixg")});
      return rows;
    }
    function rankRows(method) {
      var bag = player.rank || {};
      var rank = "not recorded";
      if (method.id && typeof bag[method.id] === "number") rank = "#" + bag[method.id];
      var shots = "not recorded";
      if (player.style && typeof player.style.shots === "number") shots = String(player.style.shots);
      else if (estimate && typeof estimate.cur_sog === "number") shots = formatInput(estimate.cur_sog);
      return [
        {label: "Rank in this group", value: rank},
        {label: "Goals per game", value: fromSlate("Goals/GP")},
        {label: "Games", value: fromSlate("GP")},
        {label: "Goals", value: fromSlate("G")},
        {label: "Shots", value: shots},
        {label: "Shots per game", value: fromSlate("Shots/GP")},
        {label: "Shooting percentage", value: fromSlate("Shoot%")},
        {label: "Ice time per game", value: fromSlate("TOI/GP")},
        {label: "Power-play ice time per game", value: fromSlate("PP TOI/GP")},
        {label: "Opponent goals against per game", value: fromSlate("Opponent GAA")},
        {label: "Home or away", value: fromSlate("Home/Away")}
      ];
    }

    return methods.map(function (method) {
      if (method.kind === "rank") {
        return {
          title: method.label || "Goals per game",
          resultLabel: null,
          result: null,
          note: "This method ranks by goals per game. It does not compute a probability. Ties break toward the lower player id.",
          rows: rankRows(method)
        };
      }
      if (method.id === "model") {
        return {
          title: method.label || "Logistic model (player form + matchup)",
          resultLabel: "Probability",
          result: probabilityText(method),
          note: "These are the values the model reads. It also takes the log of the rate fields, and log1p of the game counts in place of the raw counts.",
          rows: modelRows()
        };
      }
      return {
        title: method.label || "Scoring-rate estimate",
        resultLabel: "Probability",
        result: probabilityText(method),
        note: "Age is not recorded, and the estimate uses 27 when age is missing. Individual expected goals are not recorded. The fitted blend uses goals only, so that missing total does not change this estimate. When opponent or league goals against is missing, the estimate uses 3. Shots are listed with the season totals; this estimate does not use them.",
        rows: estimateRows()
      };
    });
  }

  function renderInputSection(block) {
    var kids = [h("h3", {text: block.title})];
    if (block.note) kids.push(h("p", {class: "input-note", text: block.note}));
    if (block.resultLabel) {
      kids.push(h("p", {class: "input-result"}, block.resultLabel + ": ", h("b", {text: block.result})));
    }
    var table = h("table", {class: "input-table"});
    var body = h("tbody");
    var lastGroup = "";
    (block.rows || []).forEach(function (row) {
      if (row.group && row.group !== lastGroup) {
        lastGroup = row.group;
        body.appendChild(h("tr", null, h("th", {colspan: "2", text: row.group})));
      }
      body.appendChild(h("tr", null,
        h("td", {text: row.label}),
        h("td", {class: "value", text: row.value})
      ));
    });
    table.appendChild(body);
    kids.push(table);
    return h("section", {class: "input-section"}, kids);
  }

  function openPlayer(player, day, group, trigger) {
    var dialog = document.getElementById("player-detail");
    var title = document.getElementById("player-detail-title");
    var body = document.getElementById("player-detail-body");
    if (!dialog || !title || !body) return;
    lastPlayerButton = trigger || null;
    title.textContent = player.name || "Player";
    clear(body);
    var pos = positionLabel(player.position);
    var bits = [];
    if (group && group.id != null) bits.push("Group " + group.id);
    if (pos) bits.push(pos);
    var game = matchup(player, day);
    if (game) bits.push(game);
    if (bits.length) body.appendChild(h("p", {class: "dialog-kicker", text: bits.join(" \u00b7 ")}));
    var gone = removedNote(player);
    if (gone) body.appendChild(h("p", {class: "removed-note", text: gone}));
    statusBadges(player).forEach(function (badge) {
      body.appendChild(h("p", {class: "status-note"},
        h("span", {class: "pill " + badge.kind, text: badge.label}),
        badge.title ? " " + badge.title : ""
      ));
    });
    var slate = slateRows(player);
    body.appendChild(renderInputSection({
      title: "Inputs for this slate",
      note: slateNote(slate),
      rows: slate
    }));
    inputSections(player, detailMethods(day)).forEach(function (block) {
      body.appendChild(renderInputSection(block));
    });
    if (dialog.showModal) dialog.showModal();
    else dialog.setAttribute("open", "");
    var closeBtn = document.getElementById("player-detail-close");
    if (closeBtn) closeBtn.focus();
  }

  function bindPlayerDialog() {
    var dialog = document.getElementById("player-detail");
    var closeBtn = document.getElementById("player-detail-close");
    if (!dialog || dialog.getAttribute("data-bound")) return;
    dialog.setAttribute("data-bound", "1");
    function closePlayer() {
      if (dialog.open) dialog.close();
      else dialog.removeAttribute("open");
    }
    if (closeBtn) closeBtn.addEventListener("click", closePlayer);
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) closePlayer();
    });
    dialog.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closePlayer();
    });
    dialog.addEventListener("close", function () {
      if (lastPlayerButton && lastPlayerButton.focus) lastPlayerButton.focus();
      lastPlayerButton = null;
    });
  }

  function shortDate(iso) {
    var parts = String(iso || "").slice(0, 10).split("-");
    if (parts.length < 3) return "";
    var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    var month = months[Number(parts[1]) - 1];
    var day = Number(parts[2]);
    if (!month || !day) return "";
    return month + " " + day;
  }

  function absenceNote(absence) {
    if (!absence || typeof absence.missed_team_games !== "number") return "";
    var games = absence.missed_team_games === 1 ? "game" : "games";
    var text = "missed " + absence.missed_team_games + " " + games;
    var played = shortDate(absence.last_played);
    if (played) text += ", last played " + played;
    return text;
  }

  function injuryTitle(injury) {
    if (!injury || !injury.status) return "";
    var bits = [];
    if (injury.detail) bits.push(injury.detail);
    var when = shortDate(injury.updated);
    if (when) bits.push(when);
    return bits.join(" \u00b7 ");
  }

  function statusBadges(player) {
    var badges = [];
    var injury = player && player.injury;
    if (injury && injury.status) {
      badges.push({kind: "injury", label: String(injury.status), title: injuryTitle(injury)});
    }
    var absence = player && player.absence;
    if (absence && typeof absence.missed_team_games === "number" && absence.missed_team_games >= 3) {
      badges.push({kind: "returning", label: "Returning", title: absenceNote(absence)});
    }
    return badges;
  }

  function renderPlayer(player, players, method, mode, group, day) {
    var selected = method && method.id ? method : methodMeta(null);
    var valueText = formatMethodValue(player, selected);
    var on = highlighted(player, players, selected.id, mode, kindOf(selected), group);
    var pos = positionLabel(player.position);
    var row = h("div", {class: "row"},
      h("span", {class: "name"},
        pos ? h("span", {class: "pill pos", text: pos}) : null,
        pos ? " " : null,
        player.name,
        on ? " " : null,
        on ? h("span", {class: "pill", text: "Pick"}) : null,
        statusBadges(player).map(function (badge) {
          return [" ", h("span", {class: "pill " + badge.kind, title: badge.title || null, text: badge.label})];
        }),
        !isAvailable(player) && gameStartedFirst(player) ? " " : null,
        !isAvailable(player) && gameStartedFirst(player) ? h("span", {class: "pill started", text: "Game started"}) : null),
      h("span", {class: "pct", text: valueText})
    );
    var gone = removedNote(player);
    var meta = h("div", {class: "meta"},
      matchup(player, day),
      gone ? " \u00b7 " : "",
      gone ? h("span", {class: "removed-note", text: gone}) : null,
      scoredText(player) ? " \u00b7 " : "",
      scoredText(player) ? h("span", {class: "scored", text: scoredText(player)}) : null
    );
    var stats = kindOf(selected) === "rank" ? styleLine(player) : "";
    var aria = (player.name || "Player") + (pos ? ", " + pos : "");
    if (on) aria += ", pick";
    statusBadges(player).forEach(function (badge) {
      aria += ", " + badge.label;
      if (badge.title) aria += ", " + badge.title;
    });
    if (!isAvailable(player)) aria += ", no longer on the list";
    aria += ". Show calculation inputs.";
    return h("div", {
      class: "player" + (on ? " pick" : "") + (!isAvailable(player) ? " removed" : ""),
      role: "button",
      tabindex: "0",
      "aria-haspopup": "dialog",
      "aria-label": aria,
      onclick: function (event) { openPlayer(player, day, group, event.currentTarget); },
      onkeydown: function (event) {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        openPlayer(player, day, group, event.currentTarget);
      }
    },
      row,
      meta,
      stats ? h("div", {class: "meta stats-line", text: stats}) : null,
      h("div", {class: "bar", title: valueText}, h("i", {style: "width:" + barWidth(barValue(player, players, selected))}))
    );
  }

  function renderGroups(day, mode) {
    var grid = h("div", {class: "groups"});
    var selected = methodMeta(day);
    (day.groups || []).forEach(function (group) {
      var available = ordered((group.players || []).filter(isAvailable), selected.id, kindOf(selected));
      var removed = (group.players || []).filter(function (player) { return !isAvailable(player); });
      var hit = hitOf(group, selected.id);
      var head = h("div", {class: "ghead"},
        h("h3", {text: "Group " + group.id}),
        h("span", {class: "pill " + hitClass(hit), text: mode === "today" && day.status === "pending" ? available.length + " players" : hitText(hit, group.status || day.status)})
      );
      var cardKids = [head];
      var block = pickOf(group, selected.id);
      if (block && block.name) {
        var currentGame = teamsAndTime(block, group, day);
        cardKids.push(h("p", {class: "pickline", text: "Current pick: " + block.name + (currentGame ? " \u00b7 " + currentGame : "") + " \u00b7 " + formatBlock(block, selected)}));
      }
      var earlier = morningPick(day, group.id, selected.id);
      if (earlier && earlier.name && !samePick(block, earlier)) {
        var morningGameLine = teamsAndTime(earlier, group, day);
        var morningText = "Morning pick: " + earlier.name + (morningGameLine ? " \u00b7 " + morningGameLine : "") + " \u00b7 " + formatBlock(earlier, selected);
        if (earlier.hit != null) morningText += " \u00b7 " + hitText(earlier.hit);
        cardKids.push(h("p", {class: "pickline morning-pick", text: morningText}));
      }
      available.forEach(function (player) {
        cardKids.push(renderPlayer(player, available, selected, mode, group, day));
      });
      if (removed.length) {
        cardKids.push(h("p", {class: "pickline", text: "No longer on the list"}));
        removed.forEach(function (player) {
          cardKids.push(renderPlayer(player, available, selected, mode, group, day));
        });
      }
      if (mode === "past") {
        var line = "Not final yet.";
        if (group.status === "graded") {
          line = group.scorers && group.scorers.length
            ? "Scored: " + group.scorers.join(", ")
            : "No one scored";
        }
        cardKids.push(h("p", {class: "pickline", text: line}));
      }
      var tint = mode === "past" ? pickTint(group.id) : "";
      grid.appendChild(h("article", {class: "card" + (tint ? " " + tint : "")}, cardKids));
    });
    return grid;
  }

  function renderCompare(day) {
    var methods = displayMethods(day);
    var placeholder = methods.length < 2;
    var head = [h("th", {text: "Group"}), h("th", {text: "Player"}), h("th", {text: "Team"})];
    methods.forEach(function (method) { head.push(h("th", {text: method.label})); });
    if (placeholder) head.push(h("th", {class: "placeholder", text: "Next method"}));
    var body = document.createElement("tbody");
    var selected = methodMeta(day);
    (day.groups || []).forEach(function (group) {
      var available = ordered((group.players || []).filter(isAvailable), selected.id, kindOf(selected));
      var removed = (group.players || []).filter(function (player) { return !isAvailable(player); });
      var players = available.concat(removed);
      var best = {};
      methods.forEach(function (method) {
        best[method.id] = bestOf(available, method.id, kindOf(method));
      });
      players.forEach(function (player) {
        var gone = !isAvailable(player);
        var who = player.name;
        if (gone && gameStartedFirst(player)) {
          var startedAt = torontoClock(player.start || player.game_started_at);
          who = player.name + (startedAt ? " \u00b7 game started " + startedAt : " \u00b7 game started");
        } else if (gone) {
          var when = torontoClock(player.removed_at);
          who = player.name + (when ? " \u00b7 removed " + when : " \u00b7 removed");
        }
        var cells = [
          h("td", {text: String(group.id)}),
          h("td", {class: "player-name", text: who}),
          h("td", {text: teamsAndTime(player, group, day)})
        ];
        methods.forEach(function (method) {
          var markValue = kindOf(method) === "rank" ? rankOf(player, method.id) : pOf(player, method.id);
          var mark = !gone && markValue != null && markValue === best[method.id];
          cells.push(h("td", {class: mark ? "ok" : "", text: formatMethodValue(player, method)}));
        });
        if (placeholder) cells.push(h("td", {class: "placeholder", text: "\u2014"}));
        var rowClass = [gone ? "removed" : (isStoredPick(player, group, "model") ? "pick" : ""), pickTint(group.id)].filter(Boolean).join(" ");
        var tr = h("tr", {class: rowClass}, cells);
        body.appendChild(tr);
      });
    });
    var note = placeholder
      ? "Side-by-side is ready for another method. It will add a column next to Model. Only Model is published today."
      : "Each column is one method. A marked cell is that column's leader among players still on the list. A marked row is the current model pick.";
    return h("section", {class: "card", id: "compare"},
      h("h2", {text: "Compare methods"}),
      h("p", {class: "muted small compare-note", text: note}),
      h("div", {class: "tablewrap"},
        h("table", {class: "data"},
          h("thead", null, h("tr", null, head)),
          body))
    );
  }

  function renderToday() {
    var view = document.getElementById("view-today");
    clear(view);
    var day = state.today;
    if (!day) {
      view.appendChild(h("section", {class: "card"},
        h("h2", {text: "No slate yet"}),
        h("p", {class: "muted", text: "today.json has not been published. The daily job writes it before the games."})));
      return;
    }
    view.appendChild(h("div", {class: "dayhead"},
      h("h2", {text: pretty(day.date)}),
      h("p", {class: "muted", text: statusLine(day)})));
    var skippedToday = renderSkipped(day);
    if (skippedToday) view.appendChild(skippedToday);
    var changesToday = renderListChanges(day);
    if (changesToday) view.appendChild(changesToday);
    var morningToday = renderMorningBanner(day);
    if (morningToday) view.appendChild(morningToday);
    view.appendChild(renderSummary(day, "today"));
    view.appendChild(h("div", {style: "height:12px"}));
    view.appendChild(renderGroups(day, "today"));
    view.appendChild(renderCompare(day));
  }

  function dateButton(row) {
    var label = pretty(row.date);
    if (row.picks) label += " \u00b7 " + row.hits + "/" + row.picks;
    else label += " \u00b7 pending";
    return h("button", {
      type: "button",
      class: "ghost" + (row.date === state.pastDate ? " on" : ""),
      text: label,
      onclick: function () { selectPast(row.date); }
    });
  }

  function monthKey(iso) {
    return String(iso || "").slice(0, 7);
  }

  function monthLabel(key) {
    var p = String(key || "").split("-");
    if (p.length < 2 || !p[0] || !p[1]) return key;
    var d = new Date(Date.UTC(+p[0], +p[1] - 1, 1));
    return d.toLocaleDateString("en-US", {month: "long", year: "numeric", timeZone: "UTC"});
  }

  function renderDateList(dates) {
    if (dates.length <= 24) {
      var flat = h("div", {class: "dates"});
      dates.forEach(function (row) { flat.appendChild(dateButton(row)); });
      return flat;
    }
    var groups = [];
    var byMonth = {};
    dates.forEach(function (row) {
      var key = monthKey(row.date);
      if (!byMonth[key]) {
        byMonth[key] = [];
        groups.push(key);
      }
      byMonth[key].push(row);
    });
    var selected = monthKey(state.pastDate) || groups[0];
    var wrap = h("div", {class: "past-months"});
    groups.forEach(function (key) {
      var rows = byMonth[key];
      var buttons = h("div", {class: "dates"});
      rows.forEach(function (row) { buttons.appendChild(dateButton(row)); });
      var noun = rows.length === 1 ? " day" : " days";
      wrap.appendChild(h("details", {class: "month", open: key === selected},
        h("summary", {text: monthLabel(key) + " \u00b7 " + rows.length + noun}),
        buttons
      ));
    });
    return wrap;
  }

  function renderPast() {
    var view = document.getElementById("view-past");
    clear(view);
    var index = state.index;
    var dates = (index && index.days) ? index.days : [];
    var tools = h("div", {class: "past-tools"},
      h("label", {class: "method", style: "margin-left:0"}, "Date ",
        (function () {
          var input = h("input", {type: "date", id: "pastDate", value: state.pastDate || ""});
          input.addEventListener("change", function () {
            if (input.value) selectPast(input.value);
          });
          return input;
        })())
    );
    view.appendChild(h("section", {class: "card"},
      h("h2", {text: "Past days"}),
      h("p", {class: "muted small", text: "The result is the current pick, from the latest list. The morning pick is shown when it differs. Players who scored are marked."}),
      tools,
      renderDateList(dates)));
    var months = view.querySelector(".past-months");
    var openMonth = months && months.querySelector("details[open]");
    if (months && openMonth) months.scrollTop = openMonth.offsetTop;
    if (!state.past) {
      view.appendChild(h("p", {class: "muted", text: dates.length ? "Pick a date." : "No days published yet."}));
      return;
    }
    var day = state.past;
    view.appendChild(h("div", {class: "dayhead"},
      h("h2", {text: pretty(day.date)}),
      h("p", {class: "muted", text: statusLine(day)})));
    var skippedPast = renderSkipped(day);
    if (skippedPast) view.appendChild(skippedPast);
    var changesPast = renderListChanges(day);
    if (changesPast) view.appendChild(changesPast);
    var morningPast = renderMorningBanner(day);
    if (morningPast) view.appendChild(morningPast);
    view.appendChild(renderSummary(day, "past"));
    view.appendChild(h("div", {style: "height:12px"}));
    view.appendChild(renderGroups(day, "past"));
  }

  // Widest solid line first, then a dash, then dots. Markers nest the same way
  // (circle, square, diamond) so a shared value still shows every series.
  var SERIES_STYLES = [
    {color: "#ff8c1a", width: 3.6, dash: null, marker: "circle", markerSize: 4.6},
    {color: "#7eb6ff", width: 2.4, dash: "7 4", marker: "square", markerSize: 2.7},
    {color: "#6fd389", width: 2.2, dash: "1.2 3.4", marker: "diamond", markerSize: 3.5}
  ];

  function seriesStyle(index) {
    return SERIES_STYLES[index % SERIES_STYLES.length];
  }

  function lineChart(spec) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 680 240");
    svg.setAttribute("role", "img");
    var dates = spec.dates || [];
    var series = spec.series || [];
    var baseline = spec.baseline || {values: []};
    var rate = spec.mode !== "hits";
    if (!dates.length) {
      svg.setAttribute("aria-label", "No graded days yet");
      return svg;
    }
    var w = 680, h = 240;
    var pad = {l: 42, r: 16, t: 16, b: 32};
    var innerW = w - pad.l - pad.r;
    var innerH = h - pad.t - pad.b;
    var yMax = rate ? 1 : 0;
    function consider(values) {
      (values || []).forEach(function (value) {
        if (typeof value === "number" && value > yMax) yMax = value;
      });
    }
    series.forEach(function (item) { consider(item.values); });
    consider(baseline.values);
    if (!rate) {
      var step = Math.max(1, Math.ceil((yMax || 1) / 4));
      yMax = Math.max(step, Math.ceil((yMax || 1) / step) * step);
    }
    function x(i) {
      if (dates.length === 1) return pad.l + innerW / 2;
      return pad.l + (innerW * i) / (dates.length - 1);
    }
    function y(v) {
      var top = rate ? 1 : yMax;
      var clamped = Math.max(0, v || 0);
      if (rate) clamped = Math.min(1, clamped);
      return pad.t + innerH * (1 - clamped / top);
    }
    function el(name, attrs) {
      var node = document.createElementNS("http://www.w3.org/2000/svg", name);
      Object.keys(attrs).forEach(function (key) { node.setAttribute(key, attrs[key]); });
      return node;
    }
    var ticks = rate ? [0, 0.25, 0.5, 0.75, 1] : [];
    if (!rate) {
      var tickStep = yMax / 4;
      for (var t = 0; t <= 4; t++) ticks.push(tickStep * t);
    }
    ticks.forEach(function (tick) {
      svg.appendChild(el("line", {
        x1: pad.l, x2: w - pad.r, y1: y(tick), y2: y(tick),
        stroke: "#24467d", "stroke-width": "1"
      }));
      svg.appendChild(el("text", {
        x: 4, y: y(tick) + 4, fill: "#9fb0cc", "font-size": "11",
        "font-family": "system-ui, sans-serif"
      }));
      svg.lastChild.textContent = rate ? Math.round(tick * 100) + "%" : String(Math.round(tick * 10) / 10);
    });
    function path(values) {
      var cmd = "";
      var pen = false;
      (values || []).forEach(function (value, i) {
        if (typeof value !== "number") {
          pen = false;
          return;
        }
        cmd += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(value).toFixed(1);
        pen = true;
      });
      return cmd;
    }
    function addMarker(shape, cx, cy, color, size) {
      if (shape === "square") {
        var side = size * 2;
        svg.appendChild(el("rect", {
          x: (cx - side / 2).toFixed(1),
          y: (cy - side / 2).toFixed(1),
          width: side.toFixed(1),
          height: side.toFixed(1),
          fill: color
        }));
        return;
      }
      if (shape === "diamond") {
        svg.appendChild(el("polygon", {
          points: [
            [cx, cy - size],
            [cx + size, cy],
            [cx, cy + size],
            [cx - size, cy]
          ].map(function (pair) {
            return pair[0].toFixed(1) + "," + pair[1].toFixed(1);
          }).join(" "),
          fill: color
        }));
        return;
      }
      svg.appendChild(el("circle", {
        cx: cx.toFixed(1), cy: cy.toFixed(1), r: String(size), fill: color
      }));
    }
    if (baseline.values) {
      svg.appendChild(el("path", {
        d: path(baseline.values), fill: "none", stroke: "#9fb0cc",
        "stroke-width": "2", "stroke-dasharray": "4 4",
        "stroke-linecap": "round"
      }));
    }
    // Thickest solid stroke first, so a later dash or dot leaves it visible.
    series.forEach(function (item) {
      var style = item.style;
      var attrs = {
        d: path(item.values), fill: "none", stroke: style.color,
        "stroke-width": String(style.width), "stroke-linecap": "round",
        "stroke-linejoin": "round"
      };
      if (style.dash) attrs["stroke-dasharray"] = style.dash;
      svg.appendChild(el("path", attrs));
    });
    var many = dates.length > 40;
    series.forEach(function (item) {
      var style = item.style;
      if (many) {
        var lastI = -1;
        (item.values || []).forEach(function (value, i) {
          if (typeof value === "number") lastI = i;
        });
        if (lastI >= 0) addMarker(style.marker, x(lastI), y(item.values[lastI]), style.color, style.markerSize);
        return;
      }
      (item.values || []).forEach(function (value, i) {
        if (typeof value !== "number") return;
        addMarker(style.marker, x(i), y(value), style.color, style.markerSize);
      });
    });
    var labelIndexes = [];
    if (many) {
      var lastMonth = "";
      dates.forEach(function (iso, i) {
        var month = String(iso || "").slice(0, 7);
        if (month && month !== lastMonth) {
          labelIndexes.push(i);
          lastMonth = month;
        }
      });
      if (labelIndexes[labelIndexes.length - 1] !== dates.length - 1) labelIndexes.push(dates.length - 1);
      var kept = [];
      labelIndexes.forEach(function (i) {
        if (!kept.length) {
          kept.push(i);
          return;
        }
        var prev = kept[kept.length - 1];
        if (Math.abs(x(i) - x(prev)) < 56 && i !== dates.length - 1) return;
        if (i === dates.length - 1 && kept.length > 1 && Math.abs(x(i) - x(prev)) < 56) kept.pop();
        kept.push(i);
      });
      labelIndexes = kept;
    } else {
      labelIndexes = [0, Math.floor((dates.length - 1) / 2), dates.length - 1];
    }
    labelIndexes.forEach(function (i) {
      if (!many && dates.length > 1 && i === Math.floor((dates.length - 1) / 2) && dates.length < 3) return;
      var label = el("text", {
        x: x(i), y: h - 8, fill: "#9fb0cc", "font-size": "11",
        "text-anchor": i === 0 ? "start" : i === dates.length - 1 ? "end" : "middle",
        "font-family": "system-ui, sans-serif"
      });
      label.textContent = String(dates[i] || "").slice(5);
      svg.appendChild(label);
    });
    var bits = series.map(function (item) {
      var last = null;
      (item.values || []).forEach(function (value) {
        if (typeof value === "number") last = value;
      });
      if (last == null) return null;
      return item.label + " " + (rate ? pct(last) : String(last));
    }).filter(Boolean);
    svg.setAttribute("aria-label", (spec.title || "Season") + ". " + bits.join(", "));
    return svg;
  }

  function chartSpec(block, mode) {
    return {
      title: mode === "hits" ? "Cumulative hits" : "Hit rate",
      dates: block.dates || [],
      mode: mode,
      series: (block.series || []).map(function (item, index) {
        return {
          label: item.label,
          style: seriesStyle(index),
          values: mode === "hits" ? item.hits : item.hit_rate
        };
      }),
      baseline: {
        label: "Random baseline",
        values: mode === "hits" ? block.random_hits : block.random_rate
      }
    };
  }

  function legendMark(style) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 36 14");
    svg.setAttribute("class", "swatch-line");
    svg.setAttribute("aria-hidden", "true");
    var line = document.createElementNS("http://www.w3.org/2000/svg", "path");
    line.setAttribute("d", "M1 7 H35");
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", style.color);
    line.setAttribute("stroke-width", String(Math.min(style.width, 3)));
    line.setAttribute("stroke-linecap", "round");
    if (style.dash) line.setAttribute("stroke-dasharray", style.dash);
    svg.appendChild(line);
    var color = style.color;
    var mid = 18;
    if (style.marker === "square") {
      var side = 6;
      var rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", String(mid - side / 2));
      rect.setAttribute("y", String(7 - side / 2));
      rect.setAttribute("width", String(side));
      rect.setAttribute("height", String(side));
      rect.setAttribute("fill", color);
      svg.appendChild(rect);
    } else if (style.marker === "diamond") {
      var poly = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
      poly.setAttribute("points", mid + ",2 " + (mid + 5) + ",7 " + mid + ",12 " + (mid - 5) + ",7");
      poly.setAttribute("fill", color);
      svg.appendChild(poly);
    } else if (style.marker === "circle") {
      var dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("cx", String(mid));
      dot.setAttribute("cy", "7");
      dot.setAttribute("r", "3.2");
      dot.setAttribute("fill", color);
      svg.appendChild(dot);
    }
    return svg;
  }

  function chartLegend(block) {
    var bits = (block.series || []).map(function (item, index) {
      return h("span", null, legendMark(seriesStyle(index)), item.label);
    });
    bits.push(h("span", null, h("i", {class: "swatch dash"}), "Random baseline"));
    return h("div", {class: "legend"}, bits);
  }

  function chartPair(block) {
    return h("div", {class: "chart-grid"},
      h("div", null,
        h("p", {class: "muted small chart-title", text: "Hit rate"}),
        h("div", {class: "chart-wrap"}, lineChart(chartSpec(block, "rate")))
      ),
      h("div", null,
        h("p", {class: "muted small chart-title", text: "Cumulative hits"}),
        h("div", {class: "chart-wrap"}, lineChart(chartSpec(block, "hits")))
      )
    );
  }

  function readStored(key) {
    try {
      return window.localStorage ? localStorage.getItem(key) : null;
    } catch (err) {
      return null;
    }
  }

  function writeStored(key, value) {
    try {
      if (window.localStorage) localStorage.setItem(key, value);
    } catch (err) {}
  }

  function loadMixFromPage() {
    var rules = mixApi();
    if (!rules) {
      state.mix = {preset: "", lists: {"1": "model", "2": "model", "3": "model"}, months: {}, phases: {}};
      return;
    }
    var query = new URLSearchParams(location.search);
    if (query.get("mix")) state.mix = rules.parseMix(query.get("mix"));
    else state.mix = rules.parseMix(readStored("hockey.mix") || "");
    if (query.get("method") === "custom") state.method = "custom";
    var phase = query.get("phase") || readStored("hockey.phase") || "combined";
    state.phaseFilter = phase === "regular" || phase === "playoffs" ? phase : "combined";
    var evalMode = query.get("eval") || readStored("hockey.eval") || "morning";
    state.evalMode = evalMode === "full_day" ? "full_day" : "morning";
  }

  function writeMixQuery() {
    var rules = mixApi();
    if (!rules) return;
    var url = new URL(location.href);
    var encoded = rules.serializeMix(state.mix);
    if (encoded) url.searchParams.set("mix", encoded);
    else url.searchParams.delete("mix");
    if (state.method === "custom") url.searchParams.set("method", "custom");
    else url.searchParams.delete("method");
    if (state.phaseFilter && state.phaseFilter !== "combined") url.searchParams.set("phase", state.phaseFilter);
    else url.searchParams.delete("phase");
    if (state.evalMode === "full_day") url.searchParams.set("eval", "full_day");
    else url.searchParams.delete("eval");
    writeStored("hockey.mix", encoded);
    writeStored("hockey.phase", state.phaseFilter);
    writeStored("hockey.eval", state.evalMode);
    var next = url.pathname + url.search + url.hash;
    if (next !== location.pathname + location.search + location.hash) {
      history.replaceState(null, "", next);
    }
  }

  function methodChoices() {
    return knownMethods().filter(function (method) { return method.id !== "custom"; });
  }

  function methodSelect(value, onChange) {
    var sel = document.createElement("select");
    var empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "No override";
    sel.appendChild(empty);
    methodChoices().forEach(function (method) {
      var opt = document.createElement("option");
      opt.value = method.id;
      opt.textContent = method.label;
      sel.appendChild(opt);
    });
    sel.value = value || "";
    sel.addEventListener("change", function () { onChange(sel.value); });
    return sel;
  }

  function renderMixPanel() {
    var panel = document.getElementById("mix-panel");
    var rules = mixApi();
    if (!panel || !rules) return;
    var showPanel = state.method === "custom";
    panel.hidden = !showPanel;
    if (!showPanel) return;
    clear(panel);
    if (!state.mix) loadMixFromPage();
    var mix = rules.copyMix(state.mix);
    var preset = document.createElement("select");
    [["", "Per list"], ["average", "Average of probabilities"], ["majority", "Majority of the three picks"]].forEach(function (pair) {
      var opt = document.createElement("option");
      opt.value = pair[0];
      opt.textContent = pair[1];
      preset.appendChild(opt);
    });
    preset.value = mix.preset;
    preset.addEventListener("change", function () {
      state.mix.preset = preset.value;
      writeMixQuery();
      renderMixPanel();
      show(state.view);
    });
    var grid = h("div", {class: "mix-grid"});
    ["1", "2", "3"].forEach(function (id) {
      var sel = methodSelect(mix.lists[id], function (value) {
        state.mix.lists[id] = value || "model";
        writeMixQuery();
        show(state.view);
      });
      if (!mix.lists[id]) sel.value = "model";
      else sel.value = mix.lists[id];
      if (mix.preset) sel.disabled = true;
      grid.appendChild(h("label", null, "List " + id, sel));
    });
    var month = document.createElement("select");
    [["", "Month"], ["10", "October"], ["11", "November"], ["12", "December"], ["1", "January"], ["2", "February"], ["3", "March"], ["4", "April"], ["5", "May"], ["6", "June"]].forEach(function (pair) {
      var opt = document.createElement("option");
      opt.value = pair[0];
      opt.textContent = pair[1];
      month.appendChild(opt);
    });
    var monthMethod = methodSelect("", function () {});
    var chips = [];
    Object.keys(mix.months).sort(function (a, b) { return Number(a) - Number(b); }).forEach(function (key) {
      var label = methodChoices().filter(function (method) { return method.id === mix.months[key]; })[0];
      var monthNames = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
      chips.push(h("button", {type: "button", class: "ghost", text: (monthNames[Number(key)] || key) + ": " + (label ? label.label : mix.months[key]), onclick: function () {
        delete state.mix.months[key];
        writeMixQuery();
        renderMixPanel();
        show(state.view);
      }}));
    });
    panel.appendChild(h("div", null,
      h("h2", {text: "Custom mix"}),
      h("p", {class: "muted small", text: "Chooses among the three methods. It does not recompute their probabilities. A phase override beats a month override, and a month override beats the per-list choice. The page still opens on the logistic model."}),
      h("div", {class: "mix-row"}, h("label", null, "Preset", preset)),
      grid,
      h("div", {class: "mix-row"},
        h("label", null, "Month override", month),
        h("label", null, "Method for that month", monthMethod),
        h("button", {type: "button", class: "ghost", text: "Add month", onclick: function () {
          if (!month.value || !monthMethod.value) return;
          state.mix.months[String(Number(month.value))] = monthMethod.value;
          writeMixQuery();
          renderMixPanel();
          show(state.view);
        }})
      ),
      chips.length ? h("div", {class: "mix-row"}, chips) : null,
      h("div", {class: "mix-row"},
        h("label", null, "Regular season", methodSelect(mix.phases.regular || "", function (value) {
          if (value) state.mix.phases.regular = value;
          else delete state.mix.phases.regular;
          writeMixQuery();
          show(state.view);
        })),
        h("label", null, "Playoffs", methodSelect(mix.phases.playoffs || "", function (value) {
          if (value) state.mix.phases.playoffs = value;
          else delete state.mix.phases.playoffs;
          writeMixQuery();
          show(state.view);
        }))
      )
    ));
  }

  function loadSeasonDays(base) {
    if (state.dayCache[base]) return Promise.resolve(state.dayCache[base]);
    if (state.dayLoads[base]) return state.dayLoads[base];
    var job = fetch(base + "/days/index.json", {cache: "no-store"}).then(function (res) {
      if (!res.ok) throw new Error("no index");
      return res.json();
    }).then(function (index) {
      var dates = [];
      (index && index.days || []).forEach(function (row) {
        if (row && row.date) dates.push(row.date);
      });
      return Promise.all(dates.map(function (date) {
        return fetch(base + "/days/" + date + ".json", {cache: "no-store"}).then(function (res) {
          if (!res.ok) return null;
          return res.json();
        }).catch(function () { return null; });
      }));
    }).then(function (days) {
      var clean = [];
      (days || []).forEach(function (day) {
        if (day && day.date) clean.push(day);
      });
      state.dayCache[base] = clean;
      return clean;
    }).catch(function () {
      state.dayCache[base] = [];
      return [];
    });
    state.dayLoads[base] = job;
    return job;
  }

  function loadSummaryDoc() {
    if (state.summaryDoc !== null) return Promise.resolve(state.summaryDoc);
    return fetch("data/seasons/summary.json", {cache: "no-store"}).then(function (res) {
      if (!res.ok) return null;
      return res.json();
    }).catch(function () { return null; }).then(function (doc) {
      state.summaryDoc = doc || false;
      return state.summaryDoc;
    });
  }

  function ensureRecords() {
    var bases = [];
    if (state.allSeasons) {
      (state.seasons || []).forEach(function (season) {
        if (season.base) bases.push(season);
      });
    } else if (root) {
      bases.push({id: state.seasonId || "live", base: root, label: ""});
    }
    return Promise.all(bases.map(function (season) {
      return loadSeasonDays(season.base).then(function (days) {
        days.forEach(function (day) {
          if (!day.season) day.season = season.id;
        });
        return days;
      });
    })).then(function (groups) {
      var all = [];
      groups.forEach(function (days) { all = all.concat(days); });
      state.catalog = all;
      return loadSummaryDoc();
    });
  }

  function metricsFor(methodId, phase) {
    var rules = mixApi();
    if (!rules) return null;
    var mode = state.evalMode;
    if (methodId !== "custom" && mode !== "full_day") {
      var stored = rules.storedMetrics(state.allSeasons ? state.summaryDoc : state.season, methodId, phase);
      if (!stored && state.allSeasons) stored = rules.storedMetrics(state.summaryDoc, methodId, phase);
      if (stored && !(state.catalog && state.catalog.length)) return stored;
      if (stored && !state.allSeasons) return stored;
    }
    if (state.catalog && state.catalog.length) {
      return rules.computeMetrics(state.catalog, methodId, state.mix, knownMethods(), phase, mode);
    }
    if (methodId !== "custom") return rules.storedMetrics(state.summaryDoc, methodId, phase);
    return null;
  }

  function countText(value) {
    if (value == null || isNaN(value)) return "\u2014";
    var rounded = Math.round(Number(value) * 1000) / 1000;
    return String(rounded);
  }

  function recordLine(row) {
    if (!row || !row.picks) return "\u2014";
    var days = row.days == null ? "\u2014" : String(row.days);
    var withHit = row.days_with_hit == null ? "\u2014" : String(row.days_with_hit);
    var streaks = row.streaks == null ? "\u2014" : String(row.streaks);
    var rate = row.hit_rate == null ? "\u2014" : pct(row.hit_rate);
    return days + " days \u00b7 " + countText(row.hits) + "/" + row.picks + " correct (" + rate + ") \u00b7 " + withHit + " with a hit \u00b7 " + streaks + " streaks";
  }

  function renderMetrics(view) {
    var rules = mixApi();
    if (!rules) return;
    var selected = state.method === "custom" ? rules.CUSTOM : methodMeta(state.season || {});
    var phases = [
      ["regular", "Regular season"],
      ["playoffs", "Playoffs"],
      ["combined", "Combined"]
    ];
    var filter = h("div", {class: "phase-filter"});
    var anyFull = (state.catalog || []).some(function (day) { return mixApi() && mixApi().hasFullDay(day); });
    if (!anyFull && mixApi() && mixApi().hasFullDay(state.today)) anyFull = true;
    if (!anyFull && mixApi() && mixApi().hasFullDay(state.past)) anyFull = true;
    if (anyFull) {
      [["morning", "Morning list"], ["full_day", "Full day"]].forEach(function (pair) {
        filter.appendChild(h("button", {
          type: "button",
          class: "ghost" + (state.evalMode === pair[0] ? " on" : ""),
          text: pair[1],
          onclick: function () {
            state.evalMode = pair[0];
            writeMixQuery();
            show(state.view);
          }
        }));
      });
    }
    phases.forEach(function (pair) {
      filter.appendChild(h("button", {
        type: "button",
        class: "ghost" + (state.phaseFilter === pair[0] ? " on" : ""),
        text: pair[1],
        onclick: function () {
          state.phaseFilter = pair[0];
          writeMixQuery();
          show(state.view);
        }
      }));
    });
    var blocks = phases.map(function (pair) {
      var stats = h("div", {class: "records"});
      trackMethods(state.season || state.today || {}).forEach(function (method) {
        var row = metricsFor(method.id, pair[0]);
        stats.appendChild(h("p", {class: "record-line" + (method.id === selected.id && state.phaseFilter === pair[0] ? " on" : "")},
          h("b", {text: method.label}),
          " " + recordLine(row)
        ));
      });
      return h("div", {class: "metric-block"}, h("h3", {text: pair[1]}), stats);
    });
    var note = "Hit % is scored picks over picks. A day with at least one correct scorer counts once. A 7-day streak is seven game days in a row with a scorer; the run then starts over, and a day with no games is skipped. Days are still loading when a figure is a dash and day files exist.";
    if (state.evalMode === "full_day") {
      note += " Full day uses each group's full_day pick, the latest list up to game start.";
    }
    view.appendChild(h("section", {class: "card"},
      h("div", {class: "dayhead"},
        h("h2", {text: state.allSeasons ? "All seasons" : "Records"}),
        h("p", {class: "muted", text: note})),
      filter,
      blocks
    ));
  }

  function renderSeason() {
    var view = document.getElementById("view-season");
    clear(view);
    renderMetrics(view);
    var season = state.allSeasons ? null : state.season;
    if (!season) {
      if (!state.allSeasons) {
        view.appendChild(h("section", {class: "card"},
          h("h2", {text: "Season"}),
          h("p", {class: "muted", text: "season.json has not been published yet."})));
      }
      if (!(state.catalog && state.catalog.length)) return;
    }
    if (!season && state.allSeasons) {
      var selectedAll = methodMeta({});
      var bodyAll = document.createElement("tbody");
      (state.catalog || []).forEach(function (day) {
        if (state.phaseFilter !== "combined" && mixApi() && mixApi().phaseOf(day) !== state.phaseFilter) return;
        state.renderDay = day;
        (day.groups || []).forEach(function (group) {
          var block = pickOf(group, selectedAll.id) || {};
          var hit = hitOf(group, selectedAll.id);
          bodyAll.appendChild(h("tr", null,
            h("td", {text: pretty(day.date)}),
            h("td", {text: String(group.id)}),
            h("td", {class: "player-name", text: block.name || "\u2014"}),
            h("td", {text: formatBlock(block, selectedAll)}),
            h("td", {class: hitClass(hit) === "hit" ? "ok" : "muted", text: hitText(hit, group.status || day.status)}),
            h("td", {text: "\u2014"}),
            h("td", {text: "\u2014"}),
            h("td", {text: "\u2014"})
          ));
        });
        state.renderDay = null;
      });
      view.appendChild(h("section", {class: "card"},
        h("h2", {text: "Every pick \u00b7 " + selectedAll.label}),
        h("div", {class: "tablewrap season-table"},
          h("table", {class: "data"},
            h("thead", null, h("tr", null,
              h("th", {text: "Date"}), h("th", {text: "Group"}), h("th", {text: "Pick"}),
              h("th", {text: "Value"}), h("th", {text: "Hit"}), h("th", {text: ""}),
              h("th", {text: ""}), h("th", {text: ""})
            )),
            bodyAll))
      ));
      return;
    }
    var selected = methodMeta(season);
    var block = season.by_method && season.by_method[selected.id];
    var viewSeason = block || (selected.id === "model" || selected.id === season.method ? season : {summary: {}, days: []});
    var sum = viewSeason.summary || {};
    var compare = null;
    if (season.by_method && methodsOf(season).length > 1) {
      compare = h("div", {class: "records"}, methodsOf(season).map(function (method) {
        var part = season.by_method[method.id] || {};
        var partSum = part.summary || {};
        return h("p", {class: "record-line" + (method.id === selected.id ? " on" : "")},
          h("b", {text: method.label}),
          " " + recordLine(partSum)
        );
      }));
    }
    view.appendChild(h("section", {class: "card"},
      h("div", {class: "dayhead"},
        h("h2", {text: (season.season || "Season") + " tracker"}),
        h("p", {class: "muted", text: "Each method is graded on its current pick. Days already graded keep that result. The charts are year to date."})),
      compare,
      h("p", {class: "record-line"}, recordLine(sum)),
      h("div", {class: "stats"},
        h("div", {class: "stat"}, h("b", {text: pct(sum.top3_rate)}), h("span", {text: "Top 3 scored"})),
        h("div", {class: "stat"}, h("b", {text: pct(sum.random_baseline)}), h("span", {text: "Random baseline"}))
      ),
      season.charts && season.charts.overall
        ? h("div", null, chartLegend(season.charts.overall), chartPair(season.charts.overall))
        : h("p", {class: "muted", text: "Year-to-date charts appear after the season file is rebuilt."})
    ));
    if (season.charts && season.charts.groups && season.charts.groups.length) {
      view.appendChild(h("h2", {class: "section-title", text: "By pick"}));
      season.charts.groups.forEach(function (group) {
        view.appendChild(h("section", {class: "card"},
          h("h2", {text: group.label || ("Pick " + group.id)}),
          h("p", {class: "muted small", text: "Same three methods, this pick only, with this pick's random baseline."}),
          chartPair(group)
        ));
      });
    }

    var valueHeader = kindOf(selected) === "rank" ? "Goals/game" : "Probability";
    var body = document.createElement("tbody");
    var useDays = state.method === "custom" || state.phaseFilter !== "combined" || state.evalMode === "full_day";
    var tableDays = useDays && state.catalog && state.catalog.length
      ? state.catalog.filter(function (day) {
        if (state.phaseFilter !== "combined" && mixApi() && mixApi().phaseOf(day) !== state.phaseFilter) return false;
        if (!state.allSeasons && state.seasonId && day.season && day.season !== state.seasonId) return false;
        return true;
      })
      : null;
    if (tableDays) {
      tableDays.forEach(function (day) {
        state.renderDay = day;
        (day.groups || []).forEach(function (group) {
          var block = pickOf(group, selected.id) || {};
          var hit = hitOf(group, selected.id);
          body.appendChild(h("tr", null,
            h("td", {text: pretty(day.date)}),
            h("td", {text: String(group.id)}),
            h("td", {class: "player-name", text: block.name || "\u2014"}),
            h("td", {text: formatBlock(block, selected)}),
            h("td", {class: hitClass(hit) === "hit" ? "ok" : "muted", text: hitText(hit, group.status || day.status)}),
            h("td", {text: "\u2014"}),
            h("td", {text: "\u2014"}),
            h("td", {text: "\u2014"})
          ));
        });
        state.renderDay = null;
      });
    } else {
      (viewSeason.days || []).forEach(function (day) {
        if (state.phaseFilter !== "combined" && day.phase && mixApi() && mixApi().phaseOf(day) !== state.phaseFilter) return;
        (day.groups || []).forEach(function (group) {
          var value = kindOf(selected) === "rank"
            ? (typeof group.goals_per_game === "number" ? group.goals_per_game.toFixed(2) : "\u2014")
            : pct(group.probability);
          body.appendChild(h("tr", null,
            h("td", {text: pretty(day.date)}),
            h("td", {text: String(group.id)}),
            h("td", {class: "player-name", text: group.pick || "\u2014"}),
            h("td", {text: value}),
            h("td", {class: hitClass(group.hit) === "hit" ? "ok" : "muted", text: hitText(group.hit, group.status || day.status)}),
            h("td", {text: group.top3_hits == null ? "\u2014" : String(group.top3_hits)}),
            h("td", {text: pct(group.random)}),
            h("td", {text: pct(day.running_hit_rate)})
          ));
        });
      });
    }
    var pickRows = body.children ? body.children.length : 0;
    view.appendChild(h("section", {class: "card"},
      h("h2", {text: "Every pick \u00b7 " + selected.label}),
      h("div", {class: pickRows > 48 ? "tablewrap season-table" : "tablewrap"},
        h("table", {class: "data"},
          h("thead", null, h("tr", null,
            h("th", {text: "Date"}),
            h("th", {text: "Group"}),
            h("th", {text: "Pick"}),
            h("th", {text: valueHeader}),
            h("th", {text: "Hit"}),
            h("th", {text: "Top-3 hits"}),
            h("th", {text: "Random"}),
            h("th", {text: "Running hit rate"})
          )),
          body))
    ));
  }

  function show(view) {
    if (views.indexOf(view) === -1) view = "today";
    if (state.backtest && view === "today") view = "season";
    state.view = view;
    if (location.hash !== "#" + view) {
      history.replaceState(null, "", location.pathname + location.search + "#" + view);
    }
    views.forEach(function (name) {
      var section = document.getElementById("view-" + name);
      section.hidden = name !== view;
      var btn = document.querySelector('[data-view="' + name + '"]');
      if (btn) {
        btn.classList.toggle("on", name === view);
        btn.setAttribute("aria-pressed", name === view ? "true" : "false");
      }
    });
    renderMixPanel();
    if (view === "today") renderToday();
    if (view === "past") {
      if (!state.past && state.pastDate) selectPast(state.pastDate);
      else renderPast();
    }
    if (view === "season") {
      renderSeason();
      ensureRecords().then(function () {
        if (state.view === "season") renderSeason();
      });
    } else if (state.method === "custom") {
      ensureRecords();
    }
  }

  function selectPast(iso) {
    state.pastDate = iso;
    var token = loadToken;
    var base = root;
    load("days/" + iso + ".json").then(function (day) {
      if (token !== loadToken || base !== root) return;
      state.past = day;
      if (state.view === "past") renderPast();
    }).catch(function () {
      if (token !== loadToken || base !== root) return;
      state.past = null;
      setBanner("No published file for " + iso + ".");
      if (state.view === "past") renderPast();
    });
  }

  function applyLoaded(today, season, index) {
    state.today = today;
    state.season = season;
    state.index = index;
    if ((season && season.backtest) || (index && index.backtest)) {
      state.backtest = true;
      state.today = null;
    }
    fillMethodSelect();
    updateChrome();
    if (!state.today && !state.season && !state.index) {
      setBanner("No published JSON in " + root + "/ yet.");
    } else {
      setBanner("");
    }
    var graded = ((state.index && state.index.days) || []).filter(function (row) {
      return row.status === "graded" || row.status === "partial";
    });
    var first = graded[0] || ((state.index && state.index.days) || [])[0];
    state.past = null;
    state.pastDate = first ? first.date : null;
    if (state.backtest && state.view === "today") state.view = "season";
    show(state.view);
    if (state.pastDate) selectPast(state.pastDate);
  }

  function loadBundle() {
    var token = ++loadToken;
    var backtest = state.backtest;
    var jobs = [];
    if (!backtest) jobs.push(load("today.json").catch(function () { return null; }));
    jobs.push(load("season.json").catch(function () { return null; }));
    jobs.push(load("days/index.json").catch(function () { return null; }));
    return Promise.all(jobs).then(function (all) {
      if (token !== loadToken) return;
      if (backtest) applyLoaded(null, all[0], all[1]);
      else applyLoaded(all[0], all[1], all[2]);
    });
  }

  function selectSeason(id, fromUser) {
    if (id === "all") {
      state.seasonId = "all";
      state.allSeasons = true;
      state.backtest = false;
      root = "data";
      state.view = "season";
      if (fromUser) writeSeasonQuery("all");
      fillSeasonSelect();
      updateChrome();
      show("season");
      return ensureRecords();
    }
    state.allSeasons = false;
    var chosen = state.seasons ? seasonById(state.seasons, id) : null;
    if (!chosen && state.seasons) chosen = defaultSeason(state.seasons);
    if (!chosen) {
      state.seasons = null;
      state.seasonId = null;
      state.backtest = false;
      root = fallbackRoot;
      updateChrome();
      return loadBundle();
    }
    state.seasonId = chosen.id;
    state.backtest = !!chosen.backtest;
    root = chosen.base;
    if (fromUser) writeSeasonQuery(chosen.id);
    fillSeasonSelect();
    updateChrome();
    return loadBundle();
  }

  function boot() {
    bindPlayerDialog();
    loadMixFromPage();
    var hash = (location.hash || "").replace("#", "");
    if (views.indexOf(hash) !== -1) state.view = hash;
    document.querySelectorAll("[data-view]").forEach(function (btn) {
      btn.addEventListener("click", function () { show(btn.getAttribute("data-view")); });
    });
    document.getElementById("method").addEventListener("change", function (event) {
      if (event.target.value) {
        state.method = event.target.value;
        writeMixQuery();
        show(state.view);
      }
    });
    var seasonSelect = document.getElementById("season");
    if (seasonSelect) {
      seasonSelect.addEventListener("change", function (event) {
        if (event.target.value && event.target.value !== state.seasonId) {
          selectSeason(event.target.value, true);
        }
      });
    }
    window.addEventListener("hashchange", function () {
      var next = (location.hash || "").replace("#", "");
      if (views.indexOf(next) !== -1 && next !== state.view) show(next);
    });
    loadManifest().then(function (seasons) {
      state.seasons = seasons;
      var requestedId = seasonIdFromQuery();
      if (requestedId === "all") return selectSeason("all", false);
      var requested = seasonById(seasons, requestedId);
      if (params.get("season") && !requested) writeSeasonQuery("");
      var chosen = requested || defaultSeason(seasons);
      return selectSeason(chosen.id, false);
    }).catch(function () {
      state.seasons = null;
      state.seasonId = null;
      state.backtest = false;
      root = fallbackRoot;
      updateChrome();
      return loadBundle();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else boot();
})();
