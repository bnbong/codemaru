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
    theme: document.getElementById("theme"),
    compact: document.getElementById("compact"),
    previewImg: document.getElementById("preview-img"),
    preview: document.querySelector(".preview"),
    markdown: document.getElementById("snippet-markdown"),
    picture: document.getElementById("snippet-picture"),
    refresh: document.getElementById("refresh"),
  };

  var actionAvailable = document.body.getAttribute("data-action-available") === "true";
  var refreshKey = 0;

  function readState() {
    return {
      github: els.github.value.trim(),
      boj: els.boj.value.trim(),
      leetcode: els.leetcode.value.trim(),
      theme: els.theme.value,
      compact: els.compact.value === "true",
    };
  }

  function validate(s) {
    if (!s.github) return "github: a GitHub username is required";
    if (!GITHUB_RE.test(s.github))
      return "github: letters, numbers and single hyphens only";
    if (s.boj && !PLATFORM_RE.test(s.boj)) return "boj: invalid handle";
    if (s.leetcode && !PLATFORM_RE.test(s.leetcode)) return "leetcode: invalid handle";
    return null;
  }

  function buildQuery(s) {
    var p = new URLSearchParams();
    p.set("github", s.github);
    if (s.boj) p.set("boj", s.boj);
    if (s.leetcode) p.set("leetcode", s.leetcode);
    if (s.theme !== "default") p.set("theme", s.theme);
    if (s.compact) p.set("compact", "true");
    return p.toString();
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

  function render() {
    var s = readState();
    var err = validate(s);
    if (err) {
      showError(err);
      return;
    }
    clearError();

    var query = buildQuery(s);
    var previewSrc = "/api/card.svg?" + query;
    // Reload appends a unique value so the browser/CDN refetch the image; the
    // server ignores it (its own summary cache still applies). Not added to the
    // copied snippets.
    if (refreshKey > 0) previewSrc += "&refresh=" + refreshKey;

    if (els.previewImg) {
      els.previewImg.src = previewSrc;
    } else if (els.preview) {
      els.preview.innerHTML =
        '<img id="preview-img" src="" alt="codemaru card preview" />';
      els.previewImg = document.getElementById("preview-img");
      els.previewImg.src = previewSrc;
    }

    var origin = window.location.origin;
    var cardUrl = origin + "/api/card.svg?" + query;
    var alt = "codemaru card for " + s.github;
    setText(els.markdown, "[![" + alt + "](" + cardUrl + ")](https://github.com/" + s.github + ")");
    setText(els.picture, '<picture>\n  <img alt="' + alt + '" src="' + cardUrl + '" />\n</picture>');
  }

  var timer = null;
  function scheduleRender() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(render, 150);
  }

  ["github", "boj", "leetcode"].forEach(function (id) {
    els[id].addEventListener("input", scheduleRender);
  });
  ["theme", "compact"].forEach(function (id) {
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
