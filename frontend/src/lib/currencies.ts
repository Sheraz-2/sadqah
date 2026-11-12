/** Local currency (ISO 4217) by country (ISO 3166-1 alpha-2): a starting point the person can overwrite. */
const BY_COUNTRY: Record<string, string> = {
  AF: "AFN", AL: "ALL", DZ: "DZD", AO: "AOA", AR: "ARS", AM: "AMD", AU: "AUD", AZ: "AZN", BH: "BHD", BD: "BDT", BY: "BYN", BZ: "BZD",
  BJ: "XOF", BT: "BTN", BO: "BOB", BA: "BAM", BW: "BWP", BR: "BRL", BF: "XOF", BI: "BIF", KH: "KHR", CM: "XAF", CA: "CAD", CF: "XAF",
  TD: "XAF", CL: "CLP", CN: "CNY", CO: "COP", KM: "KMF", CD: "CDF", CG: "XAF", CR: "CRC", CI: "XOF", CU: "CUP", DJ: "DJF", DO: "DOP",
  EC: "USD", EG: "EGP", SV: "USD", ER: "ERN", ET: "ETB", FJ: "FJD", GA: "XAF", GM: "GMD", GE: "GEL", GH: "GHS", GT: "GTQ", GN: "GNF",
  GW: "XOF", GY: "GYD", HT: "HTG", HN: "HNL", IN: "INR", ID: "IDR", IR: "IRR", IQ: "IQD", IL: "ILS", JM: "JMD", JP: "JPY", JO: "JOD",
  KZ: "KZT", KE: "KES", KW: "KWD", KG: "KGS", LA: "LAK", LB: "LBP", LS: "LSL", LR: "LRD", LY: "LYD", MG: "MGA", MW: "MWK", MY: "MYR",
  MV: "MVR", ML: "XOF", MR: "MRU", MU: "MUR", MX: "MXN", MD: "MDL", MN: "MNT", MA: "MAD", MZ: "MZN", MM: "MMK", NA: "NAD", NP: "NPR",
  NI: "NIO", NE: "XOF", NG: "NGN", PK: "PKR", PS: "ILS", PA: "PAB", PG: "PGK", PY: "PYG", PE: "PEN", PH: "PHP", QA: "QAR", RW: "RWF",
  SA: "SAR", SN: "XOF", RS: "RSD", SL: "SLE", SO: "SOS", ZA: "ZAR", SS: "SSP", LK: "LKR", SD: "SDG", SR: "SRD", SZ: "SZL", SY: "SYP",
  TJ: "TJS", TZ: "TZS", TH: "THB", TL: "USD", TG: "XOF", TN: "TND", TR: "TRY", TM: "TMT", UG: "UGX", UA: "UAH", AE: "AED", GB: "GBP",
  US: "USD", UY: "UYU", UZ: "UZS", VE: "VES", VN: "VND", YE: "YER", ZM: "ZMW", ZW: "USD",
};

const EUROZONE = ["AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PT", "SI", "SK"];

export function currencyFor(country: string | null | undefined): string {
  const c = (country ?? "").toUpperCase();
  if (EUROZONE.includes(c)) return "EUR";
  return BY_COUNTRY[c] ?? "USD";
}
