/* faqbot widget — self-contained, no build step. */
(function () {
  "use strict";

  var script = document.currentScript;
  var API = ((script && script.dataset.api) || "").replace(/\/$/, "");
  var STORE_SESSION = "faqbot.session";
  var STORE_HISTORY = "faqbot.history";

  var config = { botName: "FAQ bot", greeting: "Hi! Ask me a question." };
  var session = readSession();
  var busy = false;

  var root = document.createElement("div");
  root.className = "fb-root";
  root.dataset.state = "closed";
  root.innerHTML =
    '<section class="fb-panel" role="dialog" aria-modal="false" aria-label="Chat">' +
    '  <header class="fb-head">' +
    '    <div class="fb-avatar" aria-hidden="true">?</div>' +
    '    <div class="fb-title"><strong></strong><span>Answers from the FAQ</span></div>' +
    '    <button type="button" class="fb-icon fb-reset" title="New dialogue" aria-label="New dialogue">&#8635;</button>' +
    '    <button type="button" class="fb-icon fb-close" title="Close" aria-label="Close chat">&#10005;</button>' +
    "  </header>" +
    '  <div class="fb-log" role="log" aria-live="polite"></div>' +
    '  <div class="fb-quick" aria-label="Suggested questions"></div>' +
    '  <form class="fb-form">' +
    '    <input type="text" maxlength="500" autocomplete="off" placeholder="Ask a question…" aria-label="Your question">' +
    '    <button type="submit" aria-label="Send">&#8594;</button>' +
    "  </form>" +
    '  <footer class="fb-foot">Powered by <a href="https://github.com/" target="_blank" rel="noopener">faqbot</a></footer>' +
    "</section>" +
    '<button type="button" class="fb-launcher" aria-label="Open chat"><span>?</span></button>';
  document.body.appendChild(root);

  var panel = root.querySelector(".fb-panel");
  var log = root.querySelector(".fb-log");
  var quickBox = root.querySelector(".fb-quick");
  var form = root.querySelector(".fb-form");
  var input = form.querySelector("input");
  var launcher = root.querySelector(".fb-launcher");
  var title = root.querySelector(".fb-title strong");
  var avatar = root.querySelector(".fb-avatar");

  /* ----------------------------------------------------------- storage */
  function readSession() {
    try {
      var value = localStorage.getItem(STORE_SESSION);
      if (value && value.length >= 8) return value;
      value = Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem(STORE_SESSION, value);
      return value;
    } catch (error) {
      return "anon-" + Math.random().toString(36).slice(2);
    }
  }

  function saveHistory() {
    try {
      var messages = log.querySelectorAll(".fb-msg");
      var data = [];
      for (var i = Math.max(0, messages.length - 60); i < messages.length; i++) {
        data.push({
          role: messages[i].dataset.role,
          text: messages[i].dataset.text
        });
      }
      localStorage.setItem(STORE_HISTORY, JSON.stringify(data));
    } catch (error) {
      /* storage is optional */
    }
  }

  /* ------------------------------------------------------------- view */
  function linkify(text) {
    var urlPattern = /(https?:\/\/[^\s<]+|@[a-zA-Z0-9_]{4,})/g;
    var fragment = document.createDocumentFragment();
    var last = 0;
    var match;

    while ((match = urlPattern.exec(text)) !== null) {
      if (match.index > last) {
        fragment.appendChild(document.createTextNode(text.slice(last, match.index)));
      }
      var token = match[0];
      var anchor = document.createElement("a");
      anchor.target = "_blank";
      anchor.rel = "noopener";
      if (token.charAt(0) === "@") {
        anchor.href = "https://t.me/" + token.slice(1);
        anchor.textContent = token;
      } else {
        anchor.href = token;
        anchor.textContent = token;
      }
      fragment.appendChild(anchor);
      last = match.index + token.length;
    }
    if (last < text.length) {
      fragment.appendChild(document.createTextNode(text.slice(last)));
    }
    return fragment;
  }

  function addMessage(role, text, options) {
    options = options || {};
    var bubble = document.createElement("div");
    bubble.className = "fb-msg fb-msg--" + role;
    bubble.dataset.role = role;
    bubble.dataset.text = text;

    var body = document.createElement("div");
    body.className = "fb-msg__body";
    String(text)
      .split("\n")
      .forEach(function (line, index) {
        if (index > 0) body.appendChild(document.createElement("br"));
        body.appendChild(linkify(line));
      });
    bubble.appendChild(body);

    if (role === "bot" && options.qaId) {
      var meta = document.createElement("div");
      meta.className = "fb-rate";
      meta.appendChild(ratingButton(1, options.qaId, "Helpful"));
      meta.appendChild(ratingButton(-1, options.qaId, "Not helpful"));
      bubble.appendChild(meta);
    }

    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;
    if (!options.restore) saveHistory();
    return bubble;
  }

  function ratingButton(value, qaId, label) {
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = value === 1 ? "\u{1F44D}" : "\u{1F44E}";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.addEventListener("click", function () {
      button.parentElement.querySelectorAll("button").forEach(function (item) {
        item.classList.remove("is-active");
      });
      button.classList.add("is-active");
      api("/api/feedback", { session: session, qa_id: qaId, value: value }).catch(
        function () {}
      );
    });
    return button;
  }

  function setQuick(chips) {
    quickBox.textContent = "";
    (chips || []).slice(0, 4).forEach(function (chip) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "fb-chip";
      button.textContent = chip.label;
      button.addEventListener("click", function () {
        if (chip.url) {
          window.open(chip.url, "_blank", "noopener");
          return;
        }
        send(chip.query || chip.label);
      });
      quickBox.appendChild(button);
    });
  }

  function showTyping(on) {
    var typing = log.querySelector(".fb-typing");
    if (on && !typing) {
      typing = document.createElement("div");
      typing.className = "fb-typing";
      typing.innerHTML = "<i></i><i></i><i></i>";
      log.appendChild(typing);
      log.scrollTop = log.scrollHeight;
    } else if (!on && typing) {
      typing.remove();
    }
  }

  /* ------------------------------------------------------------ network */
  function api(path, payload) {
    var options = { headers: {} };
    var url = API + path;
    if (payload) {
      options.method = "POST";
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }
    return fetch(url, options).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) {
          throw new Error((data && data.detail) || "Request failed");
        }
        return data;
      });
    });
  }

  function send(text) {
    text = String(text || "").trim();
    if (!text || busy) return;
    busy = true;
    input.value = "";
    setQuick([]);
    addMessage("user", text);
    showTyping(true);

    api("/api/ask", { message: text, session: session, page: location.href })
      .then(function (data) {
        showTyping(false);
        addMessage("bot", data.answer || "…", { qaId: data.qa_id });
        setQuick(data.quick);
        busy = false;
      })
      .catch(function (error) {
        showTyping(false);
        addMessage("bot", "Sorry, the bot is unavailable: " + error.message);
        busy = false;
      });
  }

  /* -------------------------------------------------------------- state */
  function open() {
    root.dataset.state = "open";
    panel.setAttribute("aria-hidden", "false");
    setTimeout(function () {
      input.focus();
    }, 60);
    log.scrollTop = log.scrollHeight;
  }

  function close() {
    root.dataset.state = "closed";
    panel.setAttribute("aria-hidden", "true");
    launcher.focus();
  }

  function reset() {
    try {
      localStorage.removeItem(STORE_HISTORY);
      session = readSession();
    } catch (error) {}
    log.textContent = "";
    setQuick(config.quick);
    addMessage("bot", config.greeting);
    input.focus();
  }

  function restore() {
    var restored = false;
    try {
      var raw = localStorage.getItem(STORE_HISTORY);
      if (raw) {
        JSON.parse(raw).forEach(function (message) {
          addMessage(message.role === "user" ? "user" : "bot", message.text, {
            restore: true
          });
          restored = true;
        });
      }
    } catch (error) {}
    return restored;
  }

  /* --------------------------------------------------------------- init */
  function applyConfig(data) {
    config = Object.assign(config, data);
    title.textContent = config.botName;
    avatar.textContent = (config.botName || "?").trim().charAt(0).toUpperCase();
    if (config.color) root.style.setProperty("--fb-accent", config.color);
  }

  function boot() {
    var hasHistory = restore();
    api("/api/config")
      .then(function (data) {
        applyConfig(data);
        if (!hasHistory) {
          addMessage("bot", data.greeting);
          setQuick(data.quick);
        }
      })
      .catch(function () {
        if (!hasHistory) {
          addMessage("bot", config.greeting);
        }
      });
  }

  launcher.addEventListener("click", function () {
    if (root.dataset.state === "open") close();
    else open();
  });
  root.querySelector(".fb-close").addEventListener("click", close);
  root.querySelector(".fb-reset").addEventListener("click", reset);
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    send(input.value);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && root.dataset.state === "open") close();
  });

  boot();
})();
