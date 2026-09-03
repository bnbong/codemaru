// Progressive enhancement for the generator. The page works without JS (the
// form GETs "/" and the server renders a live preview); this adds instant
// preview updates, a Reload that bypasses the browser/CDN cache (the server's
// summary cache still applies), and copy buttons.
(function () {
  "use strict";

  var GITHUB_RE = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/;
  var PLATFORM_RE = /^[A-Za-z0-9._-]{1,39}$/;

  var form = document.getElementById("generator-form");
  if (!form) return;

  var els = {
    github: document.getElementById("github"),
    boj: document.getElementById("boj"),
    leetcode: document.getElementById("leetcode"),
    jungol: document.getElementById("jungol"),
    theme: document.getElementById("theme"),
    compact: document.getElementById("compact"),
    animate: document.getElementById("animate"),
    previewImg: document.getElementById("preview-img"),
    preview: document.querySelector(".preview"),
    spinner: document.getElementById("preview-spinner"),
    markdown: document.getElementById("snippet-markdown"),
    picture: document.getElementById("snippet-picture"),
    refresh: document.getElementById("refresh"),
    replay: document.getElementById("replay"),
  };

  var actionAvailable = document.body.getAttribute("data-action-available") === "true";
  var refreshKey = 0;
  var replaySeq = 0;
  var spinnerTimer = null;

  function readState() {
    return {
      github: els.github.value.trim(),
      boj: els.boj.value.trim(),
      leetcode: els.leetcode.value.trim(),
      jungol: els.jungol.value.trim(),
      theme: els.theme.value,
      compact: els.compact.value === "true",
      animate: els.animate.value !== "false",
    };
  }

  function validate(s) {
    if (!s.github) return "github: a GitHub username is required";
    if (!GITHUB_RE.test(s.github))
      return "github: letters, numbers and single hyphens only";
    if (s.boj && !PLATFORM_RE.test(s.boj)) return "boj: invalid handle";
    if (s.leetcode && !PLATFORM_RE.test(s.leetcode)) return "leetcode: invalid handle";
    if (s.jungol && !PLATFORM_RE.test(s.jungol)) return "jungol: invalid handle";
    return null;
  }

  // Mirrors build_card_query() in codemaru/web/snippets.py: defaults and empty
  // handles are omitted so URLs stay clean. themeOverride builds the same query
  // for a different theme (used by the <picture> dark <source>).
  function buildQuery(s, themeOverride) {
    var theme = themeOverride || s.theme;
    var p = new URLSearchParams();
    p.set("github", s.github);
    if (s.boj) p.set("boj", s.boj);
    if (s.leetcode) p.set("leetcode", s.leetcode);
    if (s.jungol) p.set("jungol", s.jungol);
    if (theme !== "default") p.set("theme", theme);
    if (s.compact) p.set("compact", "true");
    if (!s.animate) p.set("animate", "false");
    return p.toString();
  }

  // Keep the address bar in sync with the form so a reload — or a shared link —
  // reproduces exactly what's on screen. The cache-busting params stay out.
  function syncUrl(query) {
    if (!window.history || !window.history.replaceState) return;
    var next = "/?" + query;
    if (window.location.pathname + window.location.search === next) return;
    window.history.replaceState(null, "", next);
  }

  // With animation off there is no entrance to replay, so the button falls back
  // to a cache-busting reload — and says so.
  function syncReplayTitle(animate) {
    if (!els.replay) return;
    els.replay.title = animate
      ? "Replay the card's entrance animation"
      : "Animation is off — reloads the preview";
  }

  function showError(message) {
    var node = document.getElementById("error");
    if (!node) {
      node = document.createElement("div");
      node.id = "error";
      node.className = "error";
      form.appendChild(node);
    }
    node.textContent = message;
  }

  function clearError() {
    var node = document.getElementById("error");
    if (node) node.remove();
  }

  function setText(node, value) {
    if (node) node.textContent = value;
  }

  function showSpinner() {
    if (els.spinner) els.spinner.hidden = false;
    if (els.preview) els.preview.setAttribute("aria-busy", "true");
  }

  function hideSpinner() {
    if (els.spinner) els.spinner.hidden = true;
    if (els.preview) els.preview.removeAttribute("aria-busy");
    if (spinnerTimer) {
      clearTimeout(spinnerTimer);
      spinnerTimer = null;
    }
  }

  // Create the preview <img> the first time (replacing the placeholder) while
  // keeping the spinner element in place.
  function ensureImg() {
    if (els.previewImg || !els.preview) return;
    var placeholder = document.getElementById("preview-placeholder");
    if (placeholder) placeholder.remove();
    var img = document.createElement("img");
    img.id = "preview-img";
    img.alt = "codemaru card preview";
    els.preview.insertBefore(img, els.spinner || null);
    els.previewImg = img;
  }

  function setPreviewSrc(src) {
    ensureImg();
    if (!els.previewImg) return;
    showSpinner();
    els.previewImg.onload = hideSpinner;
    els.previewImg.onerror = hideSpinner;
    els.previewImg.src = src;
    // Safety net: never leave the spinner up if the load event doesn't fire
    // (e.g. an identical cached src or a stalled network).
    if (spinnerTimer) clearTimeout(spinnerTimer);
    spinnerTimer = setTimeout(hideSpinner, 6000);
  }

  function render() {
    var s = readState();
    syncReplayTitle(s.animate);
    var err = validate(s);
    if (err) {
      showError(err);
      return;
    }
    clearError();

    var query = buildQuery(s);
    var previewSrc = "/api/card.svg?" + query;
    // Reload appends a unique value so the browser/CDN refetch the image; Replay
    // forces the <img> to reload so its entrance animation runs again. Both are
    // server-ignored and kept out of the copied snippets.
    if (refreshKey > 0) previewSrc += "&refresh=" + refreshKey;
    if (replaySeq > 0) previewSrc += "&_replay=" + replaySeq;

    setPreviewSrc(previewSrc);

    var origin = window.location.origin;
    var cardUrl = origin + "/api/card.svg?" + query;
    var alt = "codemaru card for " + s.github;
    setText(els.markdown, "[![" + alt + "](" + cardUrl + ")](https://github.com/" + s.github + ")");

    // Same rule as build_snippets(): a dark <source> paired with a light <img>
    // fallback, so the embed follows the reader's GitHub theme. Every other
    // param matches; picking "dark" makes the <img> fall back to "default",
    // while "transparent" stays put (it suits either scheme).
    var darkUrl = origin + "/api/card.svg?" + buildQuery(s, "dark");
    var imgTheme = s.theme === "dark" ? "default" : s.theme;
    var imgUrl = origin + "/api/card.svg?" + buildQuery(s, imgTheme);
    setText(
      els.picture,
      "<picture>\n" +
        '  <source media="(prefers-color-scheme: dark)" srcset="' + darkUrl + '" />\n' +
        '  <img alt="' + alt + '" src="' + imgUrl + '" />\n' +
        "</picture>"
    );

    syncUrl(query);
  }

  var timer = null;
  function scheduleRender() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(render, 150);
  }

  ["github", "boj", "leetcode", "jungol"].forEach(function (id) {
    els[id].addEventListener("input", scheduleRender);
  });
  ["theme", "compact", "animate"].forEach(function (id) {
    els[id].addEventListener("change", render);
  });

  // Don't reload the page on submit when JS is active.
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    render();
  });

  if (els.refresh) {
    els.refresh.addEventListener("click", function () {
      refreshKey = Date.now();
      render();
    });
  }

  if (els.replay) {
    syncReplayTitle(els.animate.value !== "false");
    els.replay.addEventListener("click", function () {
      if (readState().animate) {
        replaySeq = Date.now();
      } else {
        refreshKey = Date.now();
      }
      render();
    });
  }

  document.querySelectorAll("button[data-copy]").forEach(function (btn) {
    var key = btn.getAttribute("data-copy");
    if (key === "action" && !actionAvailable) return;
    btn.addEventListener("click", function () {
      var pre = document.getElementById("snippet-" + key);
      if (!pre || !navigator.clipboard) return;
      navigator.clipboard.writeText(pre.textContent).then(function () {
        var original = btn.textContent;
        btn.textContent = "Copied";
        setTimeout(function () {
          btn.textContent = original;
        }, 1500);
      });
    });
  });
})();
