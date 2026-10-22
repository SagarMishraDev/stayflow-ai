"use strict";

/* =====================================================================
 * StayFlow AI — public hotel landing page.
 *
 * Data: GET {origin}/api/v1/public/hotels/{public_id}/landing, or the
 * featured-hotel variant when no hotel is specified. Hotel resolution:
 *   1. ?hotel=<public_id> in the URL
 *   2. localStorage "stayflow_landing_hotel" (last hotel viewed)
 *   3. GET /api/v1/public/featured-hotel/landing (single-property/demo)
 *
 * Staff login posts to the SAME endpoint the dashboard uses
 * (POST /api/v1/auth/login) and stores the session under the SAME
 * localStorage keys ("stayflow_token", "stayflow_hotel_id"), so a
 * session started here is picked up by the dashboard. Credentials are
 * never logged.
 * ===================================================================== */

(function () {
  var API = window.location.origin + "/api/v1";
  var TOKEN_KEY = "stayflow_token"; // dashboard: src/lib/api.ts
  var HOTEL_KEY = "stayflow_hotel_id"; // dashboard: src/lib/auth.tsx
  var LAST_HOTEL_KEY = "stayflow_landing_hotel";
  var DASHBOARD_URL_KEY = "stayflow_dashboard_url";

  var state = { hotel: null, redirectTimer: null, countdownTimer: null };

  /* Replacement photography (NOT the reference site's assets): found
   * via image search, verified HTTP 200 on 2026-10-22, and LOCALIZED
   * in v5 — the files live in frontend/landing/assets/ and are served
   * by the /landing static mount, so absolute /landing/assets/* paths
   * resolve identically at "/" and "/landing/". Original sources are
   * listed in MASTER_BUILD_REPORT.md (v4/v5). Any image that fails to
   * load is swapped for a token-coloured gradient block by
   * photoFigure() — never a broken <img>. */
  var HERO_IMAGE = "/landing/assets/hero.jpg";
  var ROOM_IMAGES = [
    "/landing/assets/room-1.jpg",
    "/landing/assets/room-2.jpg",
    "/landing/assets/room-3.jpg",
  ];
  /* Service photography is matched by the service itself — name,
   * category and description keywords — NEVER by card position (the old
   * index-based mapping put the spa photo on the Airport Shuttle card).
   * Local assets: exp-1 = spa, exp-2 = hotel lobby, exp-3 = restaurant,
   * exp-transport = white minivan at an airport terminal (Pexels
   * 39075475), hero = pool at golden hour. Services with no fitting
   * photo (laundry, housekeeping, …) deliberately get no image and
   * render the gradient fallback figure instead. */
  var SERVICE_IMAGE_RULES = [
    { keys: ["spa", "wellness", "massage"], src: "/landing/assets/exp-1.jpg" },
    {
      keys: ["shuttle", "transfer", "airport", "taxi", "cab", "transport", "chauffeur"],
      src: "/landing/assets/exp-transport.jpg",
    },
    {
      keys: ["restaurant", "dining", "food", "cuisine", "breakfast", "cafe"],
      src: "/landing/assets/exp-3.jpg",
    },
    { keys: ["pool", "swim"], src: HERO_IMAGE },
    { keys: ["lobby", "reception", "front desk"], src: "/landing/assets/exp-2.jpg" },
  ];

  function serviceImage(svc) {
    var hay = (
      (svc.name || "") + " " + (svc.category || "") + " " + (svc.description || "")
    ).toLowerCase();
    for (var i = 0; i < SERVICE_IMAGE_RULES.length; i++) {
      var rule = SERVICE_IMAGE_RULES[i];
      for (var j = 0; j < rule.keys.length; j++) {
        if (hay.indexOf(rule.keys[j]) !== -1) return rule.src;
      }
    }
    return null;
  }

  /* Gradient-only media figure (no photo): same markup/classes the
   * error path swaps in, so layout is identical. */
  function mediaFallback(altClass) {
    var fig = el("figure", "sf-card-media");
    fig.appendChild(
      el("div", "sf-card-media-fallback" + (altClass ? " " + altClass : ""))
    );
    return fig;
  }

  /* Build a card media figure: real photo, gradient fallback on error. */
  function photoFigure(src, alt, altClass) {
    if (!src) return mediaFallback(altClass);
    var fig = el("figure", "sf-card-media");
    var img = el("img");
    img.src = src;
    img.alt = alt || "";
    img.loading = "lazy";
    img.addEventListener("error", function () {
      var fb = el("div", "sf-card-media-fallback" + (altClass ? " " + altClass : ""));
      fig.replaceChildren(fb);
    });
    fig.appendChild(img);
    return fig;
  }

  function $(id) { return document.getElementById(id); }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function money(amount, currency) {
    var num = Number(amount);
    if (!isFinite(num)) return String(amount);
    try {
      return new Intl.NumberFormat(undefined, {
        style: "currency", currency: currency || "INR", maximumFractionDigits: 0,
      }).format(num);
    } catch (e) {
      return (currency || "INR") + " " + num.toLocaleString();
    }
  }

  function dashboardUrl() {
    return (
      window.STAYFLOW_DASHBOARD_URL ||
      window.localStorage.getItem(DASHBOARD_URL_KEY) ||
      "http://localhost:5173/"
    );
  }

  /* ---------------- Hotel loading ---------------- */

  function fetchJson(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error("http " + r.status);
      return r.json();
    });
  }

  function loadLanding() {
    var params = new URLSearchParams(window.location.search);
    var candidates = [];
    var fromUrl = params.get("hotel");
    if (fromUrl) candidates.push(fromUrl);
    var last = window.localStorage.getItem(LAST_HOTEL_KEY);
    if (last && candidates.indexOf(last) === -1) candidates.push(last);

    var chain = Promise.reject(new Error("no candidate"));
    candidates.forEach(function (publicId) {
      chain = chain.catch(function () {
        return fetchJson(API + "/public/hotels/" + encodeURIComponent(publicId) + "/landing");
      });
    });
    return chain.catch(function () {
      return fetchJson(API + "/public/featured-hotel/landing");
    });
  }

  function showError() {
    $("state-loading").hidden = true;
    $("content").hidden = true;
    $("state-error").hidden = false;
  }

  function hideSection(id, hasData) {
    var section = $(id);
    if (section) section.hidden = !hasData;
    return hasData;
  }

  function render(data) {
    var hotel = data.hotel;
    state.hotel = hotel;
    window.localStorage.setItem(LAST_HOTEL_KEY, hotel.public_id);
    document.title = hotel.name + " — Powered by StayFlow AI";

    $("nav-hotel-name").textContent = hotel.name;
    $("footer-hotel-name").textContent = hotel.name;

    // Hero
    $("hero-city").textContent = hotel.city ? "Your stay in " + hotel.city : "Welcome";
    $("hero-name").textContent = hotel.name;
    $("hero-desc").textContent = hotel.description || "";
    var heroImg = $("hero-img");
    heroImg.src = HERO_IMAGE;
    heroImg.alt = hotel.name + " — pool and terrace at golden hour";
    heroImg.addEventListener("error", function () {
      heroImg.hidden = true;
      $("hero-img-fallback").hidden = false;
    });
    var chips = $("hero-chips");
    chips.textContent = "";
    if (hotel.check_in_time) chips.appendChild(el("span", "sf-chip", "Check-in " + hotel.check_in_time));
    if (hotel.check_out_time) chips.appendChild(el("span", "sf-chip", "Check-out " + hotel.check_out_time));
    if (hotel.city) chips.appendChild(el("span", "sf-chip", hotel.city));

    // Feature chips strip: real service names only; hidden when none.
    var featuresRow = $("features-row");
    featuresRow.textContent = "";
    (data.services || []).forEach(function (svc) {
      featuresRow.appendChild(el("span", "sf-feature-chip", svc.name));
    });
    hideSection("features", (data.services || []).length > 0);

    // About (hotel description only — nothing invented)
    $("about-text").textContent = hotel.description || "";
    hideSection("about", !!hotel.description);

    // Rooms & rates
    var roomsGrid = $("rooms-grid");
    roomsGrid.textContent = "";
    (data.rooms || []).forEach(function (room, idx) {
      var card = el("article", "sf-card");
      card.appendChild(photoFigure(ROOM_IMAGES[idx % ROOM_IMAGES.length], room.name + " — photo", idx % 2 ? "sf-card-media-fallback-alt" : ""));
      card.appendChild(el("h3", null, room.name));
      if (room.description) card.appendChild(el("p", null, room.description));
      card.appendChild(el("p", "sf-meta", "Sleeps " + room.capacity));
      if (room.features) card.appendChild(el("p", "sf-meta", room.features));
      if (room.nightly_rate != null) {
        var price = el("p", "sf-price");
        price.appendChild(document.createTextNode(money(room.nightly_rate, room.currency) + " "));
        price.appendChild(el("small", null, "/ night"));
        card.appendChild(price);
      } else {
        card.appendChild(el("p", "sf-meta", "Rates on request — ask the concierge in chat."));
      }
      var cta = el("button", "sf-btn sf-btn-sun sf-card-cta", "Ask to book");
      cta.type = "button";
      cta.setAttribute("data-chat-open", "");
      card.appendChild(cta);
      roomsGrid.appendChild(card);
    });
    hideSection("rooms", (data.rooms || []).length > 0);

    // Amenities & services
    var servicesGrid = $("services-grid");
    servicesGrid.textContent = "";
    (data.services || []).forEach(function (svc, idx) {
      var card = el("article", "sf-card");
      card.appendChild(photoFigure(serviceImage(svc), svc.name + " — photo", idx % 2 ? "sf-card-media-fallback-alt" : ""));
      card.appendChild(el("h3", null, svc.name));
      if (svc.description) card.appendChild(el("p", null, svc.description));
      if (svc.category) card.appendChild(el("p", "sf-meta", svc.category));
      if (svc.price != null) card.appendChild(el("p", "sf-price", money(svc.price, hotel.currency)));
      servicesGrid.appendChild(card);
    });
    hideSection("amenities", (data.services || []).length > 0);

    // Offers
    var offersList = $("offers-list");
    offersList.textContent = "";
    (data.offers || []).forEach(function (offer) {
      var box = el("article", "sf-offer");
      box.appendChild(el("h3", null, offer.name));
      var deal;
      if (String(offer.discount_type).indexOf("percent") !== -1) {
        deal = offer.discount_value + "% off";
      } else {
        deal = money(offer.discount_value, hotel.currency) + " off";
      }
      box.appendChild(el("p", "sf-offer-deal", deal));
      if (offer.description) box.appendChild(el("p", null, offer.description));
      box.appendChild(el("p", "sf-meta", "Valid " + offer.valid_from + " to " + offer.valid_until));
      offersList.appendChild(box);
    });
    hideSection("offers", (data.offers || []).length > 0);

    // Dining / menu highlights
    var menuGrid = $("menu-grid");
    menuGrid.textContent = "";
    (data.menu_highlights || []).forEach(function (item) {
      var card = el("article", "sf-card");
      card.appendChild(el("h3", null, item.name));
      if (item.description) card.appendChild(el("p", null, item.description));
      if (item.category) card.appendChild(el("p", "sf-meta", item.category));
      card.appendChild(el("span", "sf-menu-price", money(item.price, hotel.currency)));
      menuGrid.appendChild(card);
    });
    hideSection("dining", (data.menu_highlights || []).length > 0);

    // FAQ accordion
    var faqList = $("faq-list");
    faqList.textContent = "";
    (data.faqs || []).forEach(function (faq) {
      var item = el("div", "sf-faq-item");
      var btn = el("button", "sf-faq-q", faq.question);
      btn.type = "button";
      btn.setAttribute("aria-expanded", "false");
      var panel = el("div", "sf-faq-a", faq.answer);
      panel.hidden = true;
      btn.addEventListener("click", function () {
        var open = panel.hidden;
        panel.hidden = !open;
        btn.setAttribute("aria-expanded", String(open));
      });
      item.appendChild(btn);
      item.appendChild(panel);
      faqList.appendChild(item);
    });
    hideSection("faq", (data.faqs || []).length > 0);

    // Policies + contact
    var policiesList = $("policies-list");
    policiesList.textContent = "";
    (data.policies || []).forEach(function (policy) {
      var box = el("div", "sf-policy");
      box.appendChild(el("h3", null, policy.title));
      box.appendChild(el("p", null, policy.description));
      policiesList.appendChild(box);
    });
    var contact = $("contact-block");
    contact.textContent = "";
    contact.appendChild(el("div", "sf-contact-label", hotel.name));
    var lines = [];
    if (hotel.address) lines.push(hotel.address + (hotel.city ? ", " + hotel.city : ""));
    else if (hotel.city) lines.push(hotel.city);
    lines.forEach(function (line) {
      contact.appendChild(el("div", null, line));
    });
    if (hotel.phone) {
      var phoneLine = el("div");
      phoneLine.appendChild(document.createTextNode("Phone: "));
      var a = el("a", null, hotel.phone);
      a.href = "tel:" + hotel.phone.replace(/\s+/g, "");
      phoneLine.appendChild(a);
      contact.appendChild(phoneLine);
    }
    if (hotel.email) {
      var emailLine = el("div");
      emailLine.appendChild(document.createTextNode("Email: "));
      var m = el("a", null, hotel.email);
      m.href = "mailto:" + hotel.email;
      emailLine.appendChild(m);
      contact.appendChild(emailLine);
    }
    var hasContact = !!(hotel.address || hotel.phone || hotel.email);
    hideSection("contact", (data.policies || []).length > 0 || hasContact);

    $("state-loading").hidden = true;
    $("state-error").hidden = true;
    $("content").hidden = false;

    embedWidget(hotel.public_id);
  }

  /* ---------------- Widget embed ---------------- */

  function embedWidget(publicId) {
    if (document.querySelector("script[data-stayflow-landing-widget]")) return;
    var script = document.createElement("script");
    script.src = "/widget.js";
    script.async = true;
    script.setAttribute("data-hotel-id", publicId);
    script.setAttribute("data-stayflow-landing-widget", "1");
    document.body.appendChild(script);
  }

  function openWidgetChat(attempts) {
    var launcher = document.querySelector(".sfw-launcher");
    if (launcher) {
      var panel = document.querySelector(".sfw-panel");
      if (!panel || panel.hidden) launcher.click();
      return;
    }
    if ((attempts || 0) < 12) {
      window.setTimeout(function () { openWidgetChat((attempts || 0) + 1); }, 300);
    }
  }

  /* ---------------- Auth (role-based) ---------------- */

  function decodePayload(token) {
    try {
      var body = token.split(".")[1];
      var json = atob(body.replace(/-/g, "+").replace(/_/g, "/"));
      return JSON.parse(json);
    } catch (e) {
      return null;
    }
  }

  function normalizeRole(role) {
    var r = String(role || "").toLowerCase();
    if (r === "admin") return "hotel_admin"; // legacy alias (backend roles.py)
    return r;
  }

  var ROLE_PANELS = {
    super_admin: { label: "Super Admin", button: "Open Admin Dashboard" },
    hotel_admin: { label: "Hotel Admin", button: "Open Hotel Dashboard" },
    staff: { label: "Staff", button: "Open Staff Dashboard" },
  };

  function updateNavAuth() {
    var area = $("nav-auth-area");
    area.textContent = "";
    var token = window.localStorage.getItem(TOKEN_KEY);
    if (token) {
      var open = el("button", "sf-btn sf-btn-primary", "Open Dashboard");
      open.type = "button";
      open.addEventListener("click", function () { window.location.assign(dashboardUrl()); });
      var out = el("button", "sf-btn sf-btn-ghost", "Logout");
      out.type = "button";
      out.addEventListener("click", logout);
      area.appendChild(open);
      area.appendChild(out);
    } else {
      var login = el("button", "sf-btn sf-btn-primary", "Staff Login");
      login.type = "button";
      login.id = "btn-login-open";
      login.addEventListener("click", openModal);
      area.appendChild(login);
    }
  }

  function logout() {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(HOTEL_KEY);
    cancelRedirect();
    updateNavAuth();
  }

  function cancelRedirect() {
    if (state.redirectTimer) { window.clearTimeout(state.redirectTimer); state.redirectTimer = null; }
    if (state.countdownTimer) { window.clearInterval(state.countdownTimer); state.countdownTimer = null; }
  }

  function showRolePanel(user, role) {
    var info = ROLE_PANELS[role] || { label: role || "Staff", button: "Open Dashboard" };
    var name = (user && user.name) || (user && user.email) || "there";
    $("role-welcome").textContent = "Welcome, " + name + " — you are signed in as " + info.label + ".";
    $("btn-open-dashboard").textContent = info.button;
    var seconds = 5;
    var note = $("role-note");
    note.textContent = "Opening your dashboard in " + seconds + " seconds…";
    $("role-panel").hidden = false;
    cancelRedirect();
    state.countdownTimer = window.setInterval(function () {
      seconds -= 1;
      if (seconds > 0) note.textContent = "Opening your dashboard in " + seconds + " seconds…";
    }, 1000);
    state.redirectTimer = window.setTimeout(function () {
      window.location.assign(dashboardUrl());
    }, 5000);
  }

  function openModal() {
    $("login-error").hidden = true;
    $("role-panel").hidden = true;
    $("login-modal").hidden = false;
    var email = $("login-email");
    if (email) email.focus();
  }

  function closeModal() {
    cancelRedirect();
    $("login-modal").hidden = true;
  }

  function handleLogin(event) {
    event.preventDefault();
    var email = $("login-email").value.trim();
    var password = $("login-password").value;
    var errorEl = $("login-error");
    var submit = $("btn-login-submit");
    errorEl.hidden = true;
    submit.disabled = true;
    submit.textContent = "Signing in…";

    fetch(API + "/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email, password: password }),
    })
      .then(function (r) {
        if (!r.ok) throw new Error("login failed");
        return r.json();
      })
      .then(function (data) {
        window.localStorage.setItem(TOKEN_KEY, data.access_token);
        var payload = decodePayload(data.access_token) || {};
        var userId = payload.hotel_user_id || data.hotel_user_id;
        var fallbackRole = normalizeRole(payload.role || data.role);
        var fallbackHotel = payload.hotel_id || data.hotel_id;
        if (!userId) {
          showRolePanel({ email: email }, fallbackRole);
          if (fallbackHotel) window.localStorage.setItem(HOTEL_KEY, String(fallbackHotel));
          updateNavAuth();
          return null;
        }
        return fetch(API + "/hotel-users/" + encodeURIComponent(userId), {
          headers: { Authorization: "Bearer " + data.access_token },
        })
          .then(function (r) { return r.ok ? r.json() : null; })
          .catch(function () { return null; })
          .then(function (me) {
            var hotelId = (me && me.hotel_id) || fallbackHotel;
            if (hotelId) window.localStorage.setItem(HOTEL_KEY, String(hotelId));
            var role = normalizeRole((me && me.role) || fallbackRole);
            showRolePanel(me || { email: email }, role);
            updateNavAuth();
          });
      })
      .catch(function () {
        // Generic on purpose: never reveal which part was wrong.
        errorEl.textContent = "That email and password combination was not recognised. Try again.";
        errorEl.hidden = false;
      })
      .finally(function () {
        submit.disabled = false;
        submit.textContent = "Sign in";
        $("login-password").value = "";
      });
  }

  /* ---------------- Wire up ---------------- */

  document.addEventListener("DOMContentLoaded", function () {
    $("btn-retry").addEventListener("click", function () { window.location.reload(); });
    $("btn-login-open").addEventListener("click", openModal);
    $("btn-login-close").addEventListener("click", closeModal);
    $("login-modal").addEventListener("click", function (e) {
      if (e.target === $("login-modal")) closeModal();
    });
    $("login-form").addEventListener("submit", handleLogin);
    $("btn-open-dashboard").addEventListener("click", function () {
      cancelRedirect();
      window.location.assign(dashboardUrl());
    });
    $("btn-cancel-redirect").addEventListener("click", function () {
      cancelRedirect();
      $("role-note").textContent = "Auto-open cancelled — use the button below whenever you are ready.";
    });
    $("btn-guest-chat").addEventListener("click", function () {
      closeModal();
      openWidgetChat(0);
    });
    // Delegated: covers static buttons AND ones render() creates later
    // (e.g. each room card's "Ask to book").
    document.addEventListener("click", function (e) {
      var btn = e.target.closest ? e.target.closest("[data-chat-open]") : null;
      if (btn) openWidgetChat(0);
    });

    // Mobile hamburger: open/close the nav, close after choosing a link.
    var navToggle = $("btn-nav-toggle");
    var navLinks = $("nav-links");
    if (navToggle && navLinks) {
      navToggle.addEventListener("click", function () {
        var open = navLinks.classList.toggle("sf-nav-open");
        navToggle.setAttribute("aria-expanded", String(open));
        navToggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
      });
      navLinks.addEventListener("click", function (e) {
        if (e.target.tagName === "A") {
          navLinks.classList.remove("sf-nav-open");
          navToggle.setAttribute("aria-expanded", "false");
          navToggle.setAttribute("aria-label", "Open menu");
        }
      });
    }

    updateNavAuth();
    loadLanding().then(render).catch(showError);
  });
})();
