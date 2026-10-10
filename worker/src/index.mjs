const DISPATCH_URL = "https://api.github.com/repos/YanickAnnema/utrecht-vrije-sector-monitor/dispatches";

function dispatch(env, eventType) {
  return fetch(DISPATCH_URL, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
      "Content-Type": "application/json",
      "User-Agent": "utrecht-woningalert-webhook",
    },
    body: JSON.stringify({ event_type: eventType }),
  });
}

export default {
  async scheduled(_controller, env) {
    if (!env.GITHUB_DISPATCH_TOKEN || !(await dispatch(env, "scheduled_check")).ok) {
      throw new Error("Scheduled GitHub dispatch failed");
    }
  },

  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Not found", { status: 404 });
    }
    if (!env.GITHUB_DISPATCH_TOKEN || !env.TELEGRAM_WEBHOOK_SECRET || !env.TELEGRAM_CHAT_ID) {
      return new Response("Not configured", { status: 503 });
    }
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TELEGRAM_WEBHOOK_SECRET) {
      return new Response("Forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("Invalid JSON", { status: 400 });
    }
    const message = update?.message;
    if (message?.chat?.type !== "private") {
      return new Response("OK");
    }
    const command = message?.text?.trim().toLowerCase();
    if (command === "/id" || command === "/id@utrecht_woningalert_bot") {
      return new Response(JSON.stringify({
        method: "sendMessage",
        chat_id: message.chat.id,
        text: `Jouw chat-ID: ${message.chat.id}`,
      }), { headers: { "Content-Type": "application/json" } });
    }
    if (String(message.chat.id) !== env.TELEGRAM_CHAT_ID) {
      return new Response("OK");
    }
    if (command !== "/update" && command !== "/update@utrecht_woningalert_bot") {
      return new Response("OK");
    }

    const response = await dispatch(env, "telegram_update");
    if (!response.ok) {
      return new Response("GitHub unavailable", { status: 503 });
    }
    return new Response("OK");
  },
};
