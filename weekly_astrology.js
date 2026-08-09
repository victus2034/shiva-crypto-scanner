"use strict";

const {
  buildWeeklyPayload,
  parseWeekStart,
  postJson,
} = require("./astrology_engine");

async function main() {
  const weekStart = parseWeekStart();
  const { payload, diagnostics } = buildWeeklyPayload(weekStart);

  console.log(JSON.stringify(payload, null, 2));
  console.log("Diagnostic:", JSON.stringify(diagnostics));

  if (process.env.ASTROLOGY_DRY_RUN === "true") {
    console.log("Dry run enabled; Discord post skipped.");
    return;
  }

  const webhook = process.env.DISCORD_ASTROLOGY_WEBHOOK_URL?.trim();
  if (!webhook) {
    throw new Error("DISCORD_ASTROLOGY_WEBHOOK_URL is not configured.");
  }

  await postJson(webhook, payload);
  console.log("Weekly astrology briefing sent.");
}

main().catch((error) => {
  console.error(error.stack || error.message || error);
  process.exitCode = 1;
});
