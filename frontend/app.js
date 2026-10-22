"use strict";

/* =====================================================================
 * StayFlow guest chat (vanilla JS, no build step).
 *
 * Two modes:
 *   1. Full page  — StayFlowChat.init({ hotelId, hotelName, mode: "fullpage" })
 *      The page at /chat uses this (see index.html).
 *   2. Floating widget — StayFlowChat.init({ hotelId, hotelName,
 *      mode: "widget" }) renders a launcher button + collapsible panel,
 *      suitable for embedding on a hotel website:
 *        <script src="https://chat.example.com/app.js"></script>
 *        <script>StayFlowChat.init({ hotelId: 1, hotelName: "…",
 *                                     apiBase: "https://chat.example.com",
 *                                     mode: "widget" });</script>
 *
 * Configuration is public embed config: the hotel is resolved by the page
 * embedding the chat. There is intentionally no hotel picker and no call to
 * the staff-only GET /hotels endpoint (it requires a staff JWT).
 *
 * API contract (backend/app/agent/schemas.py + app/api/router.py):
 *   POST {apiBase}/api/v1/agent/chat
 *   Request:  { hotel_id: int (required), message: str (1-4000),
 *               conversation_id: int|null, guest_id: int|null, channel }
 *   Response: { reply: str, conversation_id: int, iterations: int,
 *               degraded: bool, tool_trace: [{ tool, arguments, ok,
 *               result, error }] }
 *
 * Structured cards are derived ONLY from tool_trace results:
 *   - get_room_rate   -> rate quote card (room_type, dates, nights, total,
 *                        currency, missing_dates, fully_priced)
 *   - preview_booking -> booking draft card (draft_id, expires_at, details:
 *                        room_type, check_in, check_out, number_of_guests,
 *                        total_price, currency) + confirm/cancel chips
 * If a trace is missing or malformed, the plain-text reply is shown on its
 * own — the cards are a progressive enhancement, never a replacement.
 * ===================================================================== */

window.StayFlowChat = (function () {
  var CHAT_PATH = "/api/v1/agent/chat";
  var MAX_LEN = 4000;

  /* ---------- text fallbacks for the confirmation heuristic ---------- */
  var BOOKING_SUMMARY_RE = /booking summary/i;
  var CONFIRM_ASK_RE =
    /shall i confirm|confirm this booking|ready to confirm|proceed with this booking|would you like me to confirm/i;

  function looksLikeBookingConfirmation(reply) {
    return BOOKING_SUMMARY_RE.test(reply) && CONFIRM_ASK_RE.test(reply);
  }

  /* ---------- small helpers ---------- */
  function el(tag, className, text) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function isObj(v) {
    return v !== null && typeof v === "object" && !Array.isArray(v);
  }

  function num(v) {
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function money(value, currency) {
    var n = num(value);
    if (n === null) return String(value);
    var cur = typeof currency === "string" && currency ? currency : "INR";
    try {
      return new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: cur,
        maximumFractionDigits: 2,
      }).format(n);
    } catch (e) {
      return cur + " " + n.toFixed(2);
    }
  }

  function shortDate(iso) {
    if (typeof iso !== "string") return String(iso);
    var d = new Date(iso.length <= 10 ? iso + "T00:00:00" : iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  }

  /* =================================================================
   * Chat instance
   * ================================================================= */
  function createChat(opts) {
    var hotelId = opts.hotelId;
    var hotelName =
      typeof opts.hotelName === "string" && opts.hotelName
        ? opts.hotelName
        : "Our hotel";
    var apiBase =
      typeof opts.apiBase === "string"
        ? opts.apiBase.replace(/\/+$/, "")
        : "";
    var chatUrl = apiBase + CHAT_PATH;
    var sessionKey = "stayflow_conversation_id_" + hotelId;

    var state = {
      conversationId: loadConversationId(),
      sending: false,
      lastFailedMessage: null,
      open: opts.mode !== "widget", // widget starts closed
    };

    /* ---------- DOM ---------- */
    var root = el("div", "sf-chat" + (opts.mode === "widget" ? " sf-in-panel" : " sf-fullpage"));
    root.setAttribute("lang", "en");

    var header = el("header", "sf-header");
    var brand = el("div", "sf-brand");
    var mark = el("span", "sf-mark", hotelName.charAt(0).toUpperCase());
    mark.setAttribute("aria-hidden", "true");
    var brandText = el("div", "sf-brand-text");
    brandText.appendChild(el("p", "sf-hotel", hotelName));
    brandText.appendChild(el("p", "sf-tagline", "AI concierge"));
    brand.appendChild(mark);
    brand.appendChild(brandText);
    var newChatBtn = el("button", "sf-btn sf-btn-ghost", "New chat");
    newChatBtn.type = "button";
    header.appendChild(brand);
    header.appendChild(newChatBtn);
    root.appendChild(header);

    var messagesEl = el("div", "sf-messages");
    messagesEl.setAttribute("role", "log");
    messagesEl.setAttribute("aria-live", "polite");
    messagesEl.setAttribute("aria-label", "Chat messages");
    root.appendChild(messagesEl);

    var chipsEl = el("div", "sf-chips");
    chipsEl.hidden = true;
    root.appendChild(chipsEl);

    var composer = el("footer", "sf-composer");
    var form = el("form");
    form.setAttribute("autocomplete", "off");
    var inputId = "sf-input-" + Math.random().toString(36).slice(2, 8);
    var label = el("label", "sf-sr-only", "Type your message");
    label.setAttribute("for", inputId);
    var input = el("input", "sf-input");
    input.id = inputId;
    input.type = "text";
    input.placeholder = "Ask about rooms, prices, or bookings…";
    input.maxLength = MAX_LEN;
    input.setAttribute("aria-label", "Type your message");
    var sendBtn = el("button", "sf-btn sf-btn-primary", "Send");
    sendBtn.type = "submit";
    form.appendChild(label);
    form.appendChild(input);
    form.appendChild(sendBtn);
    composer.appendChild(form);
    composer.appendChild(
      el(
        "p",
        "sf-fineprint",
        "Demo concierge — do not share payment details in chat."
      )
    );
    root.appendChild(composer);

    /* ---------- rendering ---------- */
    function scrollToBottom() {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function addMessage(kind, text) {
      var div = el("div", "message " + kind, text);
      messagesEl.appendChild(div);
      scrollToBottom();
      return div;
    }

    function addError(text) {
      var div = el("div", "message error");
      div.appendChild(document.createTextNode(text + " "));
      var retry = el("button", "sf-retry", "Retry");
      retry.type = "button";
      retry.addEventListener("click", function () {
        if (state.lastFailedMessage) {
          div.remove();
          sendMessage(state.lastFailedMessage);
        }
      });
      div.appendChild(retry);
      messagesEl.appendChild(div);
      scrollToBottom();
    }

    function showTyping() {
      var div = el("div", "message agent sf-typing");
      div.setAttribute("role", "status");
      var dots = el("span", "sf-dots");
      dots.setAttribute("aria-hidden", "true");
      dots.appendChild(el("span"));
      dots.appendChild(el("span"));
      dots.appendChild(el("span"));
      div.appendChild(dots);
      div.appendChild(el("span", "sf-sr-only", "Concierge is typing"));
      messagesEl.appendChild(div);
      scrollToBottom();
    }

    function hideTyping() {
      var t = messagesEl.querySelector(".sf-typing");
      if (t) t.remove();
    }

    /* ----- structured cards (from tool_trace only) ----- */
    function lastOkTrace(traces, toolName) {
      if (!Array.isArray(traces)) return null;
      for (var i = traces.length - 1; i >= 0; i--) {
        var t = traces[i];
        if (isObj(t) && t.tool === toolName && t.ok === true && isObj(t.result))
          return t.result;
      }
      return null;
    }

    function cardShell(title, extraClass) {
      var card = el("div", "sf-card " + (extraClass || ""));
      card.appendChild(el("p", "sf-card-title", title));
      return card;
    }

    function cardRow(dl, term, value) {
      var row = el("div", "sf-card-row");
      row.appendChild(el("dt", null, term));
      row.appendChild(el("dd", null, value));
      dl.appendChild(row);
    }

    /** Rate quote card from a get_room_rate tool result. Returns null when
     * the result doesn't have the expected shape (caller falls back to
     * the plain-text reply). */
    function quoteCard(result) {
      try {
        if (typeof result.room_type !== "string" || result.total === undefined)
          return null;
        var nights = Array.isArray(result.nights) ? result.nights : [];
        var card = cardShell("Rate quote", "sf-quote");
        var dl = el("dl", "sf-card-list");
        cardRow(dl, "Room", result.room_type);
        cardRow(
          dl,
          "Dates",
          shortDate(result.check_in) + " → " + shortDate(result.check_out)
        );
        cardRow(dl, "Nights", String(nights.length));
        cardRow(dl, "Total", money(result.total, result.currency));
        card.appendChild(dl);
        var missing = Array.isArray(result.missing_dates)
          ? result.missing_dates.length
          : 0;
        if (result.fully_priced === false || missing > 0) {
          card.appendChild(
            el(
              "p",
              "sf-card-note sf-warn",
              "Some dates have no published rate yet — the total may change before booking."
            )
          );
        }
        return card;
      } catch (e) {
        return null;
      }
    }

    /** Booking draft card from a preview_booking tool result. */
    function draftCard(result) {
      try {
        var d = isObj(result.details) ? result.details : null;
        if (!d || typeof d.room_type !== "string" || d.total_price === undefined)
          return null;
        var card = cardShell("Booking draft", "sf-draft");
        var dl = el("dl", "sf-card-list");
        cardRow(dl, "Room", d.room_type);
        cardRow(
          dl,
          "Dates",
          shortDate(d.check_in) + " → " + shortDate(d.check_out)
        );
        if (d.number_of_guests !== undefined)
          cardRow(dl, "Guests", String(d.number_of_guests));
        cardRow(dl, "Total", money(d.total_price, d.currency));
        card.appendChild(dl);
        var note = "Nothing is booked yet — confirm below and we'll hold it.";
        if (typeof result.expires_at === "string")
          note += " Draft expires " + shortDate(result.expires_at) + ".";
        card.appendChild(el("p", "sf-card-note", note));
        return card;
      } catch (e) {
        return null;
      }
    }

    function renderAgentReply(data) {
      var reply =
        data && typeof data.reply === "string" ? data.reply : "(empty reply)";
      var div = addMessage("agent", reply);
      if (data && data.degraded === true) {
        div.appendChild(
          el(
            "span",
            "sf-degraded",
            "Answered in offline mode — some live details may be unavailable."
          )
        );
      }
      var traces = data ? data.tool_trace : null;
      var quote = lastOkTrace(traces, "get_room_rate");
      var draft = lastOkTrace(traces, "preview_booking");
      if (quote) {
        var qc = quoteCard(quote);
        if (qc) messagesEl.appendChild(qc);
      }
      if (draft) {
        var dc = draftCard(draft);
        if (dc) messagesEl.appendChild(dc);
        showConfirmChips();
      } else if (looksLikeBookingConfirmation(reply)) {
        showConfirmChips();
      }
      scrollToBottom();
    }

    /* ---------- chips ---------- */
    function clearChips() {
      chipsEl.hidden = true;
      chipsEl.innerHTML = "";
    }

    function showChips(options) {
      clearChips();
      options.forEach(function (opt) {
        var btn = el("button", "sf-chip", opt.label);
        btn.type = "button";
        btn.addEventListener("click", function () {
          clearChips();
          sendMessage(opt.message);
        });
        chipsEl.appendChild(btn);
      });
      chipsEl.hidden = false;
      scrollToBottom();
    }

    function showConfirmChips() {
      showChips([
        { label: "Yes, confirm", message: "Yes, please confirm the booking." },
        {
          label: "No, don't confirm",
          message: "No, don't confirm. Let me change something.",
        },
      ]);
    }

    /* ---------- conversation persistence ---------- */
    function loadConversationId() {
      try {
        var raw = sessionStorage.getItem(sessionKey);
        var id = raw ? parseInt(raw, 10) : NaN;
        return Number.isInteger(id) ? id : null;
      } catch (e) {
        return null;
      }
    }

    function saveConversationId(id) {
      state.conversationId = id;
      try {
        sessionStorage.setItem(sessionKey, String(id));
      } catch (e) {
        /* storage unavailable — conversation still works for this page view */
      }
    }

    function resetConversation() {
      state.conversationId = null;
      try {
        sessionStorage.removeItem(sessionKey);
      } catch (e) {}
      clearChips();
      messagesEl.innerHTML = "";
      addMessage(
        "system",
        "New chat started at " + hotelName + ". How can I help you today?"
      );
    }

    /* ---------- round-trip ---------- */
    function setComposerEnabled(enabled) {
      input.disabled = !enabled;
      sendBtn.disabled = !enabled;
      chipsEl
        .querySelectorAll("button")
        .forEach(function (b) { b.disabled = !enabled; });
    }

    function sendMessage(text) {
      var message = String(text || "").trim();
      if (!message || state.sending) return;

      state.sending = true;
      setComposerEnabled(false);
      clearChips();

      addMessage("guest", message);
      input.value = "";
      showTyping();
      state.lastFailedMessage = message;

      fetch(chatUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hotel_id: hotelId,
          message: message.slice(0, MAX_LEN),
          conversation_id: state.conversationId,
          channel: "web",
        }),
      })
        .then(function (res) {
          if (!res.ok) {
            return res.text().then(function (detail) {
              throw new Error(
                "Server responded " +
                  res.status +
                  (detail ? ": " + detail.slice(0, 160) : "")
              );
            });
          }
          return res.json();
        })
        .then(function (data) {
          state.lastFailedMessage = null;
          hideTyping();
          if (data && typeof data.conversation_id === "number") {
            saveConversationId(data.conversation_id);
          }
          renderAgentReply(data || {});
        })
        .catch(function (err) {
          hideTyping();
          addError(
            "Couldn't reach the concierge (" + (err && err.message ? err.message : "network error") + ")."
          );
        })
        .then(function () {
          state.sending = false;
          setComposerEnabled(true);
          input.focus();
        });
    }

    /* ---------- wiring ---------- */
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      sendMessage(input.value);
    });

    newChatBtn.addEventListener("click", function () {
      if (state.sending) return;
      resetConversation();
    });

    addMessage(
      "system",
      "Welcome to " + hotelName + "! Ask me about rooms, rates, or bookings."
    );

    return { root: root, reset: resetConversation, send: sendMessage };
  }

  /* =================================================================
   * Public init
   * ================================================================= */
  function init(options) {
    var opts = options || {};
    if (!Number.isInteger(opts.hotelId)) {
      throw new Error("StayFlowChat.init requires an integer hotelId.");
    }
    var mode = opts.mode === "widget" ? "widget" : "fullpage";
    var chat = createChat({
      hotelId: opts.hotelId,
      hotelName: opts.hotelName,
      apiBase: opts.apiBase,
      mode: mode,
    });

    if (mode === "widget") {
      var wrap = el("div", "sf-widget");
      var panel = el("div", "sf-panel");
      panel.hidden = true;
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-label", (opts.hotelName || "Hotel") + " concierge chat");
      panel.appendChild(chat.root);

      var launcher = el("button", "sf-launcher");
      launcher.type = "button";
      launcher.setAttribute("aria-expanded", "false");
      launcher.setAttribute("aria-label", "Open concierge chat");
      launcher.innerHTML =
        '<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">' +
        '<path fill="currentColor" d="M12 2C6.5 2 2 6.1 2 11.2c0 2.9 1.4 5.5 3.7 7.2V22l3.4-1.9c.9.3 1.9.4 2.9.4 5.5 0 10-4.1 10-9.2S17.5 2 12 2zm0 12.5c-.4 0-.8-.2-1-.6l-2.2-3.1c-.3-.4-.2-1 .2-1.3.4-.3 1-.2 1.3.2l1.7 2.4 3.2-4.3c.3-.4.9-.5 1.3-.2.4.3.5.9.2 1.3l-3.7 5c-.2.4-.6.6-1 .6z"/>' +
        "</svg>";

      function setOpen(open) {
        panel.hidden = !open;
        launcher.setAttribute("aria-expanded", String(open));
        launcher.setAttribute(
          "aria-label",
          open ? "Close concierge chat" : "Open concierge chat"
        );
        if (open) {
          var field = panel.querySelector(".sf-input");
          if (field) field.focus();
        } else {
          launcher.focus();
        }
      }

      launcher.addEventListener("click", function () {
        setOpen(panel.hidden);
      });
      panel.addEventListener("keydown", function (e) {
        if (e.key === "Escape") setOpen(false);
      });

      wrap.appendChild(panel);
      wrap.appendChild(launcher);
      document.body.appendChild(wrap);
      return { reset: chat.reset, setOpen: setOpen };
    }

    var mount =
      opts.mount instanceof Element
        ? opts.mount
        : document.getElementById("stayflow-chat-root");
    if (!mount) {
      throw new Error(
        "StayFlowChat.init: no mount element found (expected #stayflow-chat-root)."
      );
    }
    mount.appendChild(chat.root);
    return { reset: chat.reset };
  }

  /* Auto-init for the full-page build (index.html sets window.STAYFLOW_CHAT). */
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit);
  } else {
    autoInit();
  }
  function autoInit() {
    var cfg = window.STAYFLOW_CHAT;
    if (cfg && cfg.hotelId && !cfg._initialized) {
      cfg._initialized = true;
      try {
        init(cfg);
      } catch (e) {
        var root = document.getElementById("stayflow-chat-root");
        if (root)
          root.textContent =
            "Chat could not start: " + (e && e.message ? e.message : e);
      }
    }
  }

  return { init: init };
})();
