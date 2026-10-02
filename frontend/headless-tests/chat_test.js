/* Headless functional test of frontend/app.js using jsdom.
 * Exercises: fullpage init, sendMessage round-trip with stubbed fetch,
 * quote card from get_room_rate tool_trace, draft card + confirm chips
 * from preview_booking tool_trace, degraded note, sessionStorage
 * conversation id, error+retry path, widget mode init.
 */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const assert = require("assert");

const appJs = fs.readFileSync(
  "/home/hatch/workspace/stayflow-ai-work/frontend/app.js",
  "utf8"
);

function makeDom() {
  const dom = new JSDOM(
    `<!DOCTYPE html><html><body><div id="stayflow-chat-root"></div></body></html>`,
    { url: "http://localhost/", runScripts: "outside-only" }
  );
  return dom;
}

const RATE_TRACE = {
  tool: "get_room_rate",
  arguments: { room_id: 3 },
  ok: true,
  result: {
    room_id: 3,
    room_type: "Deluxe King",
    check_in: "2026-10-05",
    check_out: "2026-10-07",
    currency: "INR",
    nights: [
      { date: "2026-10-05", price: "4500.00" },
      { date: "2026-10-06", price: "4500.00" },
    ],
    total: "9000.00",
    missing_dates: [],
    fully_priced: true,
    error: null,
  },
};

const DRAFT_TRACE = {
  tool: "preview_booking",
  arguments: { room_id: 3 },
  ok: true,
  result: {
    draft_id: 42,
    expires_at: "2026-09-29T15:30:00",
    message: "Booking draft created.",
    details: {
      room_type: "Deluxe King",
      check_in: "2026-10-05",
      check_out: "2026-10-07",
      number_of_guests: 2,
      total_price: "9000.00",
      currency: "INR",
    },
    error: null,
  },
};

function chatResponse(reply, traces, degraded) {
  return {
    ok: true,
    status: 200,
    json: () =>
      Promise.resolve({
        reply,
        conversation_id: 777,
        iterations: 2,
        degraded: !!degraded,
        tool_trace: traces,
      }),
  };
}

async function tick(ms = 30) {
  return new Promise((r) => setTimeout(r, ms));
}

(async () => {
  // ---------- fullpage mode ----------
  let dom = makeDom();
  const { window } = dom;
  const sentBodies = [];
  window.fetch = (url, opts) => {
    sentBodies.push({ url, body: JSON.parse(opts.body) });
    const msg = JSON.parse(opts.body).message;
    if (msg.includes("rate for deluxe"))
      return Promise.resolve(
        chatResponse("Here is the rate.", [RATE_TRACE], false)
      );
    if (msg.includes("book it"))
      return Promise.resolve(
        chatResponse("Here's your booking summary: … Shall I confirm this booking?", [DRAFT_TRACE], false)
      );
    if (msg.includes("degraded please"))
      return Promise.resolve(chatResponse("Offline answer.", [], true));
    if (msg.includes("boom"))
      return Promise.reject(new Error("network down"));
    return Promise.resolve(chatResponse("Plain reply.", [], false));
  };
  dom.window.eval(appJs);
  assert.ok(dom.window.StayFlowChat, "StayFlowChat global exists");

  const api = dom.window.StayFlowChat.init({
    hotelId: 1,
    hotelName: "StayFlow Grand Hotel",
    apiBase: "http://127.0.0.1:8123",
    mode: "fullpage",
  });
  const doc = window.document;

  const input = doc.querySelector(".sf-input");
  const form = doc.querySelector(".sf-composer form");
  async function send(text) {
    input.value = text;
    form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
    await tick(60);
  }

  // 1. plain reply, no cards
  await send("hello");
  let agents = doc.querySelectorAll(".message.agent");
  assert.strictEqual(agents.length, 1, "one agent message");
  assert.strictEqual(doc.querySelectorAll(".sf-card").length, 0, "no cards for plain reply");
  assert.strictEqual(
    window.sessionStorage.getItem("stayflow_conversation_id_1"),
    "777",
    "conversation id persisted in sessionStorage"
  );
  assert.strictEqual(sentBodies[0].body.hotel_id, 1, "hotel_id sent");
  assert.strictEqual(sentBodies[0].body.channel, "web", "channel sent");

  // 2. rate quote card from tool_trace
  await send("rate for deluxe");
  assert.strictEqual(sentBodies[1].body.conversation_id, 777, "conversation id reused");
  const quote = doc.querySelector(".sf-card.sf-quote");
  assert.ok(quote, "quote card rendered");
  const quoteText = quote.textContent;
  assert.ok(quoteText.includes("Deluxe King"), "quote shows room type");
  assert.ok(quoteText.includes("9,000"), "quote shows total, got: " + quoteText);
  assert.ok(quoteText.includes("2"), "quote shows nights");

  // 3. draft card + confirm chips from preview_booking trace
  await send("book it");
  const draft = doc.querySelector(".sf-card.sf-draft");
  assert.ok(draft, "draft card rendered");
  assert.ok(draft.textContent.includes("Deluxe King"), "draft shows room type");
  assert.ok(draft.textContent.includes("Nothing is booked yet"), "draft honesty note");
  const chips = [...doc.querySelectorAll(".sf-chip")].map((c) => c.textContent);
  assert.deepStrictEqual(chips, ["Yes, confirm", "No, don't confirm"], "confirm/cancel chips shown");

  // clicking "Yes, confirm" sends the confirmation message
  const before = sentBodies.length;
  doc.querySelectorAll(".sf-chip")[0].click();
  await tick(60);
  assert.strictEqual(sentBodies.length, before + 1, "chip click sent a message");
  assert.ok(
    sentBodies[before].body.message.toLowerCase().includes("confirm"),
    "chip message is a confirmation"
  );

  // 4. degraded note
  await send("degraded please");
  const degraded = doc.querySelector(".sf-degraded");
  assert.ok(degraded && degraded.textContent.includes("offline mode"), "degraded note shown");

  // 5. error + retry
  await send("boom");
  assert.ok(doc.querySelector(".message.error"), "error message shown");
  const failedCount = sentBodies.length;
  // make retry succeed
  window.fetch = (url, opts) => {
    sentBodies.push({ url, body: JSON.parse(opts.body) });
    return Promise.resolve(chatResponse("Recovered.", [], false));
  };
  doc.querySelector(".sf-retry").click();
  await tick(60);
  assert.strictEqual(sentBodies.length, failedCount + 1, "retry re-sent the message");
  assert.strictEqual(
    sentBodies[failedCount].body.message,
    "boom",
    "retry sent the original text"
  );

  // 6. new chat resets conversation
  doc.querySelector(".sf-btn-ghost").click();
  assert.strictEqual(
    window.sessionStorage.getItem("stayflow_conversation_id_1"),
    null,
    "conversation id cleared on new chat"
  );

  // 7. malformed trace -> plain text fallback, no crash
  window.fetch = () =>
    Promise.resolve(
      chatResponse("Reply with bad trace.", [{ tool: "get_room_rate", ok: true, result: { junk: 1 } }], false)
    );
  await send("bad trace");
  assert.strictEqual(doc.querySelectorAll(".sf-card").length, 0, "malformed trace produced no card");

  console.log("FULLPAGE: all assertions passed");

  // ---------- widget mode ----------
  dom = makeDom();
  const w2 = dom.window;
  w2.fetch = () => Promise.resolve(chatResponse("Hi from widget.", [], false));
  w2.eval(appJs);
  const wapi = w2.StayFlowChat.init({ hotelId: 5, hotelName: "Widget Hotel", mode: "widget" });
  const wdoc = w2.document;
  assert.ok(wdoc.querySelector(".sf-launcher"), "launcher rendered");
  assert.ok(wdoc.querySelector(".sf-panel").hidden, "panel starts hidden");
  wdoc.querySelector(".sf-launcher").click();
  assert.ok(!wdoc.querySelector(".sf-panel").hidden, "panel opens on launcher click");
  assert.strictEqual(
    wdoc.querySelector(".sf-launcher").getAttribute("aria-expanded"),
    "true",
    "aria-expanded toggles"
  );
  // widget chat sends with hotel 5
  let widgetBody = null;
  w2.fetch = (url, opts) => {
    widgetBody = JSON.parse(opts.body);
    return Promise.resolve(chatResponse("ok", [], false));
  };
  const winput = wdoc.querySelector(".sf-panel .sf-input");
  winput.value = "hi widget";
  wdoc.querySelector(".sf-panel form").dispatchEvent(new w2.Event("submit", { bubbles: true, cancelable: true }));
  await tick(60);
  assert.strictEqual(widgetBody.hotel_id, 5, "widget uses configured hotel");
  // Escape closes
  wdoc.querySelector(".sf-panel").dispatchEvent(
    new w2.KeyboardEvent("keydown", { key: "Escape", bubbles: true })
  );
  assert.ok(wdoc.querySelector(".sf-panel").hidden, "Escape closes panel");
  console.log("WIDGET: all assertions passed");

  console.log("CHAT TESTS: ALL PASSED");
})().catch((e) => {
  console.error("CHAT TEST FAILED:", e.message);
  process.exit(1);
});
