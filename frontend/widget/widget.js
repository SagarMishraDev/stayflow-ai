"use strict";

/* =====================================================================
 * StayFlow AI — embeddable website chat widget loader (Master Prompt §11).
 *
 * Vanilla JS, no build step. Embed on any hotel website with:
 *
 *   <script src="https://YOUR_HOSTED_DOMAIN/widget.js"
 *           data-hotel-id="HOTEL_PUBLIC_ID" async></script>
 *
 * The loader reads its configuration from its own <script> tag:
 *   data-hotel-id  (required) the hotel's PUBLIC id (hotels.public_id) —
 *                  never the internal numeric id.
 *   data-api-base  (optional) API origin; defaults to the origin the
 *                  script itself was loaded from.
 *   data-title     (optional) launcher label, default "Chat with us".
 *
 * It injects a launcher button and an expandable panel whose <iframe>
 * loads {api-base}/widget/chat.html?hotel=<public_id>. All chat traffic
 * goes to the public widget API (POST {api-base}/api/v1/public/chat);
 * no staff tokens or secrets are involved. Styles are sfw- prefixed and
 * loaded from {api-base}/widget/widget.css.
 * ===================================================================== */

(function () {
  if (window.__stayflowWidgetLoaded) return;
  window.__stayflowWidgetLoaded = true;

  var script =
    document.currentScript ||
    document.querySelector("script[data-hotel-id][src*='widget']");
  if (!script) return;

  var publicId = script.getAttribute("data-hotel-id");
  if (!publicId) {
    if (window.console) console.warn("StayFlow widget: data-hotel-id is missing.");
    return;
  }
  var scriptUrl;
  try {
    scriptUrl = new URL(script.getAttribute("src"), window.location.href);
  } catch (e) {
    return;
  }
  var apiBase = (
    script.getAttribute("data-api-base") || scriptUrl.origin
  ).replace(/\/+$/, "");
  var title = script.getAttribute("data-title") || "Chat with us";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  ready(function () {
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = apiBase + "/widget/widget.css";
    document.head.appendChild(link);

    var launcher = document.createElement("button");
    launcher.type = "button";
    launcher.className = "sfw-launcher";
    launcher.setAttribute("aria-expanded", "false");
    launcher.setAttribute("aria-controls", "sfw-panel");
    launcher.textContent = "💬 " + title;

    var panel = document.createElement("div");
    panel.className = "sfw-panel";
    panel.id = "sfw-panel";
    panel.hidden = true;

    var iframe = document.createElement("iframe");
    iframe.title = title;
    iframe.loading = "lazy";
    iframe.src =
      apiBase +
      "/widget/chat.html?hotel=" +
      encodeURIComponent(publicId) +
      "&api=" +
      encodeURIComponent(apiBase);
    panel.appendChild(iframe);

    launcher.addEventListener("click", function () {
      var open = panel.hidden;
      panel.hidden = !open;
      launcher.setAttribute("aria-expanded", String(open));
    });

    document.body.appendChild(panel);
    document.body.appendChild(launcher);
  });
})();
