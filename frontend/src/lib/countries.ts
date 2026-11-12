// Every country and territory with an ISO 3166-1 alpha-2 code, plus its international calling code.
// Names come from the browser's own Intl data (always correct for the visitor's engine); SadQah only adds
// search aliases such as "UK" or "Burma" so people can find a country however they spell it.

const RAW =
  "AF93 AX358 AL355 DZ213 AS1 AD376 AO244 AI1 AQ672 AG1 AR54 AM374 AW297 AU61 AT43 AZ994 BS1 BH973 BD880 BB1 BY375 BE32 BZ501 BJ229 BM1 BT975 BO591 BQ599 BA387 BW267 BV47 BR55 IO246 BN673 BG359 BF226 BI257 " +
  "CV238 KH855 CM237 CA1 KY1 CF236 TD235 CL56 CN86 CX61 CC61 CO57 KM269 CG242 CD243 CK682 CR506 CI225 HR385 CU53 CW599 CY357 CZ420 DK45 DJ253 DM1 DO1 EC593 EG20 SV503 GQ240 ER291 EE372 SZ268 ET251 " +
  "FK500 FO298 FJ679 FI358 FR33 GF594 PF689 TF262 GA241 GM220 GE995 DE49 GH233 GI350 GR30 GL299 GD1 GP590 GU1 GT502 GG44 GN224 GW245 GY592 HT509 HM672 VA379 HN504 HK852 HU36 IS354 IN91 ID62 IR98 IQ964 " +
  "IE353 IM44 IL972 IT39 JM1 JP81 JE44 JO962 KZ7 KE254 KI686 KP850 KR82 XK383 KW965 KG996 LA856 LV371 LB961 LS266 LR231 LY218 LI423 LT370 LU352 MO853 MG261 MW265 MY60 MV960 ML223 MT356 MH692 MQ596 MR222 " +
  "MU230 YT262 MX52 FM691 MD373 MC377 MN976 ME382 MS1 MA212 MZ258 MM95 NA264 NR674 NP977 NL31 NC687 NZ64 NI505 NE227 NG234 NU683 NF672 MK389 MP1 NO47 OM968 PK92 PW680 PS970 PA507 PG675 PY595 PE51 PH63 " +
  "PN64 PL48 PT351 PR1 QA974 RE262 RO40 RU7 RW250 BL590 SH290 KN1 LC1 MF590 PM508 VC1 WS685 SM378 ST239 SA966 SN221 RS381 SC248 SL232 SG65 SX1 SK421 SI386 SB677 SO252 ZA27 GS500 SS211 ES34 LK94 SD249 " +
  "SR597 SJ47 SE46 CH41 SY963 TW886 TJ992 TZ255 TH66 TL670 TG228 TK690 TO676 TT1 TN216 TR90 TM993 TC1 TV688 UG256 UA380 AE971 GB44 US1 UM1 UY598 UZ998 VU678 VE58 VN84 VG1 VI1 WF681 EH212 YE967 ZM260 ZW263";

const ALIASES: Record<string, string> = {
  GB: "UK Britain England Scotland Wales",
  US: "USA America",
  AE: "UAE Emirates Dubai Abu Dhabi",
  MM: "Burma",
  CZ: "Czech Republic",
  TR: "Turkey Turkiye",
  SZ: "Swaziland Eswatini",
  MK: "Macedonia",
  CD: "DRC Congo Kinshasa Democratic Republic",
  CG: "Congo Brazzaville",
  CI: "Ivory Coast",
  TL: "East Timor",
  KR: "South Korea",
  KP: "North Korea",
  PS: "Palestine Gaza West Bank",
  VA: "Vatican Holy See",
  CV: "Cape Verde",
  MO: "Macau",
  RU: "Russia",
  LA: "Laos",
  SY: "Syria",
  IR: "Iran",
  BO: "Bolivia",
  VE: "Venezuela",
  TZ: "Tanzania",
  VN: "Vietnam",
  MD: "Moldova",
  FM: "Micronesia",
  SH: "Saint Helena",
};

export type Country = {
  code: string;
  name: string;
  /** Calling code without the plus sign, e.g. "92". Several territories share "1". */
  dial: string;
  /** Lower-case text used for searching (name, code, aliases). */
  search: string;
};

const names =
  typeof Intl !== "undefined" && "DisplayNames" in Intl ? new Intl.DisplayNames(["en"], { type: "region" }) : null;

function nameOf(code: string): string {
  if (code === "XK") return "Kosovo";
  try {
    const n = names?.of(code);
    if (n && n !== code) return n;
  } catch {
    /* fall through */
  }
  return code;
}

const parsed: Country[] = RAW.split(/\s+/)
  .filter(Boolean)
  .map((tok) => {
    const code = tok.slice(0, 2);
    const dial = tok.slice(2);
    const name = nameOf(code);
    return { code, name, dial, search: `${name} ${code} ${ALIASES[code] ?? ""}`.toLowerCase() };
  })
  .sort((a, b) => a.name.localeCompare(b.name, "en"));

/** All countries, sorted A to Z by English name. */
export const COUNTRIES: readonly Country[] = parsed;

const byCode = new Map(parsed.map((c) => [c.code, c]));

export function findCountry(code: string | null | undefined): Country | undefined {
  return code ? byCode.get(code.toUpperCase()) : undefined;
}

/** "+92" for Pakistan, "" when no country is chosen. */
export function dialCode(code: string | null | undefined): string {
  const c = findCountry(code);
  return c ? `+${c.dial}` : "";
}

/** Countries SadQah recipients most often live in; shown first when nothing has been typed yet. */
export const FEATURED = ["PK", "BD", "IN", "LK", "NP", "AF", "KE", "NG", "GH", "UG", "TZ", "ET", "EG", "ID", "PH", "MM"] as const;
