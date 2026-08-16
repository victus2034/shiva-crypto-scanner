"use strict";

const https = require("https");
const swe = require("sweph");

const IST_OFFSET_HOURS = 5.5;
const IST_LABEL = "IST";
const MS_PER_DAY = 24 * 60 * 60 * 1000;
const YEAR_DAYS = 365.2425;
const JABALPUR = Object.freeze({ latitude: 23.1815, longitude: 79.9864 });

const SIGNS = Object.freeze([
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
]);

const NAKSHATRAS = Object.freeze([
  "Ashwini",
  "Bharani",
  "Krittika",
  "Rohini",
  "Mrigashira",
  "Ardra",
  "Punarvasu",
  "Pushya",
  "Ashlesha",
  "Magha",
  "Purva Phalguni",
  "Uttara Phalguni",
  "Hasta",
  "Chitra",
  "Swati",
  "Vishakha",
  "Anuradha",
  "Jyeshtha",
  "Mula",
  "Purva Ashadha",
  "Uttarashadha",
  "Shravana",
  "Dhanishta",
  "Shatabhisha",
  "Purva Bhadrapada",
  "Uttara Bhadrapada",
  "Revati",
]);

const NAKSHATRA_LORDS = Object.freeze([
  "Ketu",
  "Venus",
  "Sun",
  "Moon",
  "Mars",
  "Rahu",
  "Jupiter",
  "Saturn",
  "Mercury",
]);

const DASHA_YEARS = Object.freeze({
  Ketu: 7,
  Venus: 20,
  Sun: 6,
  Moon: 10,
  Mars: 7,
  Rahu: 18,
  Jupiter: 16,
  Saturn: 19,
  Mercury: 17,
});

const DASHA_ORDER = Object.freeze([
  "Ketu",
  "Venus",
  "Sun",
  "Moon",
  "Mars",
  "Rahu",
  "Jupiter",
  "Saturn",
  "Mercury",
]);

const WEEKDAY_RULERS = Object.freeze([
  "Sun",
  "Moon",
  "Mars",
  "Mercury",
  "Jupiter",
  "Venus",
  "Saturn",
]);
const HORA_SEQUENCE = Object.freeze([
  "Saturn",
  "Jupiter",
  "Mars",
  "Sun",
  "Venus",
  "Mercury",
  "Moon",
]);

// Sunday..Saturday. Traditional Rahu Kalam daylight section numbers.
const RAHU_KALAM_SECTION = Object.freeze([8, 2, 7, 5, 6, 4, 3]);

const NATAL_DISPLAY_REFERENCE = Object.freeze({
  birthUtc: Date.UTC(2004, 6, 3, 10, 50), // 03 Jul 2004 16:20 IST.
  ascendant: 222 + 32 / 60,
  moon: 270 + 1 + 58 / 60,
  sun: 60 + 17 + 56 / 60,
  mars: 90 + 12 + 7 / 60,
  mercury: 90 + 3 + 58 / 60,
  jupiter: 120 + 19 + 48 / 60,
  venus: 30 + 15 + 57 / 60,
  saturn: 60 + 22 + 14 / 60,
  rahu: 14 + 1 / 60,
  ketu: 180 + 14 + 1 / 60,
});

const NATAL = Object.freeze(buildNatalLongitudes());

const PLANETS = Object.freeze({
  sun: swe.constants.SE_SUN,
  moon: swe.constants.SE_MOON,
  mars: swe.constants.SE_MARS,
  mercury: swe.constants.SE_MERCURY,
  jupiter: swe.constants.SE_JUPITER,
  venus: swe.constants.SE_VENUS,
  saturn: swe.constants.SE_SATURN,
  rahu: swe.constants.SE_MEAN_NODE,
});

const SECTOR_THEME_THRESHOLD = 3;

const SECTOR_THEME_DEFINITIONS = Object.freeze({
  "Technology / Communication": Object.freeze([
    houseFactor("mercury", "houseFromLagna", [3, 10, 11], 2),
    houseFactor("mercury", "houseFromLagna", [8, 12], -2),
    dashaFactor("Rahu", 1),
  ]),
  "Banking / Financials": Object.freeze([
    houseFactor("jupiter", "houseFromMoon", [2, 9, 11], 2),
    houseFactor("jupiter", "houseFromMoon", [6, 8, 12], -1),
    dashaFactor("Jupiter", 1),
  ]),
  Energy: Object.freeze([
    houseFactor("sun", "houseFromLagna", [3, 6, 10, 11], 1),
    houseFactor("mars", "houseFromLagna", [3, 6, 10, 11], 2),
    houseFactor("mars", "houseFromLagna", [8, 12], -2),
  ]),
  "Consumer / Luxury": Object.freeze([
    houseFactor("venus", "houseFromMoon", [2, 5, 9, 11], 2),
    houseFactor("venus", "houseFromMoon", [6, 8, 12], -1),
    houseFactor("moon", "houseFromLagna", [1, 5, 9, 11], 1),
  ]),
  "Metals / Gold": Object.freeze([
    houseFactor("saturn", "houseFromMoon", [3, 6, 11], 1),
    houseFactor("saturn", "houseFromMoon", [4, 8, 12], -1),
    dashaFactor("Saturn", 1),
  ]),
  "Pharma / Healthcare": Object.freeze([
    houseFactor("sun", "houseFromLagna", [1, 6, 10, 11], 1),
    houseFactor("jupiter", "houseFromLagna", [6, 10, 11], 1),
    houseFactor("moon", "houseFromMoon", [1, 5, 9, 11], 1),
  ]),
  "Real Estate": Object.freeze([
    houseFactor("venus", "houseFromLagna", [4, 11], 1),
    houseFactor("rahu", "houseFromLagna", [4, 10], -1),
  ]),
  Automobiles: Object.freeze([
    houseFactor("mars", "houseFromLagna", [3, 6, 11], 1),
    houseFactor("venus", "houseFromMoon", [2, 5, 9, 11], 1),
    houseFactor("sun", "houseFromLagna", [3, 10, 11], 1),
  ]),
});

function houseFactor(planet, relation, houses, score) {
  return Object.freeze({ type: "house", planet, relation, houses, score });
}

function dashaFactor(lord, score) {
  return Object.freeze({ type: "dasha", lord, score });
}

function normalizeDegrees(value) {
  return ((value % 360) + 360) % 360;
}

function buildNatalLongitudes() {
  swe.set_sid_mode(swe.constants.SE_SIDM_LAHIRI, 0, 0);
  const jd = julianDayForIst({ year: 2004, month: 7, day: 3 }, 16 + 20 / 60);
  const flags =
    swe.constants.SEFLG_MOSEPH |
    swe.constants.SEFLG_SPEED |
    swe.constants.SEFLG_SIDEREAL;
  const natalPlanets = {
    sun: swe.constants.SE_SUN,
    moon: swe.constants.SE_MOON,
    mars: swe.constants.SE_MARS,
    mercury: swe.constants.SE_MERCURY,
    jupiter: swe.constants.SE_JUPITER,
    venus: swe.constants.SE_VENUS,
    saturn: swe.constants.SE_SATURN,
    rahu: swe.constants.SE_MEAN_NODE,
  };
  const values = { birthUtc: NATAL_DISPLAY_REFERENCE.birthUtc };
  for (const [name, id] of Object.entries(natalPlanets)) {
    const result = swe.calc_ut(jd, id, flags);
    if (!result?.data || result.error) {
      throw new Error(`Swiss Ephemeris failed for natal ${name}: ${result?.error}`);
    }
    values[name] = normalizeDegrees(result.data[0]);
  }
  const houses = swe.houses_ex(
    jd,
    flags,
    JABALPUR.latitude,
    JABALPUR.longitude,
    "W",
  );
  if (!houses?.data?.points || houses.error) {
    throw new Error(`Swiss Ephemeris failed for natal ascendant: ${houses?.error}`);
  }
  values.ascendant = normalizeDegrees(houses.data.points[0]);
  values.ketu = normalizeDegrees(values.rahu + 180);
  return values;
}

function signIndex(longitude) {
  return Math.floor(normalizeDegrees(longitude) / 30);
}

function signName(longitude) {
  return SIGNS[signIndex(longitude)];
}

function houseFromSign(referenceLongitude, transitLongitude) {
  return ((signIndex(transitLongitude) - signIndex(referenceLongitude) + 12) % 12) + 1;
}

function nakshatraDetails(longitude) {
  const nakLength = 360 / 27;
  const padaLength = nakLength / 4;
  const normalized = normalizeDegrees(longitude);
  const index = Math.floor(normalized / nakLength);
  const offset = normalized - index * nakLength;
  return {
    index,
    name: NAKSHATRAS[index],
    pada: Math.floor(offset / padaLength) + 1,
    lord: NAKSHATRA_LORDS[index % 9],
    offset,
    remainingFraction: 1 - offset / nakLength,
  };
}

function parseYmd(value, envName) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    throw new Error(`${envName} must use YYYY-MM-DD.`);
  }
  return {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
  };
}

function parseForecastDate() {
  const override = process.env.ASTROLOGY_DATE?.trim();
  if (override) {
    return parseYmd(override, "ASTROLOGY_DATE");
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

function dateFromUtcMs(ms) {
  const date = new Date(ms);
  return {
    year: date.getUTCFullYear(),
    month: date.getUTCMonth() + 1,
    day: date.getUTCDate(),
  };
}

function dateToUtcMs(date) {
  return Date.UTC(date.year, date.month - 1, date.day);
}

function addDays(date, days) {
  return dateFromUtcMs(dateToUtcMs(date) + days * MS_PER_DAY);
}

function weekdayIndex(date) {
  return new Date(dateToUtcMs(date)).getUTCDay();
}

function utcDateForIstHour(date, istHour) {
  const utcHour = istHour - IST_OFFSET_HOURS;
  const wholeHours = Math.floor(utcHour);
  const minutes = Math.round((utcHour - wholeHours) * 60);
  return new Date(Date.UTC(date.year, date.month - 1, date.day, wholeHours, minutes));
}

function julianDayForIst(date, istHour = 7) {
  const utc = utcDateForIstHour(date, istHour);
  const hour =
    utc.getUTCHours() + utc.getUTCMinutes() / 60 + utc.getUTCSeconds() / 3600;
  return swe.julday(
    utc.getUTCFullYear(),
    utc.getUTCMonth() + 1,
    utc.getUTCDate(),
    hour,
    swe.constants.SE_GREG_CAL,
  );
}

function getTransits(date, istHour = 7) {
  swe.set_sid_mode(swe.constants.SE_SIDM_LAHIRI, 0, 0);
  const jd = julianDayForIst(date, istHour);
  const flags =
    swe.constants.SEFLG_MOSEPH |
    swe.constants.SEFLG_SPEED |
    swe.constants.SEFLG_SIDEREAL;

  const transits = Object.fromEntries(
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
  transits.ketu = {
    longitude: normalizeDegrees(transits.rahu.longitude + 180),
    speed: transits.rahu.speed,
  };
  return transits;
}

function activeDasha(date, istHour = 7) {
  const targetMs = utcDateForIstHour(date, istHour).getTime();
  const natalMoon = nakshatraDetails(NATAL.moon);
  const birthLord = natalMoon.lord;
  const birthLordIndex = DASHA_ORDER.indexOf(birthLord);
  const firstPeriodDays = DASHA_YEARS[birthLord] * natalMoon.remainingFraction * YEAR_DAYS;
  let periodStart = NATAL.birthUtc;
  let periodEnd = periodStart + firstPeriodDays * MS_PER_DAY;
  let orderIndex = birthLordIndex;

  for (let guard = 0; guard < 30; guard += 1) {
    const lord = DASHA_ORDER[orderIndex % DASHA_ORDER.length];
    if (targetMs < periodEnd) {
      return {
        mahadasha: lord,
        antardasha: activeAntardasha(targetMs, lord, periodStart, periodEnd),
        mahadashaStart: new Date(periodStart),
        mahadashaEnd: new Date(periodEnd),
      };
    }

    periodStart = periodEnd;
    orderIndex += 1;
    const nextLord = DASHA_ORDER[orderIndex % DASHA_ORDER.length];
    periodEnd = periodStart + DASHA_YEARS[nextLord] * YEAR_DAYS * MS_PER_DAY;
  }

  throw new Error("Unable to resolve Vimshottari dasha period.");
}

function activeAntardasha(targetMs, mahaLord, mahaStartMs, mahaEndMs) {
  const mahaDuration = mahaEndMs - mahaStartMs;
  let subStart = mahaStartMs;
  let startIndex = DASHA_ORDER.indexOf(mahaLord);
  for (let i = 0; i < DASHA_ORDER.length; i += 1) {
    const lord = DASHA_ORDER[(startIndex + i) % DASHA_ORDER.length];
    const subEnd = subStart + mahaDuration * (DASHA_YEARS[lord] / 120);
    if (targetMs < subEnd) {
      return {
        lord,
        start: new Date(subStart),
        end: new Date(subEnd),
      };
    }
    subStart = subEnd;
  }
  return {
    lord: DASHA_ORDER[(startIndex + DASHA_ORDER.length - 1) % DASHA_ORDER.length],
    start: new Date(subStart),
    end: new Date(mahaEndMs),
  };
}

function dayOfYear(date) {
  const start = Date.UTC(date.year, 0, 0);
  return Math.floor((dateToUtcMs(date) - start) / MS_PER_DAY);
}

function degToRad(value) {
  return (value * Math.PI) / 180;
}

function radToDeg(value) {
  return (value * 180) / Math.PI;
}

function normalizeHours(value) {
  return ((value % 24) + 24) % 24;
}

function solarEventLocalHour(date, isSunrise) {
  const zenith = 90.833;
  const lngHour = JABALPUR.longitude / 15;
  const n = dayOfYear(date);
  const t = n + ((isSunrise ? 6 : 18) - lngHour) / 24;
  const meanAnomaly = 0.9856 * t - 3.289;
  let trueLong =
    meanAnomaly +
    1.916 * Math.sin(degToRad(meanAnomaly)) +
    0.02 * Math.sin(degToRad(2 * meanAnomaly)) +
    282.634;
  trueLong = normalizeDegrees(trueLong);

  let rightAscension = radToDeg(Math.atan(0.91764 * Math.tan(degToRad(trueLong))));
  rightAscension = normalizeDegrees(rightAscension);
  rightAscension +=
    Math.floor(trueLong / 90) * 90 - Math.floor(rightAscension / 90) * 90;
  rightAscension /= 15;

  const sinDeclination = 0.39782 * Math.sin(degToRad(trueLong));
  const cosDeclination = Math.cos(Math.asin(sinDeclination));
  const cosHour =
    (Math.cos(degToRad(zenith)) -
      sinDeclination * Math.sin(degToRad(JABALPUR.latitude))) /
    (cosDeclination * Math.cos(degToRad(JABALPUR.latitude)));

  if (cosHour < -1 || cosHour > 1) {
    throw new Error("Unable to calculate sunrise/sunset for Jabalpur.");
  }

  const localHourAngle = isSunrise
    ? 360 - radToDeg(Math.acos(cosHour))
    : radToDeg(Math.acos(cosHour));
  const localMeanTime =
    localHourAngle / 15 + rightAscension - 0.06571 * t - 6.622;
  const utcHour = normalizeHours(localMeanTime - lngHour);
  return normalizeHours(utcHour + IST_OFFSET_HOURS);
}

function sunTimes(date) {
  return {
    sunrise: solarEventLocalHour(date, true),
    sunset: solarEventLocalHour(date, false),
  };
}

function rahuKalam(date) {
  const { sunrise, sunset } = sunTimes(date);
  const sectionLength = (sunset - sunrise) / 8;
  const section = RAHU_KALAM_SECTION[weekdayIndex(date)];
  const start = sunrise + (section - 1) * sectionLength;
  return {
    start,
    end: start + sectionLength,
    source: "Rahu Kalam",
  };
}

function overlaps(left, right) {
  return left.start < right.end && right.start < left.end;
}

function planetaryHoras(date) {
  const today = sunTimes(date);
  const tomorrow = sunTimes(addDays(date, 1));
  const dayLength = today.sunset - today.sunrise;
  const nightLength = 24 - today.sunset + tomorrow.sunrise;
  const dayRuler = WEEKDAY_RULERS[weekdayIndex(date)];
  const startIndex = HORA_SEQUENCE.indexOf(dayRuler);
  const horas = [];

  for (let i = 0; i < 12; i += 1) {
    const start = today.sunrise + (i * dayLength) / 12;
    horas.push({
      start,
      end: today.sunrise + ((i + 1) * dayLength) / 12,
      ruler: HORA_SEQUENCE[(startIndex + i) % HORA_SEQUENCE.length],
      period: "day",
    });
  }

  for (let i = 0; i < 12; i += 1) {
    const start = today.sunset + (i * nightLength) / 12;
    horas.push({
      start,
      end: today.sunset + ((i + 1) * nightLength) / 12,
      ruler: HORA_SEQUENCE[(startIndex + 12 + i) % HORA_SEQUENCE.length],
      period: "night",
    });
  }

  return horas;
}

function formatHour(decimalHour) {
  const totalMinutes = Math.round(normalizeHours(decimalHour) * 60);
  const hours = Math.floor(totalMinutes / 60) % 24;
  const minutes = totalMinutes % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function formatWindow(window) {
  return `${formatHour(window.start)}-${formatHour(window.end)} ${IST_LABEL}`;
}

function transitDiagnostics(transits) {
  return Object.fromEntries(
    Object.entries(transits).map(([name, planet]) => [
      name,
      {
        longitude: Number(planet.longitude.toFixed(6)),
        sign: signName(planet.longitude),
        houseFromLagna: houseFromSign(NATAL.ascendant, planet.longitude),
        houseFromMoon: houseFromSign(NATAL.moon, planet.longitude),
      },
    ]),
  );
}

function taraBala(moonNakIndex) {
  const natalNak = nakshatraDetails(NATAL.moon).index;
  const count = ((moonNakIndex - natalNak + 27) % 27) + 1;
  const tara = ((count - 1) % 9) + 1;
  return {
    count,
    tara,
    favourable: new Set([2, 4, 6, 8, 9]).has(tara),
  };
}

function chandraBala(moonFromMoon) {
  return new Set([1, 3, 6, 7, 10, 11]).has(moonFromMoon);
}

function addScore(score, amount, reason) {
  score.value += amount;
  score.reasons.push(reason);
}

function evaluateDay(date) {
  const transits = getTransits(date);
  const transit = transitDiagnostics(transits);
  const moonNak = nakshatraDetails(transits.moon.longitude);
  const dasha = activeDasha(date);
  const tara = taraBala(moonNak.index);
  const moonFromMoon = transit.moon.houseFromMoon;
  const moonFromLagna = transit.moon.houseFromLagna;
  const chandra = chandraBala(moonFromMoon);

  const scores = {
    overall: { value: 0, reasons: [] },
    study: { value: 0, reasons: [] },
    money: { value: 0, reasons: [] },
    health: { value: 0, reasons: [] },
    communication: { value: 0, reasons: [] },
  };

  if (chandra) addScore(scores.overall, 2, "Moon support");
  else addScore(scores.overall, -1, "Moon caution");
  if (tara.favourable) addScore(scores.overall, 1, "Tara Bala support");
  else addScore(scores.overall, -1, "Tara Bala caution");
  if ([1, 5, 7, 9, 10, 11].includes(moonFromLagna)) addScore(scores.overall, 1, "Moon from Lagna support");
  if ([6, 8, 12].includes(moonFromLagna)) addScore(scores.overall, -1, "Moon from Lagna caution");
  if (dasha.mahadasha === "Rahu") addScore(scores.overall, -1, "Rahu Mahadasha requires discipline");

  if ([1, 2, 5, 9, 10, 11].includes(transit.mercury.houseFromLagna)) addScore(scores.study, 2, "Mercury supports learning");
  else addScore(scores.study, -1, "Mercury needs review");
  if ([2, 5, 7, 9, 11].includes(transit.jupiter.houseFromMoon)) addScore(scores.study, 2, "Jupiter supports guidance");
  if ([5, 9, 10, 11].includes(moonFromLagna)) addScore(scores.study, 1, "Moon supports focus");
  if (!tara.favourable) addScore(scores.study, -1, "Tara Bala asks repetition");

  if (chandra) addScore(scores.money, 1, "Moon is workable");
  else addScore(scores.money, -1, "Moon is reactive");
  if ([8, 12].includes(transit.mars.houseFromLagna)) addScore(scores.money, -1, "Mars increases impulse");
  if ([4, 8, 12].includes(transit.rahu.houseFromMoon)) addScore(scores.money, -1, "Rahu increases noise");
  if ([3, 6, 10, 11].includes(transit.saturn.houseFromMoon)) addScore(scores.money, 1, "Saturn supports rules");
  if (dasha.mahadasha === "Rahu" && dasha.antardasha.lord === "Rahu") addScore(scores.money, -1, "Rahu/Rahu punishes shortcuts");

  if ([1, 3, 6, 7, 10, 11].includes(moonFromMoon)) addScore(scores.health, 1, "Moon stamina support");
  if ([6, 8, 12].includes(moonFromLagna)) addScore(scores.health, -2, "Body rhythm needs care");
  if ([1, 8, 12].includes(transit.saturn.houseFromMoon)) addScore(scores.health, -1, "Saturn may slow energy");
  if ([3, 6, 11].includes(transit.mars.houseFromLagna)) addScore(scores.health, 1, "Mars supports activity");

  if ([3, 7, 10, 11].includes(transit.mercury.houseFromLagna)) addScore(scores.communication, 2, "Mercury supports follow-up");
  else addScore(scores.communication, -1, "Mercury needs slower replies");
  if ([3, 7, 11].includes(moonFromLagna)) addScore(scores.communication, 1, "Moon supports people");
  if ([2, 8, 12].includes(transit.rahu.houseFromLagna)) addScore(scores.communication, -1, "Rahu can distort tone");
  if (tara.favourable) addScore(scores.communication, 1, "Tara Bala supports timing");

  const timings = {
    sun: sunTimes(date),
    rahuKalam: rahuKalam(date),
    horas: planetaryHoras(date),
  };
  const focus = selectFocus(scores);
  const favourable = selectFavourableWindow(timings.horas, timings.rahuKalam, focus, scores);
  const sectors = sectorThemes(transit, dasha);

  return {
    date,
    transits,
    transit,
    moonNak,
    dasha,
    tara,
    chandra,
    scores,
    timings,
    favourable,
    focus,
    sectors,
  };
}

function selectFocus(scores) {
  const ranked = Object.entries(scores)
    .filter(([name]) => name !== "overall")
    .sort((a, b) => b[1].value - a[1].value);
  return ranked[0][0];
}

function selectFavourableWindow(horas, caution, focus, scores) {
  const weightsByFocus = {
    study: { Mercury: 5, Jupiter: 4, Sun: 2, Moon: 2 },
    money: { Jupiter: 4, Mercury: 4, Saturn: 3, Venus: 2, Moon: 1 },
    health: { Sun: 4, Mars: 3, Moon: 2, Jupiter: 2 },
    communication: { Mercury: 5, Venus: 3, Moon: 3, Jupiter: 2 },
    overall: { Jupiter: 4, Mercury: 3, Moon: 2, Sun: 2 },
  };
  const weights = weightsByFocus[focus] || weightsByFocus.overall;
  const candidates = horas
    .filter((hora) => hora.period === "day")
    .filter((hora) => !overlaps(hora, caution))
    .map((hora) => ({
      ...hora,
      score: weights[hora.ruler] || 0,
    }))
    .sort((a, b) => b.score - a.score || a.start - b.start);

  const selected = candidates[0] || horas.find((hora) => hora.period === "day");
  return {
    ...selected,
    reason: `${selected.ruler} Hora selected for ${labelForSection(focus)} focus`,
  };
}

function labelForSection(name) {
  return {
    study: "Study & Career",
    money: "Money & Trading Discipline",
    health: "Health & Energy",
    communication: "Communication & People",
    overall: "Overall",
  }[name] || "Overall";
}

function tone(score) {
  if (score >= 3) return "Supportive";
  if (score <= -2) return "Caution";
  return "Balanced";
}

function sentenceFor(section, score, context) {
  const state = tone(score.value);
  if (section === "overall") {
    if (state === "Supportive") return "Supportive day for steady progress when decisions stay planned and simple.";
    if (state === "Caution") return "Reactive day; slow decisions, verify assumptions, and avoid forcing outcomes.";
    return "Balanced day; useful for routine progress if you keep structure and avoid rushing.";
  }
  if (section === "study") {
    if (state === "Supportive") return "Good for focused study, technical revision, and completing one difficult pending topic.";
    if (state === "Caution") return "Use shorter blocks, revise older material, and double-check calculations before moving ahead.";
    return "Suitable for normal study, notes, and backlog clearing with a written checklist.";
  }
  if (section === "money") {
    if (state === "Supportive") return "Discipline can stay strong if rules are written before action and setups are filtered carefully.";
    if (state === "Caution") return "High chance of impatience; avoid rushed money decisions and keep activity reduced.";
    return "Neutral discipline day; act only when the checklist is complete and the market context is clear.";
  }
  if (section === "health") {
    if (state === "Supportive") return "Energy is workable; use the stronger part of the day for demanding tasks and take regular breaks.";
    if (state === "Caution") return "Energy may fluctuate; protect sleep, hydration, meals, and screen breaks.";
    return "Moderate energy; steady routine and short movement breaks should keep focus stable.";
  }
  if (section === "communication") {
    if (state === "Supportive") return "Good for follow-ups, group coordination, and clear practical conversations.";
    if (state === "Caution") return "Tone can be misunderstood; keep replies short, factual, and delayed when emotions rise.";
    return "Normal interaction day; useful for practical follow-ups, but avoid overexplaining.";
  }
  return context;
}

function reasonsSuffix(score) {
  if (!score.reasons || !score.reasons.length) return "";
  return ` (${score.reasons.join(", ")})`;
}

function sectionSentence(section, score, evaluation) {
  return `${sentenceFor(section, score, evaluation)}${reasonsSuffix(score)}`;
}

function doToday(evaluation) {
  if (evaluation.scores.money.value <= -2) {
    return "Write rules before any money decision; finish one priority study task.";
  }
  if (evaluation.scores.study.value >= 3) {
    return "Use the best focus window for the hardest study or career task.";
  }
  return "Complete one important pending task and keep decisions inside normal rules.";
}

function avoidToday(evaluation) {
  if (evaluation.scores.money.value <= -2) {
    return "Impulsive decisions, revenge behaviour, and changing rules under pressure.";
  }
  if (evaluation.scores.communication.value <= -2) {
    return "Long emotional replies, assumptions about people, and unnecessary arguments.";
  }
  return "Overconfidence after early progress and switching plans without a clear reason.";
}

function sectorThemes(transit, dasha) {
  const evaluated = Object.fromEntries(
    Object.entries(SECTOR_THEME_DEFINITIONS).map(([name, factors]) => [
      name,
      scoreSectorTheme(factors, transit, dasha),
    ]),
  );

  const supportive = Object.entries(evaluated)
    .filter(([, item]) => item.supportReachable)
    .filter(([, item]) => item.score >= SECTOR_THEME_THRESHOLD && item.supporting >= 2)
    .map(([name]) => name);
  const caution = Object.entries(evaluated)
    .filter(([, item]) => item.cautionReachable)
    .filter(([, item]) => item.score <= -SECTOR_THEME_THRESHOLD && item.cautioning >= 2)
    .map(([name]) => name);

  if (!supportive.length && !caution.length) {
    return null;
  }
  return {
    supportive,
    caution,
    raw: Object.fromEntries(
      Object.entries(evaluated).map(([name, item]) => [name, item.score]),
    ),
    diagnostics: evaluated,
  };
}

function scoreSectorTheme(factors, transit, dasha) {
  let score = 0;
  let supporting = 0;
  let cautioning = 0;
  let theoreticalMin = 0;
  let theoreticalMax = 0;
  for (const factor of factors) {
    if (factor.score > 0) theoreticalMax += factor.score;
    if (factor.score < 0) theoreticalMin += factor.score;
    if (!sectorFactorApplies(factor, transit, dasha)) continue;
    score += factor.score;
    if (factor.score > 0) supporting += 1;
    if (factor.score < 0) cautioning += 1;
  }
  return {
    score,
    supporting,
    cautioning,
    theoreticalMin,
    theoreticalMax,
    supportReachable:
      theoreticalMax >= SECTOR_THEME_THRESHOLD &&
      factors.filter((factor) => factor.score > 0).length >= 2,
    cautionReachable:
      theoreticalMin <= -SECTOR_THEME_THRESHOLD &&
      factors.filter((factor) => factor.score < 0).length >= 2,
  };
}

function sectorFactorApplies(factor, transit, dasha) {
  if (factor.type === "dasha") {
    return dasha.mahadasha === factor.lord || dasha.antardasha?.lord === factor.lord;
  }
  if (factor.type === "house") {
    return factor.houses.includes(transit[factor.planet]?.[factor.relation]);
  }
  return false;
}

function displayDate(date) {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(Date.UTC(date.year, date.month - 1, date.day, 6)));
}

function buildDailyText(evaluation) {
  const lines = [
    `DAILY ASTROLOGY | ${displayDate(evaluation.date)}`,
    "",
    `Overall: ${sectionSentence("overall", evaluation.scores.overall, evaluation)}`,
    "",
    `Study & Career: ${sectionSentence("study", evaluation.scores.study, evaluation)}`,
    "",
    `Money & Trading Discipline: ${sectionSentence("money", evaluation.scores.money, evaluation)}`,
    "",
    `Health & Energy: ${sectionSentence("health", evaluation.scores.health, evaluation)}`,
    "",
    `Communication & People: ${sectionSentence("communication", evaluation.scores.communication, evaluation)}`,
    "",
    `Favourable Period: ${formatWindow(evaluation.favourable)}`,
    `Caution Period: ${formatWindow(evaluation.timings.rahuKalam)}`,
    "",
    `Do Today: ${doToday(evaluation)}`,
    `Avoid Today: ${avoidToday(evaluation)}`,
  ];

  if (evaluation.sectors) {
    lines.push("", "Sector Themes:");
    if (evaluation.sectors.supportive.length) {
      lines.push(`Supportive: ${evaluation.sectors.supportive.join(", ")}`);
    }
    if (evaluation.sectors.caution.length) {
      lines.push(`Caution: ${evaluation.sectors.caution.join(", ")}`);
    }
  }

  return lines.join("\n");
}

function buildDailyEmbed(evaluation) {
  const fields = [
    {
      name: "Overall",
      value: sectionSentence("overall", evaluation.scores.overall, evaluation),
    },
    {
      name: "Study & Career",
      value: sectionSentence("study", evaluation.scores.study, evaluation),
    },
    {
      name: "Money & Trading Discipline",
      value: sectionSentence("money", evaluation.scores.money, evaluation),
    },
    {
      name: "Health & Energy",
      value: sectionSentence("health", evaluation.scores.health, evaluation),
    },
    {
      name: "Communication & People",
      value: sectionSentence("communication", evaluation.scores.communication, evaluation),
    },
    {
      name: "Favourable Period",
      value: formatWindow(evaluation.favourable),
      inline: true,
    },
    {
      name: "Caution Period",
      value: formatWindow(evaluation.timings.rahuKalam),
      inline: true,
    },
    {
      name: "Do Today",
      value: doToday(evaluation),
    },
    {
      name: "Avoid Today",
      value: avoidToday(evaluation),
    },
  ];

  if (evaluation.sectors) {
    const sectorLines = [];
    if (evaluation.sectors.supportive.length) {
      sectorLines.push(`Supportive: ${evaluation.sectors.supportive.join(", ")}`);
    }
    if (evaluation.sectors.caution.length) {
      sectorLines.push(`Caution: ${evaluation.sectors.caution.join(", ")}`);
    }
    if (sectorLines.length) {
      fields.push({ name: "Sector Themes", value: sectorLines.join("\n") });
    }
  }

  return {
    title: `Shiva Daily Astrology - ${displayDate(evaluation.date)}`,
    color: 0x5865f2,
    fields,
    footer: {
      text: "Reflection only. Use your setup, stop-loss, and position-size rules.",
    },
  };
}

function buildDailyPayload(date) {
  const evaluation = evaluateDay(date);
  const content = buildDailyText(evaluation);
  return {
    payload: {
      username: "Shiva Daily Astrology",
      content: "",
      embeds: [buildDailyEmbed(evaluation)],
      allowed_mentions: { parse: [] },
    },
    text: content,
    diagnostics: diagnosticsFor(evaluation),
  };
}

function diagnosticsFor(evaluation) {
  return {
    date: evaluation.date,
    ayanamsha: "Lahiri",
    node: "Mean Node",
    natal: {
      ascendantSign: signName(NATAL.ascendant),
      moonSign: signName(NATAL.moon),
      moonNakshatra: nakshatraDetails(NATAL.moon),
    },
    transits: evaluation.transit,
    moonNakshatra: evaluation.moonNak,
    dasha: {
      mahadasha: evaluation.dasha.mahadasha,
      antardasha: evaluation.dasha.antardasha.lord,
      mahadashaStart: ymd(evaluation.dasha.mahadashaStart),
      mahadashaEnd: ymd(evaluation.dasha.mahadashaEnd),
      antardashaStart: ymd(evaluation.dasha.antardasha.start),
      antardashaEnd: ymd(evaluation.dasha.antardasha.end),
    },
    sunrise: formatHour(evaluation.timings.sun.sunrise),
    sunset: formatHour(evaluation.timings.sun.sunset),
    rahuKalam: formatWindow(evaluation.timings.rahuKalam),
    selectedHora: {
      ruler: evaluation.favourable.ruler,
      window: formatWindow(evaluation.favourable),
      reason: evaluation.favourable.reason,
    },
    chandraBala: evaluation.chandra,
    taraBala: evaluation.tara,
    scores: Object.fromEntries(
      Object.entries(evaluation.scores).map(([key, score]) => [key, score.value]),
    ),
    sectorThemes: evaluation.sectors?.raw || null,
  };
}

function ymd(date) {
  return date.toISOString().slice(0, 10);
}

function parseWeekStart() {
  const override = process.env.ASTROLOGY_WEEK_START?.trim();
  if (override) {
    return parseYmd(override, "ASTROLOGY_WEEK_START");
  }
  const base = parseForecastDate();
  const day = weekdayIndex(base);
  const daysUntilMonday = day === 0 ? 1 : 8 - day;
  return addDays(base, daysUntilMonday);
}

function weeklyRangeLabel(start) {
  const end = addDays(start, 6);
  const startLabel = new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "numeric",
    month: "short",
  }).format(new Date(Date.UTC(start.year, start.month - 1, start.day, 6)));
  const endLabel = new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(Date.UTC(end.year, end.month - 1, end.day, 6)));
  return `${startLabel}-${endLabel}`.toUpperCase();
}

function weekdayLabel(date) {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    day: "numeric",
  }).format(new Date(Date.UTC(date.year, date.month - 1, date.day, 6)));
}

function summarizeWeekly(evaluations, section) {
  const values = evaluations.map((item) => item.scores[section].value);
  const average = values.reduce((sum, value) => sum + value, 0) / values.length;
  const best = evaluations
    .map((item) => ({ label: weekdayLabel(item.date), score: item.scores[section].value }))
    .sort((a, b) => b.score - a.score)[0];
  const weak = evaluations
    .map((item) => ({ label: weekdayLabel(item.date), score: item.scores[section].value }))
    .sort((a, b) => a.score - b.score)[0];

  if (average >= 2) return `Supportive overall. Stronger around ${best.label}; use it for priority work.`;
  if (average <= -1) return `Caution overall. Be most careful around ${weak.label}; keep expectations simple.`;
  return `Mixed but workable. Stronger around ${best.label}, slower around ${weak.label}.`;
}

function buildWeeklyText(start, evaluations) {
  const totals = evaluations.map((item) => item.scores.overall.value);
  const stronger = evaluations
    .filter((item) => item.scores.overall.value >= 2)
    .map((item) => weekdayLabel(item.date));
  const caution = evaluations
    .filter((item) => item.scores.overall.value <= -2 || item.scores.money.value <= -2)
    .map((item) => weekdayLabel(item.date));
  const bestDay = evaluations
    .slice()
    .sort((a, b) => b.scores.overall.value - a.scores.overall.value)[0];
  const mainFocus =
    totals.reduce((sum, value) => sum + value, 0) >= 7
      ? "Use stronger days for difficult work; keep routines consistent on the rest."
      : "Keep the week practical: fewer decisions, cleaner routines, and written priorities.";
  const avoid =
    evaluations.some((item) => item.scores.money.value <= -2)
      ? "Avoid emotional money decisions and changing rules under pressure."
      : "Avoid overloading the schedule and reacting before checking facts.";

  const lines = [
    `NEXT WEEK ASTROLOGY | ${weeklyRangeLabel(start)}`,
    "",
    `Overall: ${summarizeWeekly(evaluations, "overall")}`,
    "",
    `Study & Career: ${summarizeWeekly(evaluations, "study")}`,
    "",
    `Money & Trading Discipline: ${summarizeWeekly(evaluations, "money")}`,
    "",
    `Health & Energy: ${summarizeWeekly(evaluations, "health")}`,
    "",
    `Communication & People: ${summarizeWeekly(evaluations, "communication")}`,
    "",
    `Stronger Days: ${stronger.length ? stronger.join(", ") : "None clearly stronger"}`,
    `Caution Days: ${caution.length ? caution.join(", ") : "None clearly caution"}`,
    `Best Period of Week: ${weekdayLabel(bestDay.date)} ${formatWindow(bestDay.favourable)}`,
    "",
    `Main Focus: ${mainFocus}`,
    `Avoid: ${avoid}`,
  ];

  const weeklySectors = mergeWeeklySectors(evaluations);
  if (weeklySectors) {
    lines.push("", "Sector Themes:");
    if (weeklySectors.supportive.length) {
      lines.push(`Supportive: ${weeklySectors.supportive.join(", ")}`);
    }
    if (weeklySectors.caution.length) {
      lines.push(`Caution: ${weeklySectors.caution.join(", ")}`);
    }
  }

  return lines.join("\n");
}

function buildWeeklyEmbed(start, evaluations) {
  const totals = evaluations.map((item) => item.scores.overall.value);
  const stronger = evaluations
    .filter((item) => item.scores.overall.value >= 2)
    .map((item) => weekdayLabel(item.date));
  const caution = evaluations
    .filter((item) => item.scores.overall.value <= -2 || item.scores.money.value <= -2)
    .map((item) => weekdayLabel(item.date));
  const bestDay = evaluations
    .slice()
    .sort((a, b) => b.scores.overall.value - a.scores.overall.value)[0];
  const mainFocus =
    totals.reduce((sum, value) => sum + value, 0) >= 7
      ? "Use stronger days for difficult work; keep routines consistent on the rest."
      : "Keep the week practical: fewer decisions, cleaner routines, and written priorities.";
  const avoid =
    evaluations.some((item) => item.scores.money.value <= -2)
      ? "Avoid emotional money decisions and changing rules under pressure."
      : "Avoid overloading the schedule and reacting before checking facts.";
  const fields = [
    {
      name: "Overall",
      value: summarizeWeekly(evaluations, "overall"),
    },
    {
      name: "Study & Career",
      value: summarizeWeekly(evaluations, "study"),
    },
    {
      name: "Money & Trading Discipline",
      value: summarizeWeekly(evaluations, "money"),
    },
    {
      name: "Health & Energy",
      value: summarizeWeekly(evaluations, "health"),
    },
    {
      name: "Communication & People",
      value: summarizeWeekly(evaluations, "communication"),
    },
    {
      name: "Stronger Days",
      value: stronger.length ? stronger.join(", ") : "None clearly stronger",
      inline: true,
    },
    {
      name: "Caution Days",
      value: caution.length ? caution.join(", ") : "None clearly caution",
      inline: true,
    },
    {
      name: "Best Period",
      value: `${weekdayLabel(bestDay.date)} ${formatWindow(bestDay.favourable)}`,
    },
    {
      name: "Main Focus",
      value: mainFocus,
    },
    {
      name: "Avoid",
      value: avoid,
    },
  ];

  const weeklySectors = mergeWeeklySectors(evaluations);
  if (weeklySectors) {
    const sectorLines = [];
    if (weeklySectors.supportive.length) {
      sectorLines.push(`Supportive: ${weeklySectors.supportive.join(", ")}`);
    }
    if (weeklySectors.caution.length) {
      sectorLines.push(`Caution: ${weeklySectors.caution.join(", ")}`);
    }
    if (sectorLines.length) {
      fields.push({ name: "Sector Themes", value: sectorLines.join("\n") });
    }
  }

  return {
    title: `Shiva Weekly Astrology - ${weeklyRangeLabel(start)}`,
    color: 0x5865f2,
    fields,
    footer: {
      text: "Reflection only. Use your setup, stop-loss, and position-size rules.",
    },
  };
}

function mergeWeeklySectors(evaluations) {
  const totals = {};
  for (const evaluation of evaluations) {
    if (!evaluation.sectors) continue;
    for (const [sector, value] of Object.entries(evaluation.sectors.raw)) {
      totals[sector] = (totals[sector] || 0) + value;
    }
  }
  const supportive = Object.entries(totals)
    .filter(([, value]) => value >= 9)
    .map(([sector]) => sector);
  const caution = Object.entries(totals)
    .filter(([, value]) => value <= -9)
    .map(([sector]) => sector);
  if (!supportive.length && !caution.length) return null;
  return { supportive, caution };
}

function buildWeeklyPayload(start) {
  const evaluations = Array.from({ length: 7 }, (_, index) => evaluateDay(addDays(start, index)));
  const content = buildWeeklyText(start, evaluations);
  return {
    payload: {
      username: "Shiva Weekly Astrology",
      content: "",
      embeds: [buildWeeklyEmbed(start, evaluations)],
      allowed_mentions: { parse: [] },
    },
    text: content,
    diagnostics: evaluations.map(diagnosticsFor),
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

module.exports = {
  NATAL,
  NATAL_DISPLAY_REFERENCE,
  SECTOR_THEME_DEFINITIONS,
  SECTOR_THEME_THRESHOLD,
  addDays,
  activeDasha,
  buildDailyPayload,
  buildWeeklyPayload,
  evaluateDay,
  getTransits,
  houseFromSign,
  nakshatraDetails,
  parseForecastDate,
  parseWeekStart,
  planetaryHoras,
  postJson,
  rahuKalam,
  scoreSectorTheme,
  signName,
  sunTimes,
  transitDiagnostics,
};
