"use strict";

const https = require("https");
const swe = require("sweph");

const IST_OFFSET_HOURS = 5.5;
const IST_LABEL = "IST";
const SIGNS = [
  "Aries",
  "Taurus",
  "Gemini",
  "Cancer",
  "Leo",
  "Virgo",
  "Libra",
  "Scorpio",
  "Sagittarius",
  "Capricorn",
  "Aquarius",
  "Pisces",
];

// Privacy-preserving chart anchors derived once from Shiva's Vedic birth chart.
// The source birth date, time, and birthplace are intentionally not stored here.
const NATAL = Object.freeze({
  ascendant: 222.569802,
  moon: 271.980834,
  sun: 77.918175,
  mercury: 93.955992,
  mars: 102.117695,
  jupiter: 139.796398,
  saturn: 82.234039,
  rahu: 15.281023,
  mahadasha: "Rahu",
  antardasha: "Rahu",
});

const PLANETS = Object.freeze({
  sun: swe.constants.SE_SUN,
  moon: swe.constants.SE_MOON,
  mercury: swe.constants.SE_MERCURY,
  venus: swe.constants.SE_VENUS,
  mars: swe.constants.SE_MARS,
  jupiter: swe.constants.SE_JUPITER,
  saturn: swe.constants.SE_SATURN,
  rahu: swe.constants.SE_TRUE_NODE,
});

const WEEKDAY_RULERS = [
  "Sun",
  "Moon",
  "Mars",
  "Mercury",
  "Jupiter",
  "Venus",
  "Saturn",
];
const HORA_SEQUENCE = [
  "Saturn",
  "Jupiter",
  "Mars",
  "Sun",
  "Venus",
  "Mercury",
  "Moon",
];
const RAHU_KALAM_INDEX = [7, 1, 6, 4, 5, 3, 2];

function normalizeDegrees(value) {
  return ((value % 360) + 360) % 360;
}

function houseFrom(reference, transit) {
  return Math.floor(normalizeDegrees(transit - reference) / 30) + 1;
}

function signName(longitude) {
  return SIGNS[Math.floor(normalizeDegrees(longitude) / 30)];
}

function parseForecastDate() {
  const override = process.env.ASTROLOGY_DATE?.trim();
  if (override) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(override);
    if (!match) {
      throw new Error("ASTROLOGY_DATE must use YYYY-MM-DD.");
    }
    return {
      year: Number(match[1]),
      month: Number(match[2]),
      day: Number(match[3]),
    };
  }

  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return {
    year: Number(values.year),
    month: Number(values.month),
    day: Number(values.day),
  };
}

function utcDateForIstHour(date, istHour) {
  return new Date(
    Date.UTC(
      date.year,
      date.month - 1,
      date.day,
      Math.floor(istHour - IST_OFFSET_HOURS),
      Math.round(((istHour - IST_OFFSET_HOURS) % 1) * 60),
    ),
  );
}

function dateSeed(date) {
  return date.year * 10000 + date.month * 100 + date.day;
}

function pick(items, seed, salt = 0) {
  return items[Math.abs(seed * 31 + salt * 17) % items.length];
}

function getTransits(date, istHour = 7) {
  swe.set_sid_mode(swe.constants.SE_SIDM_LAHIRI, 0, 0);
  const utc = utcDateForIstHour(date, istHour);
  const hour =
    utc.getUTCHours() +
    utc.getUTCMinutes() / 60 +
    utc.getUTCSeconds() / 3600;
  const jd = swe.julday(
    utc.getUTCFullYear(),
    utc.getUTCMonth() + 1,
    utc.getUTCDate(),
    hour,
    swe.constants.SE_GREG_CAL,
  );
  const flags =
    swe.constants.SEFLG_MOSEPH |
    swe.constants.SEFLG_SPEED |
    swe.constants.SEFLG_SIDEREAL;

  return Object.fromEntries(
    Object.entries(PLANETS).map(([name, id]) => {
      const result = swe.calc_ut(jd, id, flags);
      if (!result?.data || result.error) {
        throw new Error(`Swiss Ephemeris failed for ${name}: ${result?.error}`);
      }
      return [
        name,
        {
          longitude: normalizeDegrees(result.data[0]),
          speed: result.data[3],
        },
      ];
    }),
  );
}

function weekdayIndex(date) {
  return new Date(Date.UTC(date.year, date.month - 1, date.day)).getUTCDay();
}

function formatHour(decimalHour) {
  const totalMinutes = Math.round(decimalHour * 60);
  const hours = Math.floor(totalMinutes / 60) % 24;
  const minutes = totalMinutes % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function rahuKalam(date) {
  const start = 6 + (RAHU_KALAM_INDEX[weekdayIndex(date)] - 1) * 1.5;
  return { start, end: start + 1.5 };
}

function overlaps(left, right) {
  return left.start < right.end && right.start < left.end;
}

function favourableWindow(date, seed, focus) {
  const dayRuler = WEEKDAY_RULERS[weekdayIndex(date)];
  const startIndex = HORA_SEQUENCE.indexOf(dayRuler);
  const caution = rahuKalam(date);
  const weights =
    focus === "study"
      ? { Mercury: 5, Jupiter: 4, Sun: 3, Moon: 2, Venus: 1 }
      : { Jupiter: 5, Mercury: 4, Moon: 3, Venus: 2, Sun: 2 };

  const candidates = [];
  for (let hour = 7; hour < 20; hour += 1) {
    const ruler = HORA_SEQUENCE[(startIndex + (hour - 6)) % 7];
    const window = { start: hour, end: hour + 1 };
    if (!overlaps(window, caution)) {
      candidates.push({
        ...window,
        ruler,
        score: weights[ruler] || 0,
      });
    }
  }
  candidates.sort(
    (a, b) =>
      b.score - a.score ||
      ((a.start + seed) % 5) - ((b.start + seed) % 5) ||
      a.start - b.start,
  );
  return candidates[0];
}

function scoreDay(transits) {
  const moonFromMoon = houseFrom(NATAL.moon, transits.moon.longitude);
  const moonFromAsc = houseFrom(NATAL.ascendant, transits.moon.longitude);
  const mercuryFromAsc = houseFrom(
    NATAL.ascendant,
    transits.mercury.longitude,
  );
  const jupiterFromMoon = houseFrom(
    NATAL.moon,
    transits.jupiter.longitude,
  );
  const saturnFromMoon = houseFrom(
    NATAL.moon,
    transits.saturn.longitude,
  );

  const goodMoonHouses = new Set([1, 3, 6, 7, 10, 11]);
  const cautionMoonHouses = new Set([4, 8, 12]);
  const goodAscHouses = new Set([1, 5, 9, 10, 11]);
  const cautionAscHouses = new Set([6, 8, 12]);
  const goodMercuryHouses = new Set([1, 2, 5, 9, 10, 11]);
  const goodJupiterHouses = new Set([2, 5, 7, 9, 11]);

  let overall = 0;
  overall += goodMoonHouses.has(moonFromMoon)
    ? 2
    : cautionMoonHouses.has(moonFromMoon)
      ? -2
      : 0;
  overall += goodAscHouses.has(moonFromAsc)
    ? 1
    : cautionAscHouses.has(moonFromAsc)
      ? -1
      : 0;

  const study =
    (goodMercuryHouses.has(mercuryFromAsc) ? 2 : -1) +
    (goodJupiterHouses.has(jupiterFromMoon) ? 2 : 0) +
    (moonFromAsc === 5 || moonFromAsc === 9 ? 1 : 0);
  const discipline =
    overall -
    (moonFromMoon === 8 || moonFromMoon === 12 ? 1 : 0) -
    (saturnFromMoon === 1 || saturnFromMoon === 8 ? 1 : 0);
  const energy =
    (goodAscHouses.has(moonFromAsc) ? 2 : 0) -
    (cautionAscHouses.has(moonFromAsc) ? 2 : 0) -
    (saturnFromMoon === 1 ? 1 : 0);

  return {
    overall,
    study,
    discipline,
    energy,
    moonFromMoon,
    moonFromAsc,
    mercuryFromAsc,
    jupiterFromMoon,
    moonSign: signName(transits.moon.longitude),
  };
}

function buildGuidance(date, transits) {
  const seed = dateSeed(date);
  const score = scoreDay(transits);

  const overall =
    score.overall >= 2
      ? pick(
          [
            "A constructive day for steady progress. Confidence is useful when it stays attached to a clear plan.",
            "Momentum is supportive today. Keep the pace controlled and finish priority work before expanding the list.",
            "Clarity improves when you work in sequence. Use the stronger periods for decisions and the rest for execution.",
          ],
          seed,
          1,
        )
      : score.overall <= -2
        ? pick(
            [
              "A mixed, reactive day. Slow the decision cycle and leave extra room to verify assumptions.",
              "Today rewards restraint more than speed. Protect attention from noise and avoid forcing an outcome.",
              "Energy may feel uneven. Keep plans simple and postpone optional high-pressure decisions.",
            ],
            seed,
            2,
          )
        : pick(
            [
              "A balanced day with useful openings, provided you do not rush the first impression.",
              "Progress is available through consistency rather than intensity. Keep expectations realistic.",
              "The day is workable but not automatic—structure and patience will matter more than motivation.",
            ],
            seed,
            3,
          );

  const study =
    score.study >= 3
      ? pick(
          [
            "Good for difficult numerical work, revision, and completing a pending technical topic. Start with the hardest task.",
            "Strong learning window for focused study and problem-solving. Use active recall instead of passive reading.",
            "Career planning and technical study are favoured. Convert one important idea into a finished output.",
          ],
          seed,
          4,
        )
      : score.study <= 0
        ? pick(
            [
              "Concentration may scatter. Use short study blocks, written targets, and revision instead of starting too many new topics.",
              "Keep the study plan lighter and specific. One completed topic is better than several half-started ones.",
              "Double-check calculations and instructions. Save major career decisions for after a calm review.",
            ],
            seed,
            5,
          )
        : pick(
            [
              "Suitable for routine study, revision, and clearing backlog. Keep the phone away during the main session.",
              "Steady progress is possible. Use a checklist and close one task before moving to the next.",
              "A practical day for notes, PYQs, and follow-up work. Avoid changing the plan midway without a clear reason.",
            ],
            seed,
            6,
          );

  const trading =
    score.discipline >= 2
      ? pick(
          [
            "Discipline can stay strong if rules are written before entry. Take only validated setups and keep normal position size.",
            "Good for calm execution, not aggression. Let setup, stop-loss, and fixed risk decide whether a trade exists.",
            "Patience is the advantage today. Wait for confirmation and do not increase risk because the first trade works.",
          ],
          seed,
          7,
        )
      : score.discipline <= -2
        ? pick(
            [
              "Higher risk of impulsive entries or revenge trading. Reduce activity, avoid leverage changes, and skip unclear setups.",
              "Do not trade to recover a loss or relieve boredom. A no-trade decision is valid when the checklist is incomplete.",
              "Protect capital from emotional decisions. Keep size conservative and stop after a rule-breaking impulse appears.",
            ],
            seed,
            8,
          )
        : pick(
            [
              "Use normal risk only and verify the setup twice. Avoid adding to a position without a prewritten rule.",
              "Trading conditions are neutral from a discipline perspective. Let price action and your checklist make the decision.",
              "Keep execution mechanical: planned entry, fixed stop, fixed size. Avoid reacting to fast candles.",
            ],
            seed,
            9,
          );

  const health =
    score.energy >= 2
      ? "Energy is generally supportive. Use the stronger part of the day for demanding work, but still take screen and hydration breaks."
      : score.energy <= -1
        ? "Energy may fluctuate. Keep meals, hydration, sleep, and screen breaks regular; do not push through obvious fatigue."
        : "Energy looks moderate. A steady routine, hydration, and brief movement breaks should help maintain focus.";

  const focus = score.study >= score.discipline ? "study" : "general";
  const favourable = favourableWindow(date, seed, focus);
  const caution = rahuKalam(date);

  const doToday =
    score.discipline <= -2
      ? "Write the risk and invalidation level before any order; finish one priority study task."
      : score.study >= 3
        ? "Use the best focus window for your hardest topic, then review every trade decision against the checklist."
        : "Complete one pending task and keep every money decision inside your normal rules.";
  const avoidToday =
    score.discipline <= -2
      ? "Revenge trading, sudden leverage changes, and decisions made to escape frustration."
      : score.study <= 0
        ? "Multitasking, abandoning the plan too early, and taking a trade without full confirmation."
        : "Overconfidence after early progress and increasing position size outside the risk plan.";

  return {
    overall,
    study,
    trading,
    health,
    doToday,
    avoidToday,
    favourable: `${formatHour(favourable.start)}–${formatHour(favourable.end)} ${IST_LABEL}`,
    caution: `${formatHour(caution.start)}–${formatHour(caution.end)} ${IST_LABEL}`,
    diagnostic: {
      ...score,
      dasha: `${NATAL.mahadasha}–${NATAL.antardasha}`,
      favourableHora: favourable.ruler,
    },
  };
}

function displayDate(date) {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(Date.UTC(date.year, date.month - 1, date.day, 6)));
}

function buildDiscordPayload(date, guidance) {
  return {
    username: "Shiva Daily Astrology",
    embeds: [
      {
        title: `🔮 Shiva’s Daily Astrology — ${displayDate(date)}`,
        color:
          guidance.diagnostic.overall >= 2
            ? 0x3ba55c
            : guidance.diagnostic.overall <= -2
              ? 0xed4245
              : 0x5865f2,
        fields: [
          { name: "Overall", value: guidance.overall },
          { name: "📚 Study & Career", value: guidance.study },
          {
            name: "💰 Money & Trading Discipline",
            value: guidance.trading,
          },
          { name: "⚡ Health & Energy", value: guidance.health },
          {
            name: "🕒 Favourable Period",
            value: guidance.favourable,
            inline: true,
          },
          {
            name: "⚠️ Caution Period",
            value: guidance.caution,
            inline: true,
          },
          { name: "✅ Do Today", value: guidance.doToday },
          { name: "⛔ Avoid Today", value: guidance.avoidToday },
        ],
        footer: {
          text: "Reflection only—not a trade signal. Use your setup, stop-loss and position-size rules.",
        },
      },
    ],
  };
}

function postJson(url, payload, attempt = 1) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(payload);
    const request = https.request(
      url,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
        },
        timeout: 15000,
      },
      (response) => {
        let responseBody = "";
        response.on("data", (chunk) => {
          responseBody += chunk;
        });
        response.on("end", async () => {
          if (response.statusCode === 429 && attempt < 6) {
            let retryAfterMs = 1000;
            try {
              const parsed = JSON.parse(responseBody);
              retryAfterMs = Math.max(
                250,
                Math.min(Number(parsed.retry_after || 1) * 1000, 30000),
              );
            } catch {
              // Use the default delay.
            }
            await new Promise((done) => setTimeout(done, retryAfterMs));
            resolve(postJson(url, payload, attempt + 1));
            return;
          }
          if (response.statusCode < 200 || response.statusCode >= 300) {
            reject(
              new Error(
                `Discord returned ${response.statusCode}: ${responseBody.slice(0, 300)}`,
              ),
            );
            return;
          }
          resolve();
        });
      },
    );
    request.on("timeout", () => {
      request.destroy(new Error("Discord request timed out."));
    });
    request.on("error", reject);
    request.write(body);
    request.end();
  });
}

async function main() {
  const date = parseForecastDate();
  const transits = getTransits(date);
  const guidance = buildGuidance(date, transits);
  const payload = buildDiscordPayload(date, guidance);

  console.log(JSON.stringify(payload, null, 2));
  console.log("Diagnostic:", JSON.stringify(guidance.diagnostic));

  if (process.env.ASTROLOGY_DRY_RUN === "true") {
    console.log("Dry run enabled; Discord post skipped.");
    return;
  }

  const webhook = process.env.DISCORD_ASTROLOGY_WEBHOOK_URL?.trim();
  if (!webhook) {
    throw new Error("DISCORD_ASTROLOGY_WEBHOOK_URL is not configured.");
  }
  await postJson(webhook, payload);
  console.log("Daily astrology briefing sent.");
}

main().catch((error) => {
  console.error(error.stack || error.message || error);
  process.exitCode = 1;
});
