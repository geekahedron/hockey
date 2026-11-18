/* Custom mix and the record math.
   The three published methods are not recomputed here. A mix only chooses
   among their picks, or averages the probability methods that already exist.
   window.HockeyMix is the same functions the page uses. */
(function (root) {
  var CUSTOM = {id: "custom", label: "Custom mix", kind: "custom"};
  var AGGREGATE = {id: "aggregate", label: "Aggregate", kind: "probability"};
  var PHASES = ["regular", "playoffs", "combined"];

  function defaultMix() {
    return {
      preset: "",
      lists: {"1": "model", "2": "model", "3": "model"},
      months: {},
      phases: {}
    };
  }

  function copyMix(config) {
    var base = defaultMix();
    var src = config || {};
    base.preset = src.preset === "average" || src.preset === "majority" ? src.preset : "";
    ["1", "2", "3"].forEach(function (id) {
      if (src.lists && src.lists[id]) base.lists[id] = String(src.lists[id]);
    });
    Object.keys(src.months || {}).forEach(function (month) {
      var key = String(Number(month));
      if (key !== "NaN" && Number(key) >= 1 && Number(key) <= 12 && src.months[month]) {
        base.months[key] = String(src.months[month]);
      }
    });
    ["regular", "playoffs"].forEach(function (phase) {
      if (src.phases && src.phases[phase]) base.phases[phase] = String(src.phases[phase]);
    });
    return base;
  }

  function serializeMix(config) {
    var mix = copyMix(config);
    if (mix.preset === "average") return "avg";
    if (mix.preset === "majority") return "maj";
    var parts = [];
    ["1", "2", "3"].forEach(function (id) {
      if (mix.lists[id] && mix.lists[id] !== "model") parts.push(id + "=" + mix.lists[id]);
    });
    Object.keys(mix.months).sort(function (a, b) { return Number(a) - Number(b); }).forEach(function (month) {
      parts.push("m" + month + "=" + mix.months[month]);
    });
    if (mix.phases.regular) parts.push("fr=" + mix.phases.regular);
    if (mix.phases.playoffs) parts.push("fp=" + mix.phases.playoffs);
    return parts.join("|");
  }

  function parseMix(text) {
    var mix = defaultMix();
    var raw = String(text || "").replace(/^\s+|\s+$/g, "");
    if (!raw) return mix;
    if (raw === "avg" || raw === "average") {
      mix.preset = "average";
      return mix;
    }
    if (raw === "maj" || raw === "majority") {
      mix.preset = "majority";
      return mix;
    }
    raw.split("|").forEach(function (part) {
      var bits = part.split("=");
      if (bits.length !== 2 || !bits[0] || !bits[1]) return;
      var key = bits[0];
      var value = bits[1];
      if (key === "1" || key === "2" || key === "3") mix.lists[key] = value;
      else if (key.charAt(0) === "m") {
        var month = String(Number(key.slice(1)));
        if (month !== "NaN" && Number(month) >= 1 && Number(month) <= 12) mix.months[month] = value;
      } else if (key === "fr") mix.phases.regular = value;
      else if (key === "fp") mix.phases.playoffs = value;
    });
    return mix;
  }

  function presetLabel(preset) {
    if (preset === "average") return "Average of probabilities";
    if (preset === "majority") return "Majority of the three picks";
    return "Per list";
  }

  function monthOf(date) {
    var text = String(date || "");
    if (text.length < 7) return "";
    var month = Number(text.slice(5, 7));
    if (!month || month < 1 || month > 12) return "";
    return String(month);
  }

  function phaseOf(day) {
    var phase = day && (day.phase || day.season_phase);
    if (phase === "playoff") return "playoffs";
    if (phase === "playoffs" || phase === "regular") return phase;
    return "regular";
  }

  function methodForList(config, groupId, date, phase) {
    var mix = copyMix(config);
    var phaseMethod = mix.phases[phase === "playoffs" ? "playoffs" : "regular"];
    if (phaseMethod) return phaseMethod;
    var month = monthOf(date);
    if (month && mix.months[month]) return mix.months[month];
    return mix.lists[String(groupId)] || "model";
  }

  function fullDayOf(day, group) {
    if (group && group.full_day && typeof group.full_day === "object" && !Array.isArray(group.full_day)) {
      return group.full_day;
    }
    var bag = day && day.full_day;
    var groups = bag && (bag.groups || (Array.isArray(bag) ? bag : null));
    if (!groups) return null;
    for (var i = 0; i < groups.length; i++) {
      if (groups[i] && groups[i].id === group.id) return groups[i];
    }
    return null;
  }

  function hasFullDay(day) {
    if (!day) return false;
    if (day.full_day) return true;
    var groups = day.groups || [];
    for (var i = 0; i < groups.length; i++) {
      if (groups[i] && groups[i].full_day) return true;
    }
    return false;
  }

  function viewOf(day, group, mode) {
    var extra = mode === "full_day" ? fullDayOf(day, group) : null;
    var base = group || {};
    var overlay = extra || {};
    return {
      id: base.id,
      status: overlay.status || base.status,
      hit: overlay.hit != null ? overlay.hit : base.hit,
      pick: overlay.pick || base.pick || null,
      method_picks: overlay.method_picks || base.method_picks || {},
      players: overlay.players || base.players || [],
      top3_hits: overlay.top3_hits != null ? overlay.top3_hits : base.top3_hits,
      random: overlay.random != null ? overlay.random : base.random
    };
  }

  function eligible(player, pending, now) {
    if (!player) return false;
    if (player.unavailable_reason === "removed") return false;
    if (!pending) {
      if (player.available === false && !player.game_started && player.unavailable_reason !== "game_started") {
        return false;
      }
      return true;
    }
    if (player.available === false) return false;
    if (player.start && now != null) {
      var start = Date.parse(player.start);
      if (!isNaN(start) && now >= start) return false;
    }
    return true;
  }

  function probabilityOf(player, methodId) {
    if (!player || !player.probability) return null;
    var value = player.probability[methodId];
    return typeof value === "number" ? value : null;
  }

  function probabilityMethods(methods) {
    return (methods || []).filter(function (method) {
      return method && method.id !== "custom" && method.kind !== "rank";
    });
  }

  function playerAverage(player, methods) {
    var values = [];
    probabilityMethods(methods).forEach(function (method) {
      var value = probabilityOf(player, method.id);
      if (value != null) values.push(value);
    });
    if (!values.length) return null;
    var sum = 0;
    values.forEach(function (value) { sum += value; });
    return sum / values.length;
  }

  function hitFromPlayers(players, pids) {
    if (!pids || !pids.length) return null;
    var known = 0;
    var hits = 0;
    pids.forEach(function (pid) {
      (players || []).forEach(function (player) {
        if (player.pid !== pid || player.scored == null) return;
        known += 1;
        hits += player.scored ? 1 : 0;
      });
    });
    if (!known) return null;
    return hits / pids.length;
  }

  function namesFor(players, pids) {
    var names = [];
    pids.forEach(function (pid) {
      (players || []).forEach(function (player) {
        if (player.pid === pid && player.name) names.push(player.name);
      });
    });
    return names.join(" / ");
  }

  function blockForMethod(view, methodId) {
    var picks = view.method_picks || {};
    if (picks[methodId] && (picks[methodId].pids || []).length) return picks[methodId];
    if (methodId === "model" && view.pick && (view.pick.pids || []).length) return view.pick;
    return null;
  }

  function storedHit(view, methodId, block) {
    if (block && typeof block.hit === "number") return block.hit;
    if (methodId === "model" && typeof view.hit === "number") return view.hit;
    return null;
  }

  function samePids(left, right) {
    if (!left || !right || left.length !== right.length || !left.length) return false;
    var a = left.map(Number).sort(function (x, y) { return x - y; });
    var b = right.map(Number).sort(function (x, y) { return x - y; });
    for (var i = 0; i < a.length; i++) {
      if (a[i] !== b[i]) return false;
    }
    return true;
  }

  function hitFromStoredPick(view, methods, pids, fallback) {
    if (fallback != null) return fallback;
    var found = null;
    (methods || []).forEach(function (method) {
      if (found != null || !method || method.id === "custom") return;
      var block = blockForMethod(view, method.id);
      if (block && samePids(block.pids || [], pids)) found = storedHit(view, method.id, block);
    });
    return found;
  }

  function chooseAverage(view, players, methods) {
    var best = null;
    var tied = [];
    players.forEach(function (player) {
      var value = playerAverage(player, methods);
      if (value == null) return;
      if (best == null || value > best + 1e-12) {
        best = value;
        tied = [player];
      } else if (Math.abs(value - best) <= 1e-12) {
        tied.push(player);
      }
    });
    var pids = tied.map(function (player) { return player.pid; });
    return {
      pids: pids,
      name: namesFor(players, pids),
      probability: best,
      hit: hitFromStoredPick(view, methods, pids, hitFromPlayers(players, pids)),
      rule: "Average of probabilities"
    };
  }

  function chooseMajority(view, players, methods) {
    var counts = {};
    (methods || []).forEach(function (method) {
      if (!method || method.id === "custom") return;
      var block = blockForMethod(view, method.id);
      ((block && block.pids) || []).forEach(function (pid) {
        counts[pid] = (counts[pid] || 0) + 1;
      });
    });
    var best = 0;
    Object.keys(counts).forEach(function (pid) {
      if (counts[pid] > best) best = counts[pid];
    });
    if (!best) return {pids: [], name: "", probability: null, hit: null, rule: "Majority of the three picks"};
    var tied = [];
    players.forEach(function (player) {
      if (counts[player.pid] === best) tied.push(player);
    });
    if (!tied.length) {
      Object.keys(counts).forEach(function (pid) {
        if (counts[pid] === best) tied.push({pid: Number(pid), name: ""});
      });
    }
    tied.sort(function (a, b) {
      var pa = probabilityOf(a, "model");
      var pb = probabilityOf(b, "model");
      if (pa == null && pb == null) return String(a.name).localeCompare(String(b.name));
      if (pa == null) return 1;
      if (pb == null) return -1;
      if (pb !== pa) return pb - pa;
      return String(a.name).localeCompare(String(b.name));
    });
    var winner = tied[0];
    var same = tied.filter(function (player) {
      return probabilityOf(player, "model") === probabilityOf(winner, "model");
    });
    var pids = same.map(function (player) { return player.pid; });
    return {
      pids: pids,
      name: namesFor(players, pids) || namesFor(tied, pids),
      probability: probabilityOf(winner, "model"),
      hit: hitFromStoredPick(view, methods, pids, hitFromPlayers(players, pids)),
      rule: "Majority of the three picks"
    };
  }

  function chooseMethod(view, players, methodId, methods) {
    var block = blockForMethod(view, methodId);
    var method = null;
    (methods || []).forEach(function (item) {
      if (item.id === methodId) method = item;
    });
    if (!block) {
      return {pids: [], name: "", probability: null, hit: null, rule: method ? method.label : methodId};
    }
    var pids = (block.pids || []).slice();
    var value = null;
    if (typeof block.probability === "number") value = block.probability;
    else if (method && method.kind === "rank" && typeof block.goals_per_game === "number") value = block.goals_per_game;
    return {
      pids: pids,
      name: block.name || namesFor(players, pids),
      probability: typeof block.probability === "number" ? block.probability : null,
      goals_per_game: block.goals_per_game,
      rank: block.rank,
      hit: storedHit(view, methodId, block),
      rule: method ? method.label : methodId,
      valueText: method && method.kind === "rank" && typeof block.goals_per_game === "number"
        ? "#" + (block.rank || 1) + " \u00b7 " + block.goals_per_game.toFixed(2)
        : ""
    };
  }

  function aggregateMix(methods) {
    var mix = defaultMix();
    var rate = "";
    (methods || []).forEach(function (method) {
      if (!method || method.id === "model" || method.id === "custom" || method.id === "aggregate") return;
      if (method.kind === "rank") return;
      if (method.kind === "probability" && !rate) rate = method.id;
    });
    if (rate) mix.lists["1"] = rate;
    mix.phases.playoffs = "model";
    return mix;
  }

  function mixRates(days, config, methods) {
    var mix = copyMix(config);
    var topHits = 0;
    var slots = 0;
    var randomSum = 0;
    var randomN = 0;
    (days || []).forEach(function (day) {
      (day.groups || []).forEach(function (group) {
        if (!group || group.status !== "graded") return;
        if (typeof group.random === "number") {
          randomSum += group.random;
          randomN += 1;
        }
        if (mix.preset) return;
        var chosen = methodForList(mix, group.id, day && day.date, phaseOf(day));
        var block = blockForMethod(group, chosen);
        if (!block && chosen === "model" && typeof group.top3_hits === "number") {
          block = {top3_hits: group.top3_hits};
        }
        if (!block || typeof block.top3_hits !== "number") return;
        var n = Math.min(3, (group.players || []).length);
        if (!n) return;
        topHits += block.top3_hits;
        slots += n;
      });
    });
    return {
      top3_rate: slots ? topHits / slots : null,
      random_baseline: randomN ? randomSum / randomN : null
    };
  }

  function mixFor(methodId, config, methods) {
    if (methodId === "aggregate") return aggregateMix(methods);
    return config;
  }

  function customPick(day, group, config, methods, mode, pending, now) {
    var view = viewOf(day, group, mode);
    var players = (view.players || []).filter(function (player) {
      return eligible(player, pending, now);
    });
    var mix = copyMix(config);
    if (mix.preset === "average") return chooseAverage(view, players, methods);
    if (mix.preset === "majority") return chooseMajority(view, players.length ? players : (view.players || []), methods);
    var methodId = methodForList(mix, group && group.id, day && day.date, phaseOf(day));
    return chooseMethod(view, view.players || [], methodId, methods);
  }

  var SUBMIT_AT = 0.70;

  function configFor(methodId, config, methods) {
    if (methodId === "aggregate") return aggregateMix(methods);
    if (methodId === "custom") return copyMix(config);
    var mix = defaultMix();
    ["1", "2", "3"].forEach(function (id) { mix.lists[id] = methodId; });
    return mix;
  }

  function torontoMinutes(ms) {
    if (ms == null || isNaN(ms)) return null;
    try {
      var text = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/Toronto",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23"
      }).format(new Date(ms));
      var match = String(text).match(/(\d{2}):(\d{2})/);
      if (!match) return null;
      return Number(match[1]) * 60 + Number(match[2]);
    } catch (err) {
      return null;
    }
  }

  function onListAt(player, whenMs) {
    if (!player) return false;
    if (whenMs == null || isNaN(whenMs)) {
      if (player.unavailable_reason === "removed") return false;
      if (player.available === false && !player.game_started && player.unavailable_reason !== "game_started") return false;
      return true;
    }
    if (player.first_seen) {
      var seen = Date.parse(player.first_seen);
      if (!isNaN(seen) && whenMs < seen) return false;
    }
    if (player.removed_at) {
      var left = Date.parse(player.removed_at);
      if (!isNaN(left) && whenMs > left) return false;
    } else if (player.unavailable_reason === "removed") {
      return false;
    }
    if (player.start) {
      var start = Date.parse(player.start);
      if (!isNaN(start) && whenMs >= start) return false;
    }
    return true;
  }

  function methodMetaOf(methods, methodId) {
    var found = null;
    (methods || []).forEach(function (method) {
      if (method && method.id === methodId) found = method;
    });
    return found;
  }

  function methodValue(player, methodId, methods) {
    var method = methodMetaOf(methods, methodId);
    if (method && method.kind === "rank") {
      var rank = player.rank && player.rank[methodId];
      return typeof rank === "number" ? rank : null;
    }
    return probabilityOf(player, methodId);
  }

  function chooseGroup(day, group, config, methods, whenMs) {
    var methodId = methodForList(config, group && group.id, day && day.date, phaseOf(day));
    var method = methodMetaOf(methods, methodId);
    var best = null;
    var tied = [];
    (group.players || []).forEach(function (player) {
      if (!onListAt(player, whenMs)) return;
      var value = methodValue(player, methodId, methods);
      if (value == null) return;
      if (best == null || (method && method.kind === "rank" ? value < best : value > best)) {
        best = value;
        tied = [player];
      } else if (value === best) {
        tied.push(player);
      }
    });
    tied.sort(function (a, b) {
      var an = a.name || "";
      var bn = b.name || "";
      if (an !== bn) return an < bn ? -1 : 1;
      return (a.pid || 0) - (b.pid || 0);
    });
    var pids = tied.map(function (player) { return player.pid; });
    var hit = null;
    if (tied.length && tied.every(function (player) { return typeof player.scored === "number"; })) {
      hit = tied.reduce(function (sum, player) { return sum + player.scored; }, 0) / tied.length;
    }
    var start = null;
    tied.forEach(function (player) {
      if (!player.start) return;
      var ms = Date.parse(player.start);
      if (!isNaN(ms) && (start == null || ms < start)) start = ms;
    });
    var probability = null;
    if (tied.length && !(method && method.kind === "rank")) probability = probabilityOf(tied[0], methodId);
    return {
      groupId: group.id,
      pids: pids,
      name: tied.map(function (player) { return player.name || ""; }).join(" / "),
      probability: probability,
      hit: hit,
      start: start,
      methodId: methodId
    };
  }

  function chanceOf(picks) {
    if (!picks || !picks.length || picks.some(function (pick) { return typeof pick.probability !== "number"; })) return null;
    var miss = 1;
    picks.forEach(function (pick) { miss *= (1 - pick.probability); });
    return 1 - miss;
  }

  function selectionsAt(day, config, methods, whenMs) {
    var picks = [];
    (day.groups || []).forEach(function (group) {
      picks.push(chooseGroup(day, group, config, methods, whenMs));
    });
    return {picks: picks, chance: chanceOf(picks)};
  }

  function earliestStart(picks) {
    var best = null;
    (picks || []).forEach(function (pick) {
      if (pick.start == null) return;
      if (best == null || pick.start < best) best = pick.start;
    });
    return best;
  }

  function checkTimes(day) {
    var times = [];
    function add(iso) {
      if (!iso) return;
      var ms = Date.parse(iso);
      if (!isNaN(ms)) times.push(ms);
    }
    add(day && day.morning && day.morning.at);
    add(day && day.generated_at);
    (day && day.snapshots || []).forEach(function (snap) { add(snap.time); });
    (day && day.groups || []).forEach(function (group) {
      (group.players || []).forEach(function (player) {
        add(player.first_seen);
        if (!player.removed_at) return;
        var left = Date.parse(player.removed_at);
        if (!isNaN(left)) times.push(left + 1);
      });
    });
    times.sort(function (a, b) { return a - b; });
    var uniq = [];
    times.forEach(function (ms) {
      if (!uniq.length || uniq[uniq.length - 1] !== ms) uniq.push(ms);
    });
    if (!uniq.length) uniq.push(null);
    return uniq;
  }

  function dailyPlan(day, config, methods, nowMs) {
    var checks = checkTimes(day || {});
    var playoffs = phaseOf(day) === "playoffs";
    var provisional = null;
    var locked = false;
    var lockAt = null;
    var reason = null;
    var sawFive = false;
    var lastCheck = null;
    checks.forEach(function (ms) {
      if (locked) return;
      if (provisional) {
        var start = earliestStart(provisional.picks);
        if (start != null && (ms == null || start <= ms) && (nowMs == null || start <= nowMs)) {
          locked = true;
          lockAt = start;
          reason = "game";
          return;
        }
      }
      if (nowMs != null && ms != null && ms > nowMs) return;
      var next = selectionsAt(day, config, methods, ms);
      var chance = next.chance;
      lastCheck = ms;
      if (!provisional) {
        provisional = next;
        if (playoffs || (chance != null && chance >= SUBMIT_AT)) {
          locked = true;
          lockAt = ms;
          reason = playoffs ? "playoffs" : "threshold";
        }
        return;
      }
      if (chance != null && chance >= SUBMIT_AT) {
        provisional = next;
        locked = true;
        lockAt = ms;
        reason = "threshold";
        return;
      }
      var mins = torontoMinutes(ms);
      if (mins != null && mins >= 17 * 60 && !sawFive) {
        provisional = next;
        sawFive = true;
      }
    });
    if (!locked && provisional) {
      var start = earliestStart(provisional.picks);
      if (start != null && (nowMs == null || nowMs >= start)) {
        locked = true;
        lockAt = start;
        reason = "game";
      } else if (nowMs == null && day && day.status === "graded") {
        locked = true;
        lockAt = lastCheck;
        reason = "game";
      }
    }
    return {
      picks: provisional ? provisional.picks : [],
      locked: locked,
      at: lockAt,
      reason: reason,
      chance: provisional ? provisional.chance : null
    };
  }

  function groupHit(day, group, methodId, config, methods, mode, pending, now) {
    var plan = dailyPlan(day, configFor(methodId, config, methods), methods, null);
    var pick = null;
    (plan.picks || []).forEach(function (item) {
      if (item.groupId === (group && group.id)) pick = item;
    });
    if (pick && pick.pids && pick.pids.length) return pick.hit;
    if (methodId === "custom" || methodId === "aggregate") {
      var fresh = customPick(day, group, mixFor(methodId, config, methods), methods, mode, pending, now);
      return fresh.hit == null ? null : fresh.hit;
    }
    var view = viewOf(day, group, mode);
    if (view.status && view.status !== "graded" && view.hit == null) {
      var block = blockForMethod(view, methodId);
      if (!block || typeof block.hit !== "number") return null;
    }
    var chosen = blockForMethod(view, methodId);
    if (!chosen && methodId !== "model") return null;
    var hit = storedHit(view, methodId, chosen);
    if (view.status && view.status !== "graded" && (chosen == null || typeof chosen.hit !== "number") && methodId === "model" && view.hit == null) {
      return null;
    }
    return hit;
  }

  function dayRecord(day, methodId, config, methods, mode) {
    var hits = 0;
    var picks = 0;
    (day.groups || []).forEach(function (group) {
      var pending = day.status === "pending" || (group.status === "pending" && group.hit == null);
      var hit = groupHit(day, group, methodId, config, methods, mode, pending && (methodId === "custom" || methodId === "aggregate"), null);
      if (hit == null) return;
      picks += 1;
      hits += hit;
    });
    if (!picks) return null;
    return {hits: hits, picks: picks};
  }

  function computeMetrics(days, methodId, config, methods, phase, mode) {
    var rows = (days || []).filter(function (day) {
      if (!day || !day.date) return false;
      if (phase && phase !== "combined" && phaseOf(day) !== phase) return false;
      return true;
    });
    rows.sort(function (a, b) {
      if (a.date < b.date) return -1;
      if (a.date > b.date) return 1;
      return String(a.season || "").localeCompare(String(b.season || ""));
    });
    var hits = 0;
    var picks = 0;
    var gameDays = 0;
    var daysWithHit = 0;
    var run = 0;
    var streaks = 0;
    rows.forEach(function (day) {
      var record = dayRecord(day, methodId, config, methods, mode);
      if (!record) return;
      gameDays += 1;
      picks += record.picks;
      hits += record.hits;
      if (record.hits > 0) {
        daysWithHit += 1;
        run += 1;
        if (run === 7) {
          streaks += 1;
          run = 0;
        }
      } else {
        run = 0;
      }
    });
    return {
      hit_rate: picks ? hits / picks : null,
      hits: Math.round(hits * 1000) / 1000,
      picks: picks,
      days_with_hit: daysWithHit,
      days: gameDays,
      streaks: streaks
    };
  }

  function normalizeMetrics(row) {
    if (!row || typeof row !== "object") return null;
    if (row.hit_rate == null && row.picks == null && row.streaks == null && row.days_with_hit == null) return null;
    return {
      hit_rate: typeof row.hit_rate === "number" ? row.hit_rate : null,
      hits: row.hits == null ? null : row.hits,
      picks: row.picks == null ? null : row.picks,
      days_with_hit: row.days_with_hit == null ? null : row.days_with_hit,
      days: row.days == null ? null : row.days,
      streaks: row.streaks == null ? null : row.streaks
    };
  }

  function storedMetrics(doc, methodId, phase) {
    if (!doc || methodId === "custom" || methodId === "aggregate") return null;
    var key = phase || "combined";
    var metrics = doc.metrics;
    if (!metrics) return null;
    var direct = metrics[methodId];
    if (direct && typeof direct === "object" && (direct[key] || (key === "combined" && (direct.combined || direct.all)))) {
      return normalizeMetrics(direct[key] || direct.combined || direct.all);
    }
    var byPhase = metrics[key] || (key === "combined" ? metrics.combined || metrics.all : null);
    if (byPhase && byPhase[methodId]) return normalizeMetrics(byPhase[methodId]);
    return null;
  }

  root.HockeyMix = {
    CUSTOM: CUSTOM,
    AGGREGATE: AGGREGATE,
    SUBMIT_AT: SUBMIT_AT,
    aggregateMix: aggregateMix,
    mixRates: mixRates,
    configFor: configFor,
    selectionsAt: selectionsAt,
    dailyPlan: dailyPlan,
    PHASES: PHASES,
    defaultMix: defaultMix,
    copyMix: copyMix,
    serializeMix: serializeMix,
    parseMix: parseMix,
    presetLabel: presetLabel,
    monthOf: monthOf,
    phaseOf: phaseOf,
    methodForList: methodForList,
    hasFullDay: hasFullDay,
    fullDayOf: fullDayOf,
    viewOf: viewOf,
    eligible: eligible,
    playerAverage: playerAverage,
    customPick: customPick,
    groupHit: groupHit,
    dayRecord: dayRecord,
    computeMetrics: computeMetrics,
    storedMetrics: storedMetrics
  };
})(typeof window !== "undefined" ? window : this);
