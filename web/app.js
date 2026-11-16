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
   There is no second source and nothing here submits a pick. */
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
    backtest: false
  };

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
    if (state.seasonId) sel.value = state.seasonId;
  }

  function isAvailable(player) {
    return !player || player.available !== false;
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
    if (!player || player.available !== false) return "";
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

  function formatMoves(entries) {
    return (entries || []).map(function (entry) {
      var name = entry.name || ("#" + entry.pid);
      if (entry.group == null) return name;
      return name + " (group " + entry.group + ")";
    }).join(", ");
  }

  function renderListChanges(day) {
    var snaps = ((day && day.snapshots) || []).filter(function (snap) {
      return (snap.added && snap.added.length) || (snap.removed && snap.removed.length);
    });
    if (!snaps.length) return null;
    var items = snaps.map(function (snap) {
      var bits = [torontoClock(snap.time) || snap.time || ""];
      if (snap.added && snap.added.length) bits.push("Added: " + formatMoves(snap.added));
      if (snap.removed && snap.removed.length) bits.push("Removed: " + formatMoves(snap.removed));
      return h("li", {text: bits.filter(Boolean).join(" \u00b7 ")});
    });
    return h("section", {class: "card", id: "list-changes"},
      h("h2", {text: "List changes"}),
      h("p", {class: "muted small", text: "Tims changed who was available. Current picks use the latest list. Someone who left is still shown, grayed out, and is not a current pick."}),
      h("ul", {class: "list-changes"}, items)
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

  function pickOf(group, methodId) {
    var block = group.method_picks && group.method_picks[methodId];
    if (block) return block;
    if (methodId === "model") return group.pick || null;
    return null;
  }

  function hitOf(group, methodId) {
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
      if (p && p.available === false) return;
      var v = kind === "rank" ? rankOf(p, method) : pOf(p, method);
      if (v == null) return;
      if (best == null || (kind === "rank" ? v < best : v > best)) best = v;
    });
    return best;
  }

  function highlighted(player, players, method, mode, kind, group) {
    if (player && player.available === false) return false;
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

  function matchup(player) {
    var where = player.home ? "vs" : "@";
    var tag = player.home ? "Home" : "Away";
    return player.team + " " + where + " " + player.opp + " \u00b7 " + tag;
  }

  function hitText(hit) {
    if (hit == null) return "Pending";
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

  function fillMethodSelect() {
    var sel = document.getElementById("method");
    var methods = knownMethods();
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
    if (!methods.some(function (m) { return m.id === state.method; })) state.method = "model";
    sel.value = state.method;
  }

  function statusLine(day) {
    if (!day) return "";
    if (day.status === "graded") return "Final";
    if (day.status === "partial") return "Some games still going";
    return "Games not final yet. Results land after the slate is done.";
  }

  function renderSummary(day, mode) {
    var wrap = h("div", {class: "summary"});
    var methods = displayMethods(day);
    var selected = methodMeta(day);
    var multi = methods.length > 1;
    (day.groups || []).forEach(function (group) {
      var pick = pickOf(group, selected.id) || {};
      var hit = hitOf(group, selected.id);
      var bits = [
        h("div", {class: "ghead"},
          h("h3", {text: "Group " + group.id}),
          mode === "past" || day.status !== "pending"
            ? h("span", {class: "pill " + hitClass(hit), text: hitText(hit)})
            : null)
      ];
      if (!multi) {
        bits.push(h("div", {class: "who", text: pick.name || "No pick"}));
        bits.push(h("div", {class: "muted small", text: pick.team ? (pick.team + (pick.home ? " vs " : " @ ") + pick.opp) : ""}));
        bits.push(h("div", {class: "pct", text: pct(pick.probability)}));
      } else {
        bits.push(h("div", {class: "leaders"}, methods.map(function (method) {
          var block = pickOf(group, method.id);
          return h("div", {class: method.id === selected.id ? "on" : ""},
            h("span", {class: "lab", text: method.label}),
            h("span", {class: "who", text: block && block.name ? block.name : "\u2014"}),
            h("span", {class: "pct", text: formatBlock(block, method)})
          );
        })));
      }
      displayMethods(day).forEach(function (method) {
        var earlier = morningPick(day, group.id, method.id);
        if (!earlier || !earlier.name || samePick(pickOf(group, method.id), earlier)) return;
        var text = "Morning pick \u00b7 " + method.label + ": " + earlier.name;
        if (earlier.hit != null) text += " \u00b7 " + hitText(earlier.hit);
        bits.push(h("p", {class: "pickline morning-pick", text: text}));
      });
      wrap.appendChild(h("article", {class: "card"}, bits));
    });
    return wrap;
  }

  function renderPlayer(player, players, method, mode, group) {
    var selected = method && method.id ? method : methodMeta(null);
    var valueText = formatMethodValue(player, selected);
    var on = highlighted(player, players, selected.id, mode, kindOf(selected), group);
    var row = h("div", {class: "row"},
      h("span", {class: "name"},
        player.name,
        on ? " " : null,
        on ? h("span", {class: "pill", text: "Pick"}) : null),
      h("span", {class: "pct", text: valueText})
    );
    var gone = removedNote(player);
    var meta = h("div", {class: "meta"},
      matchup(player),
      player.position ? " \u00b7 " + player.position : "",
      gone ? " \u00b7 " : "",
      gone ? h("span", {class: "removed-note", text: gone}) : null,
      scoredText(player) ? " \u00b7 " : "",
      scoredText(player) ? h("span", {class: "scored", text: scoredText(player)}) : null
    );
    var stats = kindOf(selected) === "rank" ? styleLine(player) : "";
    return h("div", {class: "player" + (on ? " pick" : "") + (player.available === false ? " removed" : "")},
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
      var removed = (group.players || []).filter(function (player) { return player.available === false; });
      var hit = hitOf(group, selected.id);
      var head = h("div", {class: "ghead"},
        h("h3", {text: "Group " + group.id}),
        h("span", {class: "pill " + hitClass(hit), text: mode === "today" && day.status === "pending" ? available.length + " players" : hitText(hit)})
      );
      var cardKids = [head];
      var block = pickOf(group, selected.id);
      if (block && block.name) {
        cardKids.push(h("p", {class: "pickline", text: "Current pick: " + block.name + " \u00b7 " + formatBlock(block, selected)}));
      }
      var earlier = morningPick(day, group.id, selected.id);
      if (earlier && earlier.name && !samePick(block, earlier)) {
        var morningText = "Morning pick: " + earlier.name + " \u00b7 " + formatBlock(earlier, selected);
        if (earlier.hit != null) morningText += " \u00b7 " + hitText(earlier.hit);
        cardKids.push(h("p", {class: "pickline morning-pick", text: morningText}));
      }
      available.forEach(function (player) {
        cardKids.push(renderPlayer(player, available, selected, mode, group));
      });
      if (removed.length) {
        cardKids.push(h("p", {class: "pickline", text: "No longer on the list"}));
        removed.forEach(function (player) {
          cardKids.push(renderPlayer(player, available, selected, mode, group));
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
      grid.appendChild(h("article", {class: "card"}, cardKids));
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
      var removed = (group.players || []).filter(function (player) { return player.available === false; });
      var players = available.concat(removed);
      var best = {};
      methods.forEach(function (method) {
        best[method.id] = bestOf(available, method.id, kindOf(method));
      });
      players.forEach(function (player) {
        var gone = player.available === false;
        var who = player.name;
        if (gone) {
          var when = torontoClock(player.removed_at);
          who = player.name + (when ? " \u00b7 removed " + when : " \u00b7 removed");
        }
        var cells = [
          h("td", {text: String(group.id)}),
          h("td", {class: "player-name", text: who}),
          h("td", {text: player.team + (player.home ? " vs " : " @ ") + player.opp})
        ];
        methods.forEach(function (method) {
          var markValue = kindOf(method) === "rank" ? rankOf(player, method.id) : pOf(player, method.id);
          var mark = !gone && markValue != null && markValue === best[method.id];
          cells.push(h("td", {class: mark ? "ok" : "", text: formatMethodValue(player, method)}));
        });
        if (placeholder) cells.push(h("td", {class: "placeholder", text: "\u2014"}));
        var rowClass = gone ? "removed" : (isStoredPick(player, group, "model") ? "pick" : "");
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

  function renderSeason() {
    var view = document.getElementById("view-season");
    clear(view);
    var season = state.season;
    if (!season) {
      view.appendChild(h("section", {class: "card"},
        h("h2", {text: "Season"}),
        h("p", {class: "muted", text: "season.json has not been published yet."})));
      return;
    }
    var selected = methodMeta(season);
    var block = season.by_method && season.by_method[selected.id];
    var viewSeason = block || (selected.id === "model" || selected.id === season.method ? season : {summary: {}, days: []});
    var sum = viewSeason.summary || {};
    var hits = sum.hits == null ? "\u2014" : (Math.round(sum.hits * 1000) / 1000);
    var compare = null;
    if (season.by_method && methodsOf(season).length > 1) {
      compare = h("div", {class: "stats"}, methodsOf(season).map(function (method) {
        var part = season.by_method[method.id] || {};
        var partSum = part.summary || {};
        var partHits = partSum.hits == null ? "\u2014" : (Math.round(partSum.hits * 1000) / 1000);
        return h("div", {class: "stat" + (method.id === selected.id ? " on" : "")},
          h("b", {text: pct(partSum.hit_rate)}),
          h("span", {text: method.label + " \u00b7 " + partHits + " / " + (partSum.picks || 0)})
        );
      }));
    }
    view.appendChild(h("section", {class: "card"},
      h("div", {class: "dayhead"},
        h("h2", {text: (season.season || "Season") + " tracker"}),
        h("p", {class: "muted", text: "Each method is graded on its current pick. Days already graded keep that result. The charts are year to date."})),
      compare,
      h("div", {class: "stats"},
        h("div", {class: "stat"}, h("b", {text: pct(sum.hit_rate)}), h("span", {text: "Hit rate"})),
        h("div", {class: "stat"}, h("b", {text: hits + " / " + (sum.picks || 0)}), h("span", {text: "Picks hit"})),
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
    (viewSeason.days || []).forEach(function (day) {
      (day.groups || []).forEach(function (group) {
        var value = kindOf(selected) === "rank"
          ? (typeof group.goals_per_game === "number" ? group.goals_per_game.toFixed(2) : "\u2014")
          : pct(group.probability);
        body.appendChild(h("tr", null,
          h("td", {text: pretty(day.date)}),
          h("td", {text: String(group.id)}),
          h("td", {class: "player-name", text: group.pick || "\u2014"}),
          h("td", {text: value}),
          h("td", {class: hitClass(group.hit) === "hit" ? "ok" : "muted", text: hitText(group.hit)}),
          h("td", {text: group.top3_hits == null ? "\u2014" : String(group.top3_hits)}),
          h("td", {text: pct(group.random)}),
          h("td", {text: pct(day.running_hit_rate)})
        ));
      });
    });
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
      history.replaceState(null, "", "#" + view);
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
    if (view === "today") renderToday();
    if (view === "past") {
      if (!state.past && state.pastDate) selectPast(state.pastDate);
      else renderPast();
    }
    if (view === "season") renderSeason();
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
    var hash = (location.hash || "").replace("#", "");
    if (views.indexOf(hash) !== -1) state.view = hash;
    document.querySelectorAll("[data-view]").forEach(function (btn) {
      btn.addEventListener("click", function () { show(btn.getAttribute("data-view")); });
    });
    document.getElementById("method").addEventListener("change", function (event) {
      if (event.target.value) {
        state.method = event.target.value;
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
      var requested = seasonById(seasons, seasonIdFromQuery());
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
