/* linguaoriginale: small enhancements on top of static pages.
   Pages work without this file: every day is listed in the HTML.
   The words come from the page (<script id="l10n">), so the same file serves /it/ and /en/. */
(function () {
  "use strict";
  var H = document.documentElement, BASE = H.getAttribute("data-base") || "/", TZ = "Europe/Rome";
  var LANG = (H.getAttribute("lang") || "it").slice(0, 2), PRE = BASE + LANG + "/";
  var L = {};
  try { L = JSON.parse(document.getElementById("l10n").textContent); } catch (e) { /* no words: nothing below needs them before use */ }
  var DAYP = LANG === "it" ? "giorno" : "day";
  var NOW = Date.now();
  var fmtKey = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
  var fmtTime = new Intl.DateTimeFormat("it-IT", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
  var key = function (t) { return fmtKey.format(new Date(t)); };
  var TODAY = key(NOW), TOMORROW = key(NOW + 864e5);
  var $ = function (sel, el) { return (el || document).querySelector(sel); };
  var $$ = function (sel, el) { return Array.prototype.slice.call((el || document).querySelectorAll(sel)); };
  var esc = function (s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  var cap = function (s) { return s.charAt(0).toUpperCase() + s.slice(1); };
  var fill = function (s, o) { return String(s).replace(/\{(\w+)\}/g, function (_, k) { return o[k] !== undefined ? o[k] : ""; }); };
  var n = function (num, word) { var w = L[word] || [word, word]; return num + " " + (num === 1 ? w[0] : w[1]); };
  function store(k, v) { try { if (v === undefined) return sessionStorage.getItem(k); sessionStorage.setItem(k, v); } catch (e) { return null; } }
  function dayOf(k) { var d = new Date(k + "T12:00:00Z"); return { wd: (d.getUTCDay() + 6) % 7, d: d.getUTCDate(), m: d.getUTCMonth() }; }  // wd: 0 = Monday
  function wdName(k) { return L.wd[dayOf(k).wd]; }
  /* "Oggi" / "Domani" / "Venerdì" (it), "Today" / "Tomorrow" / "Friday" (en), for the start of a sentence */
  function dayWord(k) { return k === TODAY ? L.today : k === TOMORROW ? L.tomorrow : cap(wdName(k)); }
  /* inside a sentence: "oggi" / "domani" / "lunedì" (it), "today" / "tomorrow" / "on Monday" (en) */
  function dayInSentence(k) { return k === TODAY ? L.todayL : k === TOMORROW ? L.tomorrowL : (LANG === "en" ? "on " : "") + wdName(k); }
  function longDay(k) { var x = dayOf(k); return cap(L.wd[x.wd]) + " " + x.d + " " + L.months[x.m]; }
  function fmtKm(d) { return d < 1 ? Math.round(d * 20) * 50 + " m" : (LANG === "it" ? d.toFixed(1).replace(".", ",") : d.toFixed(1)) + " km"; }
  function dist(a, b) {
    var r = Math.PI / 180, dl = (b[0] - a[0]) * r, dn = (b[1] - a[1]) * r;
    var h = Math.pow(Math.sin(dl / 2), 2) + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.pow(Math.sin(dn / 2), 2);
    return 12742 * Math.asin(Math.sqrt(h));
  }

  /* posters that fail to load become the dark title tile */
  document.addEventListener("error", function (e) {
    var el = e.target;
    if (el.tagName !== "IMG") return;
    var ph = el.parentElement && el.parentElement.querySelector(".ph");
    if (ph) { ph.hidden = false; el.remove(); }
  }, true);

  /* 1. screenings that have started are not shown; empty rows and cards go too */
  $$(".chip[data-t]").forEach(function (a) { if (+a.getAttribute("data-t") * 60000 < NOW) a.remove(); });
  $$(".cinrow, .frow").forEach(function (r) { if (!$(".chip", r)) r.remove(); });
  $$("[data-card]").forEach(function (c) { if (!$(".cinrow, .frow", c)) c.remove(); });

  /* 2. the updated line */
  $$("[data-upd]").forEach(function (el) {
    var t = new Date(el.getAttribute("data-upd")).getTime();
    if (isNaN(t)) return;
    var k = key(t), x = dayOf(k);
    var when = k === TODAY ? L.todayL : k === key(NOW - 864e5) ? L.yesterdayL : fill(L.on_date, { d: x.d, m: L.months[x.m] });
    if (NOW - t > 30 * 36e5) { el.classList.add("stale"); el.textContent = fill(L.stale, { when: when }); }
    else el.textContent = fill(L.updated, { when: when, time: fmtTime.format(new Date(t)) });
  });

  /* 3. day strip */
  var strip = $("[data-strip]"), list = $("[data-days]");
  if (strip && list) {
    var blocks = $$("[data-dayblock]", list), btns = $$(".day", strip), info = {};
    blocks.forEach(function (b) {
      var k = b.getAttribute("data-dayblock"), num = $(".v-film", b) ? $$(".v-film .chip", b).length : $$(".chip", b).length;
      info[k] = { block: b, n: num };
      var dn = $(".dayn", b); if (dn) dn.textContent = " · " + n(num, "show");
    });
    btns.forEach(function (bt) {
      var k = bt.getAttribute("data-day"), i = info[k];
      if (k < TODAY) { bt.remove(); if (i) i.block.remove(); delete info[k]; return; }
      $(".dw", bt).textContent = k === TODAY ? L.today : (k === TOMORROW && LANG === "it") ? L.tomorrow : L.wds[dayOf(k).wd];
      bt.disabled = false; // an empty day can still be picked: it says so and offers the next one
      bt.classList.toggle("empty", !i || !i.n);
      bt.setAttribute("aria-label", longDay(k) + ": " + n(i ? i.n : 0, "show"));
      bt.addEventListener("click", function () { select(k, true); });
    });
    var keys = Object.keys(info).sort();
    var nextFull = function (k) { return keys.filter(function (x) { return x > k && info[x].n; })[0]; };
    var lead = $("[data-lead]"), where = list.getAttribute("data-where") || "";
    var select = function (k, user) {
      keys.forEach(function (x) { info[x].block.classList.toggle("on", x === k); });
      btns.forEach(function (bt) { bt.setAttribute("aria-pressed", bt.getAttribute("data-day") === k ? "true" : "false"); });
      var b = info[k].block, box = $("[data-empty]", b);
      if (box) {
        box.hidden = !!info[k].n;
        var p = $(".subt", box);
        if (p) p.innerHTML = fill(L.empty, { Day: esc(dayWord(k)), day: esc(dayInSentence(k)), where: esc(where) });
        var go = $("[data-goto]", box), nx = nextFull(k);
        if (go) {
          go.hidden = !nx;
          if (nx) { go.textContent = fill(L.go_to, { day: nx === TOMORROW ? L.tomorrowL : wdName(nx) + " " + dayOf(nx).d }); go.onclick = function () { select(nx, true); }; }
        }
      }
      if (lead) {
        var films = $$(".v-film [data-card]", b).length, cins = $$(".v-cin [data-card]", b).length;
        var times = $$(".v-film .chip", b).map(function (a) { return a.textContent; }).sort();
        lead.innerHTML = info[k].n ? fill(L.lead, { Day: esc(dayWord(k)), films: n(films, "film"), cinemas: n(cins, "cinema"), time: times[0] })
          : fill(L.lead_none, { Day: esc(dayWord(k)) });
      }
      if (user) {
        try { var u = new URL(location.href); if (k === keys[0]) u.searchParams.delete(DAYP); else u.searchParams.set(DAYP, k); history.replaceState(null, "", u); } catch (e) { /* old browser */ }
        if (strip.getBoundingClientRect().top <= 1) window.scrollTo({ top: list.getBoundingClientRect().top + window.pageYOffset - strip.offsetHeight - 8 });
      }
    };
    var want = null;
    try { var sp = new URL(location.href).searchParams; want = sp.get(DAYP) || sp.get("giorno") || sp.get("day"); } catch (e) { /* ignore */ }
    var first = (want && info[want]) ? want : (keys.filter(function (x) { return info[x].n; })[0] || keys[0]);
    if (first) select(first, false);
  }

  /* 4. by film / by cinema */
  function setView(v) {
    if (!list) return;
    list.classList.toggle("view-cin", v === "cin");
    $$("[data-view]").forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-view") === v ? "true" : "false"); });
  }
  $$("[data-view]").forEach(function (bt) {
    bt.addEventListener("click", function () { setView(bt.getAttribute("data-view")); store("view", bt.getAttribute("data-view")); });
  });
  if ($("[data-view]") && store("view") === "cin") setView("cin");

  /* 5. "show more" in long lists */
  $$("[data-more]").forEach(function (bt) {
    bt.addEventListener("click", function () { $$("[data-extra]", bt.parentElement).forEach(function (r) { r.hidden = false; }); bt.remove(); });
  });

  /* 6. location: asked only on a tap, kept for this visit only */
  function getPos(ok, fail) {
    var s = store("pos");
    if (s) { try { return ok(JSON.parse(s)); } catch (e) { /* ignore */ } }
    if (!navigator.geolocation) return fail("unsupported");
    navigator.geolocation.getCurrentPosition(function (p) {
      var pos = [p.coords.latitude, p.coords.longitude];
      store("pos", JSON.stringify(pos)); ok(pos);
    }, function (err) { fail(err && err.code === 1 ? "denied" : "error"); }, { enableHighAccuracy: false, timeout: 12000, maximumAge: 600000 });
  }
  function sortBy(parent, items, before) {
    items.sort(function (a, b) { return (+a.getAttribute("data-km") || 1e6) - (+b.getAttribute("data-km") || 1e6); });
    items.forEach(function (el) { parent.insertBefore(el, before || null); });
  }
  function applyDist(pos) {
    $$("[data-lat]").forEach(function (el) {
      var d = dist(pos, [+el.getAttribute("data-lat"), +el.getAttribute("data-lon")]);
      el.setAttribute("data-km", d.toFixed(3));
      var t = $("[data-dist]", el); if (t) t.textContent = fmtKm(d);
    });
    $$(".card.film").forEach(function (c) { sortBy(c, $$(":scope > .cinrow", c), $(":scope > .more", c)); });
    $$(".v-cin").forEach(function (v) { sortBy(v, $$(":scope > .card.cin", v)); });
    $$(".daylist .card.rows").forEach(function (v) { sortBy(v, $$(":scope > .cinrow", v)); });
    $$("[data-sort]").forEach(function (v) { sortBy(v, $$(":scope > .lrow", v)); });
    $$("[data-locate]").forEach(function (b) { if (!b.closest("[data-near-home],[data-near-film]")) { b.textContent = L.sorted; b.disabled = true; } });
  }
  if (store("pos")) { try { applyDist(JSON.parse(store("pos"))); } catch (e) { /* ignore */ } }
  $$("[data-locate]").forEach(function (b) {
    if (b.closest("[data-near-home],[data-near-film]")) return;
    b.addEventListener("click", function () {
      b.disabled = true;
      getPos(applyDist, function () { b.disabled = false; b.textContent = L.no_pos; });
    });
  });

  /* 7. the data file, loaded only for search and "near me" */
  var dataP = null;
  function loadData() {
    if (!dataP) dataP = fetch(PRE + "data.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (D) {
      D.sh = D.shows.map(function (s) { return { c: s[0], f: s[1], t: s[2] * 60000, u: s[3] }; }).filter(function (s) { return s.t >= NOW; });
      D.cityUrl = function (i) { return PRE + D.cities[i][1] + "/"; };
      D.cinUrl = function (ci) { var c = D.cinemas[ci]; return PRE + D.cities[c[1]][1] + "/" + c[2] + "/"; };
      D.filmUrl = function (fi, city) { return PRE + "film/" + D.films[fi][6] + "/" + (city !== undefined ? D.cities[city][1] + "/" : ""); };
      return D;
    });
    return dataP;
  }
  var CHEV = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';
  function whenShort(t) { var k = key(t); return (k === TODAY ? "" : k === TOMORROW ? L.tomorrowL + " " : L.wds[dayOf(k).wd].toLowerCase() + " " + dayOf(k).d + " ") + fmtTime.format(new Date(t)); }
  function cinemaDist(D, pos) { return D.cinemas.map(function (c) { return c[4] == null ? Infinity : dist(pos, [c[4], c[5]]); }); }
  function nearFail(out, why) {
    out.hidden = false;
    out.innerHTML = why === "denied" ? "<h3>" + esc(L.denied_h) + "</h3><p class=hint>" + esc(L.denied_p) + "</p>"
      : "<h3>" + esc(L.err_h) + "</h3><p class=hint>" + esc(L.err_p) + "</p>";
  }

  /* 7a. homepage: what's on near me */
  var nh = $("[data-near-home]");
  if (nh) {
    var nhOut = $("[data-near-out]", nh), nhBtn = $("[data-locate]", nh);
    nhBtn.addEventListener("click", function () {
      nhBtn.disabled = true;
      getPos(function (pos) {
        loadData().then(function (D) {
          var cd = cinemaDist(D, pos), best = Math.min.apply(null, cd), city;
          nhBtn.hidden = true; nhOut.hidden = false;
          if (!isFinite(best) || best > 40) {
            var ci = isFinite(best) ? cd.indexOf(best) : 0;
            city = D.cinemas[ci][1];
            nhOut.innerHTML = "<h3>" + esc(L.far_h) + "</h3><p class=hint>" + esc(fill(L.far_p, { city: D.cities[city][0], km: Math.round(best) })) + "</p>"
              + '<a class="btn-y" href="' + D.cityUrl(city) + '">' + esc(fill(L.see, { city: D.cities[city][0] })) + "</a>"
              + '<a class="more" href="mailto:ciao@linguaoriginale.com?subject=' + encodeURIComponent(L.missing_subject) + '">' + esc(L.missing) + "</a>";
            return;
          }
          var radius = Math.max(5, best * 2.5);
          var near = D.sh.filter(function (s) { return cd[s.c] <= radius; });
          city = D.cinemas[cd.indexOf(best)][1];
          var ks = [TODAY, TOMORROW, ""];
          var render = function (ix) {
            var k = ks[ix], rows = near.filter(function (s) { return !k || key(s.t) === k; }).slice(0, 8);
            nhOut.innerHTML = "<h3>" + esc(L.near_h[ix]) + "</h3>"
              + '<div class="tabs" role="group" aria-label="' + esc(L.when_label) + '">' + L.tabs.map(function (t, i) { return '<button type="button" data-ix="' + i + '" aria-pressed="' + (i === ix) + '">' + esc(t) + "</button>"; }).join("") + "</div>"
              + (rows.length ? rows.map(function (s) {
                var f = D.films[s.f], c = D.cinemas[s.c];
                return '<a class="nrow" href="' + D.filmUrl(s.f, c[1]) + '"><span class="t">' + (k ? fmtTime.format(new Date(s.t)) : esc(whenShort(s.t))) + '</span><span class="w"><b>' + esc(f[0]) + "</b><span>" + esc(f[5]) + "</span><span>" + esc(c[0]) + " · " + fmtKm(cd[s.c]) + "</span></span>" + CHEV + "</a>";
              }).join("") : '<p class="hint">' + esc(L.near_none[ix]) + "</p>")
              + '<a class="more" href="' + D.cityUrl(city) + (k && k !== TODAY ? "?" + DAYP + "=" + k : "") + '">' + esc(fill(L.all_in[ix], { city: D.cities[city][0] })) + "</a>";
            $$(".tabs button", nhOut).forEach(function (b) { b.addEventListener("click", function () { render(+b.getAttribute("data-ix")); }); });
          };
          render(near.some(function (s) { return key(s.t) === TODAY; }) ? 0 : near.some(function (s) { return key(s.t) === TOMORROW; }) ? 1 : 2);
        }).catch(function () { nhBtn.disabled = false; nearFail(nhOut, "error"); });
      }, function (why) { nhBtn.disabled = false; nearFail(nhOut, why); });
    });
  }

  /* 7b. film page: the nearest cinemas showing it */
  var nf = $("[data-near-film]");
  if (nf) {
    var nfOut = $("[data-near-out]", nf), nfBtn = $("[data-locate]", nf), fid = nf.getAttribute("data-near-film");
    nfBtn.addEventListener("click", function () {
      nfBtn.disabled = true;
      getPos(function (pos) {
        loadData().then(function (D) {
          var fi = -1, cd = cinemaDist(D, pos), seen = {}, rows = [];
          D.films.forEach(function (f, i) { if (f[6] === fid) fi = i; });
          D.sh.forEach(function (s) { if (s.f === fi && !seen[s.c]) { seen[s.c] = 1; rows.push(s); } });
          rows.sort(function (a, b) { return cd[a.c] - cd[b.c]; });
          nfBtn.hidden = true; nfOut.hidden = false;
          nfOut.innerHTML = rows.slice(0, 3).map(function (s) {
            var c = D.cinemas[s.c];
            return '<div class="cinrow"><div class="row-top"><a class="row-name" href="' + D.cinUrl(s.c) + '">' + esc(c[0]) + '</a><span class="dist">' + esc(D.cities[c[1]][0]) + (isFinite(cd[s.c]) ? " · " + fmtKm(cd[s.c]) : "") + "</span></div>"
              + '<div class="chips"><a class="chip" href="' + esc(s.u) + '" target="_blank" rel="noopener">' + esc(whenShort(s.t)) + "</a></div></div>";
          }).join("") || '<p class="hint">' + esc(L.no_shows) + "</p>";
        }).catch(function () { nfBtn.disabled = false; nearFail(nfOut, "error"); });
      }, function (why) { nfBtn.disabled = false; nearFail(nfOut, why); });
    });
  }

  /* 8. search */
  var dlg = $("#search"), q = $("#q"), res = $("#results"), IDX = null, D0 = null, opts = [], active = -1;
  var norm = function (s) { return String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim(); };
  var STOP = { a: 1, "in": 1, di: 1, da: 1, al: 1, il: 1, la: 1, lo: 1, le: 1, the: 1, of: 1, at: 1, e: 1, and: 1, vo: 1, vos: 1, ov: 1, versione: 1, originale: 1, original: 1, lingua: 1, language: 1, version: 1, film: 1, films: 1, movie: 1, movies: 1, cinema: 1, cinemas: 1, orari: 1, showtimes: 1, stasera: 1, tonight: 1, oggi: 1, today: 1, english: 1, inglese: 1 };
  function lev(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    var prev = [], i, j; for (j = 0; j <= b.length; j++) prev[j] = j;
    for (i = 1; i <= a.length; i++) {
      var cur = [i], rowMin = i;
      for (j = 1; j <= b.length; j++) { cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)); rowMin = Math.min(rowMin, cur[j]); }
      if (rowMin > max) return max + 1;
      prev = cur;
    }
    return prev[b.length];
  }
  function tokScore(t, words) {
    var best = 0, maxEd = t.length >= 7 ? 2 : t.length >= 4 ? 1 : 0;
    for (var i = 0; i < words.length; i++) {
      var w = words[i];
      if (w === t) return 3;
      if (w.indexOf(t) === 0) best = Math.max(best, 2 + t.length / (w.length * 10));
      else if (t.length >= 3 && w.indexOf(t) > 0) best = Math.max(best, 1.2);
      else if (maxEd && best < 1) {
        var d = Math.min(lev(t, w, maxEd), w.length > t.length ? lev(t, w.slice(0, t.length), maxEd) : 99);
        if (d <= maxEd) best = Math.max(best, 1 - d * 0.2);
      }
    }
    return best;
  }
  function buildIdx(D) {
    var I = [], perCity = {}, perCin = {}, perFilm = {};
    D.sh.forEach(function (s) {
      var city = D.cinemas[s.c][1];
      (perCity[city] = perCity[city] || []).push(s); (perCin[s.c] = perCin[s.c] || []).push(s); (perFilm[s.f] = perFilm[s.f] || []).push(s);
    });
    D.cities.forEach(function (c, i) {
      var sh = perCity[i] || []; if (!sh.length) return;
      var cins = {}; sh.forEach(function (s) { cins[s.c] = 1; });
      I.push({ type: "city", city: i, label: c[0], sub: n(Object.keys(cins).length, "cinema") + " · " + n(sh.length, "show"), href: D.cityUrl(i), words: norm(c[0] + " " + c[2]).split(" "), w: 0.6 });
    });
    D.cinemas.forEach(function (c, i) {
      var sh = perCin[i] || [], fs = {}; sh.forEach(function (s) { fs[s.f] = 1; });
      I.push({ type: "cinema", city: c[1], label: c[0], sub: [D.cities[c[1]][0], c[3], sh.length ? n(Object.keys(fs).length, "film") : L.no_films].filter(Boolean).join(" · "), href: D.cinUrl(i), words: norm(c[0] + " " + c[3]).split(" "), name: norm(c[0]).split(" "), w: sh.length ? 0.3 : -0.4 });
    });
    D.films.forEach(function (f, i) {
      var sh = perFilm[i] || []; if (!sh.length) return;
      var cities = {}; sh.forEach(function (s) { cities[D.cinemas[s.c][1]] = 1; });
      I.push({ type: "film", fi: i, label: f[0], cities: cities, n: sh, words: norm([f[0], f[2], f[3], f[4], f[5]].join(" ")).split(" "), w: Math.min(0.4, Math.log(sh.length + 1) / Math.LN10 / 4) });
    });
    return I;
  }
  function cityFromToken(D, t) {
    for (var i = 0; i < D.cities.length; i++) if (norm(D.cities[i][0]) === t || norm(D.cities[i][2]) === t) return i;
    return -1;
  }
  function search(D, raw) {
    var qt = norm(raw).split(" ").filter(Boolean); if (!qt.length) return null;
    var city = -1;
    var toks = qt.filter(function (t) { if (qt.length > 1 && city < 0) { var c = cityFromToken(D, t); if (c >= 0) { city = c; return false; } } return true; });
    var m = toks.filter(function (t) { return !STOP[t]; }); if (m.length) toks = m;
    if (!toks.length && city >= 0) toks = [norm(D.cities[city][0])];
    var out = [];
    IDX.forEach(function (e) {
      if (city >= 0 && (e.type === "city" || (e.type === "cinema" && e.city !== city) || (e.type === "film" && !e.cities[city]))) return;
      var sum = 0;
      for (var i = 0; i < toks.length; i++) { var s = tokScore(toks[i], e.words); if (!s) return; sum += s; }
      if (e.name && toks.some(function (t) { return e.name.indexOf(t) >= 0; })) sum += 0.5 * toks.length;  // "barberini": the cinema called so beats the one in the Barberini area
      out.push({ e: e, s: sum / toks.length + e.w });
    });
    out.sort(function (a, b) { return b.s - a.s; });
    var groups = { city: [], cinema: [], film: [] }, lim = { city: 3, cinema: 5, film: 8 };
    out.forEach(function (r) { if (groups[r.e.type].length < lim[r.e.type]) groups[r.e.type].push(r); });
    var order = Object.keys(groups).filter(function (k) { return groups[k].length; }).sort(function (a, b) { return groups[b][0].s - groups[a][0].s; });
    return { city: city, toks: toks, order: order, groups: groups };
  }
  function filmSub(D, e, city) {
    var sh = city >= 0 ? e.n.filter(function (s) { return D.cinemas[s.c][1] === city; }) : e.n, cins = {}, cities = {};
    sh.forEach(function (s) { cins[s.c] = 1; cities[D.cities[D.cinemas[s.c][1]][0]] = 1; });
    var ck = Object.keys(cins), f = D.films[e.fi];
    var where = ck.length === 1 ? D.cinemas[ck[0]][0] : n(ck.length, "cinema");
    if (city < 0) where += ", " + Object.keys(cities).join(", ");
    return [f[5], where, fill(L.next, { when: whenShort(sh[0].t) })].join(" · ");
  }
  function render() {
    if (!IDX) return;
    var v = q.value, r;
    if (v.trim()) r = search(D0, v);
    else {
      var films = IDX.filter(function (e) { return e.type === "film"; }).sort(function (a, b) { return b.n.length - a.n.length; }).slice(0, 5);
      r = { city: -1, toks: [], order: ["city", "film"], groups: { city: IDX.filter(function (e) { return e.type === "city"; }).slice(0, 6).map(function (e) { return { e: e }; }), film: films.map(function (e) { return { e: e }; }), cinema: [] }, suggest: true };
    }
    opts = []; active = -1;
    var h = "";
    if (r.city >= 0) h += '<div class="grp">' + esc(fill(L.results_in, { city: D0.cities[r.city][0] })) + "</div>";
    if (!r.order.length) h += '<div class="empty">' + esc(fill(L.no_results, { q: v.trim() })) + "</div>";
    r.order.forEach(function (k) {
      h += '<div class="grp">' + esc(r.suggest && k === "film" ? L.top : L.groups[k]) + "</div>";
      r.groups[k].forEach(function (x) {
        var e = x.e, oneCity = e.type === "film" && Object.keys(e.cities).length === 1 ? +Object.keys(e.cities)[0] : undefined;
        var href = e.type === "film" ? D0.filmUrl(e.fi, r.city >= 0 ? r.city : oneCity) : e.href;
        var sub = e.type === "film" ? filmSub(D0, e, r.city) : e.sub, i = opts.length, f = e.type === "film" ? D0.films[e.fi] : null;
        opts.push(href);
        var ic = f && f[7] ? '<img class="ic" src="' + esc(f[7]) + '" alt="" loading="lazy">' : '<span class="ic' + (e.type === "film" ? "" : " round") + '" aria-hidden="true">' + (e.type === "city" ? "C" : e.type === "cinema" ? "S" : "F") + "</span>";
        h += '<a class="opt" role="option" id="opt' + i + '" href="' + esc(href) + '" aria-selected="false">' + ic + '<span class="tx"><span class="lb">' + mark(e.label, r.toks) + '</span><span class="sb">' + esc(sub) + "</span></span></a>";
      });
    });
    res.innerHTML = h;
    q.setAttribute("aria-expanded", "true");
  }
  function mark(label, toks) {
    var nn = label.split("").map(function (ch) { return (norm(ch) || " ")[0]; }).join("");
    if (nn.length !== label.length || !toks.length) return esc(label);
    var marks = [];
    toks.forEach(function (t) { var re = new RegExp("(^|[^a-z0-9])(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "g"), m; while ((m = re.exec(nn))) marks.push([m.index + m[1].length, m.index + m[1].length + t.length]); });
    marks.sort(function (a, b) { return a[0] - b[0]; });
    var out = "", pos = 0;
    marks.forEach(function (m) { if (m[0] < pos) return; out += esc(label.slice(pos, m[0])) + "<mark>" + esc(label.slice(m[0], m[1])) + "</mark>"; pos = m[1]; });
    return out + esc(label.slice(pos));
  }
  function setActive(i) {
    if (!opts.length) return;
    active = (i + opts.length) % opts.length;
    $$(".opt", res).forEach(function (o, j) { o.setAttribute("aria-selected", j === active ? "true" : "false"); });
    var el = document.getElementById("opt" + active); if (el) el.scrollIntoView({ block: "nearest" });
    q.setAttribute("aria-activedescendant", "opt" + active);
  }
  function openSearch() {
    if (!dlg) return;
    if (dlg.showModal) { if (!dlg.open) dlg.showModal(); } else dlg.setAttribute("open", "");
    q.value = ""; q.focus();
    res.innerHTML = '<div class="empty">' + esc(L.loading) + "</div>";
    loadData().then(function (D) { D0 = D; IDX = IDX || buildIdx(D); render(); }).catch(function () { res.innerHTML = '<div class="empty">' + esc(L.search_off) + "</div>"; });
  }
  function closeSearch() { if (dlg && dlg.open) { if (dlg.close) dlg.close(); else dlg.removeAttribute("open"); } }
  if (dlg) {
    $$("[data-search]").forEach(function (b) { b.addEventListener("click", openSearch); });
    $("[data-close]", dlg).addEventListener("click", closeSearch);
    dlg.addEventListener("click", function (e) { if (e.target === dlg) closeSearch(); });
    q.addEventListener("input", render);
    q.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
      else if (e.key === "Enter") { e.preventDefault(); var h = opts[active >= 0 ? active : 0]; if (h) location.href = h; }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && !dlg.open && !/input|textarea|select/i.test(document.activeElement.tagName)) { e.preventDefault(); openSearch(); }
    });
  }

  /* 9. the IT/EN switch keeps the picked day */
  $$("a.lang").forEach(function (a) {
    a.addEventListener("click", function () {
      var d = $(".day[aria-pressed=true]");
      if (d && d.getAttribute("data-day") !== TODAY) a.href = a.href.split("?")[0] + "?" + (LANG === "it" ? "day" : "giorno") + "=" + d.getAttribute("data-day");
    });
  });
})();
