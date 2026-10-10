import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import worker from "./src/index.mjs";

const originalFetch = globalThis.fetch;
const env = {
  GITHUB_DISPATCH_TOKEN: "test-token",
  TELEGRAM_WEBHOOK_SECRET: "test-secret",
  TELEGRAM_CHAT_ID: "123",
};

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function telegramRequest(text, chatId = 123, secret = "test-secret") {
  return new Request("https://worker.example/", {
    method: "POST",
    headers: { "X-Telegram-Bot-Api-Secret-Token": secret },
    body: JSON.stringify({ message: { chat: { id: chatId, type: "private" }, text } }),
  });
}

test("only /update from the configured private chat starts GitHub", async () => {
  const calls = [];
  globalThis.fetch = async (...args) => {
    calls.push(args);
    return new Response(null, { status: 204 });
  };

  assert.equal((await worker.fetch(telegramRequest("/update"), env)).status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1].method, "POST");
  assert.equal(JSON.parse(calls[0][1].body).event_type, "telegram_update");

  assert.equal((await worker.fetch(telegramRequest("/update", 456), env)).status, 200);
  assert.equal((await worker.fetch(telegramRequest("hello"), env)).status, 200);
  assert.equal((await worker.fetch(telegramRequest("/update", 123, "wrong"), env)).status, 403);
  assert.equal(calls.length, 1);
});

test("GitHub failure lets Telegram retry the command", async () => {
  globalThis.fetch = async () => new Response("error", { status: 500 });
  assert.equal((await worker.fetch(telegramRequest("/update"), env)).status, 503);
});

test("scheduled trigger runs a check without a Telegram report", async () => {
  let eventType;
  globalThis.fetch = async (_url, options) => {
    eventType = JSON.parse(options.body).event_type;
    return new Response(null, { status: 204 });
  };
  await worker.scheduled({}, env);
  assert.equal(eventType, "scheduled_check");
});

test("/id returns only the sender's chat ID", async () => {
  globalThis.fetch = async () => { throw new Error("GitHub should not be called"); };
  const response = await worker.fetch(telegramRequest("/id", 456), env);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    method: "sendMessage",
    chat_id: 456,
    text: "Jouw chat-ID: 456",
  });
});
