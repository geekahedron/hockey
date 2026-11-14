/* Public Tims Hockey Challenge page.
   Reads static JSON only (data/today.json, data/season.json, data/days/...).
   A method is {id, label} on the payload. Each player has
   probability: { [id]: number }. "model" is the only method published
   today. Another method is a new entry plus a number under that id;
   the selector, the bars, and the compare table pick it up from the JSON.
   There is no second source and nothing here submits a pick. */
(function () {
  var params = new URLSearchParams(location.search);
  var root = (params.get("data") || "data").replace(/[^a-zA-Z0-9_-]/g, "");
  if (!root) root = "data";

  var state = {
    view: "today",
    method: "model",
    today: null,
    season: null,
    index: null,
    past: null,
    pastDate: null
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
      list.unshift({id: "model", label: "Model"});
    }
    return list;
  }

  function knownMethods() {
    return methodsOf(state.today || state.season || {methods: []});
  }

  function pOf(player, method) {
    if (!player || !player.probability) return null;
    var v = player.probability[method];
    return typeof v === "number" ? v : null;
  }

  function ordered(players, method) {
    return (players || []).slice().sort(function (a, b) {
      var pa = pOf(a, method);
      var pb = pOf(b, method);
      if (pa == null && pb == null) return a.name < b.name ? -1 : 1;
      if (pa == null) return 1;
      if (pb == null) return -1;
      if (pb !== pa) return pb - pa;
      return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
    });
  }

  function bestOf(players, method) {
    var best = null;
    (players || []).forEach(function (p) {
      var v = pOf(p, method);
      if (v != null && (best == null || v > best)) best = v;
    });
    return best;
  }

  function highlighted(player, players, method, mode) {
    if (mode === "past") return !!player.pick;
    var best = bestOf(players, method);
    var v = pOf(player, method);
    if (best == null) return !!player.pick;
    return v === best;
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
    (day.groups || []).forEach(function (group) {
      var pick = group.pick || {};
      var bits = [
        h("div", {class: "ghead"},
          h("h3", {text: "Group " + group.id}),
          mode === "past" || day.status !== "pending"
            ? h("span", {class: "pill " + hitClass(group.hit), text: hitText(group.hit)})
            : null)
      ];
      bits.push(h("div", {class: "who", text: pick.name || "No pick"}));
      bits.push(h("div", {class: "muted small", text: pick.team ? (pick.team + (pick.home ? " vs " : " @ ") + pick.opp) : ""}));
      bits.push(h("div", {class: "pct", text: pct(pick.probability)}));
      wrap.appendChild(h("article", {class: "card"}, bits));
    });
    return wrap;
  }

  function renderPlayer(player, players, method, mode) {
    var value = pOf(player, method);
    var on = highlighted(player, players, method, mode);
    var row = h("div", {class: "row"},
      h("span", {class: "name"},
        player.name,
        on ? " " : null,
        on ? h("span", {class: "pill", text: "Pick"}) : null),
      h("span", {class: "pct", text: pct(value)})
    );
    var meta = h("div", {class: "meta"},
      matchup(player),
      player.position ? " \u00b7 " + player.position : "",
      scoredText(player) ? " \u00b7 " : "",
      scoredText(player) ? h("span", {class: "scored", text: scoredText(player)}) : null
    );
    return h("div", {class: "player" + (on ? " pick" : "")},
      row,
      meta,
      h("div", {class: "bar", title: pct(value)}, h("i", {style: "width:" + barWidth(value)}))
    );
  }

  function renderGroups(day, mode) {
    var grid = h("div", {class: "groups"});
    (day.groups || []).forEach(function (group) {
      var players = ordered(group.players, state.method);
      var head = h("div", {class: "ghead"},
        h("h3", {text: "Group " + group.id}),
        h("span", {class: "pill " + hitClass(group.hit), text: mode === "today" && day.status === "pending" ? (group.players || []).length + " players" : hitText(group.hit)})
      );
      var cardKids = [head];
      if (group.pick) {
        cardKids.push(h("p", {class: "pickline", text: "Pick: " + group.pick.name + " \u00b7 " + pct(group.pick.probability)}));
      }
      players.forEach(function (player) {
        cardKids.push(renderPlayer(player, players, state.method, mode));
      });
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
    var methods = methodsOf(day);
    var placeholder = methods.length < 2;
    var head = [h("th", {text: "Group"}), h("th", {text: "Player"}), h("th", {text: "Team"})];
    methods.forEach(function (method) { head.push(h("th", {text: method.label})); });
    if (placeholder) head.push(h("th", {class: "placeholder", text: "Next method"}));
    var body = document.createElement("tbody");
    (day.groups || []).forEach(function (group) {
      var players = ordered(group.players, state.method);
      var best = {};
      methods.forEach(function (method) { best[method.id] = bestOf(players, method.id); });
      players.forEach(function (player) {
        var cells = [
          h("td", {text: String(group.id)}),
          h("td", {class: "player-name", text: player.name}),
          h("td", {text: player.team + (player.home ? " vs " : " @ ") + player.opp})
        ];
        methods.forEach(function (method) {
          var v = pOf(player, method.id);
          var mark = v != null && v === best[method.id];
          cells.push(h("td", {class: mark ? "ok" : "", text: pct(v)}));
        });
        if (placeholder) cells.push(h("td", {class: "placeholder", text: "\u2014"}));
        var tr = h("tr", {class: player.pick ? "pick" : ""}, cells);
        body.appendChild(tr);
      });
    });
    var note = placeholder
      ? "Side-by-side is ready for another method. It will add a probability column next to Model. Only Model is published today."
      : "Each column is one method. The highlighted row is the published pick.";
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
    view.appendChild(renderSummary(day, "today"));
    view.appendChild(h("div", {style: "height:12px"}));
    view.appendChild(renderGroups(day, "today"));
    view.appendChild(renderCompare(day));
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
    var list = h("div", {class: "dates"});
    dates.forEach(function (row) {
      var label = pretty(row.date);
      if (row.picks) label += " \u00b7 " + row.hits + "/" + row.picks;
      else label += " \u00b7 pending";
      var btn = h("button", {
        type: "button",
        class: "ghost" + (row.date === state.pastDate ? " on" : ""),
        text: label,
        onclick: function () { selectPast(row.date); }
      });
      list.appendChild(btn);
    });
    view.appendChild(h("section", {class: "card"},
      h("h2", {text: "Past days"}),
      h("p", {class: "muted small", text: "The pick is the one published that morning. Players who scored are marked."}),
      tools,
      list));
    if (!state.past) {
      view.appendChild(h("p", {class: "muted", text: dates.length ? "Pick a date." : "No days published yet."}));
      return;
    }
    var day = state.past;
    view.appendChild(h("div", {class: "dayhead"},
      h("h2", {text: pretty(day.date)}),
      h("p", {class: "muted", text: statusLine(day)})));
    view.appendChild(renderSummary(day, "past"));
    view.appendChild(h("div", {style: "height:12px"}));
    view.appendChild(renderGroups(day, "past"));
  }

  function chart(days) {
    var pts = (days || []).filter(function (d) {
      return d.picks > 0 && typeof d.running_hit_rate === "number";
    });
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 680 240");
    svg.setAttribute("role", "img");
    if (!pts.length) {
      svg.setAttribute("aria-label", "No graded days yet");
      return svg;
    }
    var last = pts[pts.length - 1];
    svg.setAttribute("aria-label",
      "Running hit rate " + pct(last.running_hit_rate) +
      ", random baseline " + pct(last.running_random));
    var w = 680, h = 240;
    var pad = {l: 42, r: 16, t: 16, b: 32};
    var innerW = w - pad.l - pad.r;
    var innerH = h - pad.t - pad.b;
    function x(i) {
      if (pts.length === 1) return pad.l + innerW / 2;
      return pad.l + (innerW * i) / (pts.length - 1);
    }
    function y(v) {
      var clamped = Math.max(0, Math.min(1, v || 0));
      return pad.t + innerH * (1 - clamped);
    }
    function el(name, attrs) {
      var node = document.createElementNS("http://www.w3.org/2000/svg", name);
      Object.keys(attrs).forEach(function (key) { node.setAttribute(key, attrs[key]); });
      return node;
    }
    [0, 0.25, 0.5, 0.75, 1].forEach(function (tick) {
      svg.appendChild(el("line", {
        x1: pad.l, x2: w - pad.r, y1: y(tick), y2: y(tick),
        stroke: "#24467d", "stroke-width": "1"
      }));
      svg.appendChild(el("text", {
        x: 4, y: y(tick) + 4, fill: "#9fb0cc", "font-size": "11",
        "font-family": "system-ui, sans-serif"
      }));
      svg.lastChild.textContent = Math.round(tick * 100) + "%";
    });
    function path(key) {
      return pts.map(function (d, i) {
        var v = d[key];
        if (typeof v !== "number") return null;
        return (i === 0 ? "M" : "L") + x(i).toFixed(1) + " " + y(v).toFixed(1);
      }).filter(Boolean).join(" ");
    }
    svg.appendChild(el("path", {
      d: path("running_random"), fill: "none", stroke: "#9fb0cc",
      "stroke-width": "2", "stroke-dasharray": "4 4"
    }));
    svg.appendChild(el("path", {
      d: path("running_hit_rate"), fill: "none", stroke: "#ff8c1a", "stroke-width": "2.5"
    }));
    pts.forEach(function (d, i) {
      svg.appendChild(el("circle", {
        cx: x(i).toFixed(1), cy: y(d.running_hit_rate).toFixed(1), r: "3.5", fill: "#ff8c1a"
      }));
    });
    [0, Math.floor((pts.length - 1) / 2), pts.length - 1].forEach(function (i) {
      if (pts.length > 1 && i === Math.floor((pts.length - 1) / 2) && pts.length < 3) return;
      var label = el("text", {
        x: x(i), y: h - 8, fill: "#9fb0cc", "font-size": "11",
        "text-anchor": i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle",
        "font-family": "system-ui, sans-serif"
      });
      label.textContent = pts[i].date.slice(5);
      svg.appendChild(label);
    });
    return svg;
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
    var sum = season.summary || {};
    var hits = sum.hits == null ? "\u2014" : (Math.round(sum.hits * 1000) / 1000);
    view.appendChild(h("section", {class: "card"},
      h("div", {class: "dayhead"},
        h("h2", {text: (season.season || "Season") + " tracker"}),
        h("p", {class: "muted", text: "Running results for the Model pick."})),
      h("div", {class: "stats"},
        h("div", {class: "stat"}, h("b", {text: pct(sum.hit_rate)}), h("span", {text: "Hit rate"})),
        h("div", {class: "stat"}, h("b", {text: hits + " / " + (sum.picks || 0)}), h("span", {text: "Picks hit"})),
        h("div", {class: "stat"}, h("b", {text: pct(sum.top3_rate)}), h("span", {text: "Top 3 scored"})),
        h("div", {class: "stat"}, h("b", {text: pct(sum.random_baseline)}), h("span", {text: "Random baseline"}))
      ),
      h("div", {class: "chart-wrap"}, chart(season.days)),
      h("div", {class: "legend"},
        h("span", null, h("i", {class: "swatch model"}), "Running hit rate"),
        h("span", null, h("i", {class: "swatch random"}), "Random baseline"))
    ));

    var body = document.createElement("tbody");
    (season.days || []).forEach(function (day) {
      (day.groups || []).forEach(function (group) {
        body.appendChild(h("tr", null,
          h("td", {text: pretty(day.date)}),
          h("td", {text: String(group.id)}),
          h("td", {class: "player-name", text: group.pick || "\u2014"}),
          h("td", {text: pct(group.probability)}),
          h("td", {class: hitClass(group.hit) === "hit" ? "ok" : "muted", text: hitText(group.hit)}),
          h("td", {text: group.top3_hits == null ? "\u2014" : String(group.top3_hits)}),
          h("td", {text: pct(group.random)}),
          h("td", {text: pct(day.running_hit_rate)})
        ));
      });
    });
    view.appendChild(h("section", {class: "card"},
      h("h2", {text: "Every pick"}),
      h("div", {class: "tablewrap"},
        h("table", {class: "data"},
          h("thead", null, h("tr", null,
            h("th", {text: "Date"}),
            h("th", {text: "Group"}),
            h("th", {text: "Pick"}),
            h("th", {text: "Probability"}),
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
    load("days/" + iso + ".json").then(function (day) {
      state.past = day;
      if (state.view === "past") renderPast();
    }).catch(function () {
      state.past = null;
      setBanner("No published file for " + iso + ".");
      if (state.view === "past") renderPast();
    });
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
    window.addEventListener("hashchange", function () {
      var next = (location.hash || "").replace("#", "");
      if (views.indexOf(next) !== -1 && next !== state.view) show(next);
    });
    Promise.all([
      load("today.json").catch(function () { return null; }),
      load("season.json").catch(function () { return null; }),
      load("days/index.json").catch(function () { return null; })
    ]).then(function (all) {
      state.today = all[0];
      state.season = all[1];
      state.index = all[2];
      fillMethodSelect();
      if (!state.today && !state.season) {
        setBanner("No published JSON in " + root + "/ yet.");
      }
      var graded = ((state.index && state.index.days) || []).filter(function (row) {
        return row.status === "graded" || row.status === "partial";
      });
      var first = graded[0] || ((state.index && state.index.days) || [])[0];
      if (first) state.pastDate = first.date;
      show(state.view);
      if (state.pastDate) selectPast(state.pastDate);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else boot();
})();
