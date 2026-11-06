// Country and time-zone choices. Names come from the browser in the user's language.

export const COUNTRIES = (
  "AE AF AL AM AO AR AT AU AZ BA BD BE BF BG BH BI BJ BN BO BR BW BY CA CD CF CG CH CI CL CM CN CO CR CU CY CZ " +
  "DE DJ DK DO DZ EC EE EG ER ES ET FI FR GA GB GE GH GM GN GQ GR GT GW HK HN HR HU ID IE IL IN IQ IR IS IT JM JO " +
  "JP KE KG KH KM KR KW KZ LA LB LK LR LS LT LU LV LY MA MD ME MG MK ML MM MN MR MT MU MW MX MY MZ NA NE NG NI NL " +
  "NO NP NZ OM PA PE PH PK PL PS PT PY QA RO RS RU RW SA SC SD SE SG SI SK SL SN SO SS SV SY SZ TD TG TH TJ TM TN " +
  "TR TW TZ UA UG US UY UZ VE VN YE ZA ZM ZW"
).split(" ");

const FALLBACK_ZONES = [
  "Africa/Cairo", "Africa/Algiers", "Africa/Casablanca", "Africa/Johannesburg", "Africa/Khartoum", "Africa/Lagos",
  "Africa/Nairobi", "Africa/Tripoli", "Africa/Tunis", "America/New_York", "America/Chicago", "America/Los_Angeles",
  "America/Sao_Paulo", "Asia/Amman", "Asia/Baghdad", "Asia/Bahrain", "Asia/Beirut", "Asia/Damascus", "Asia/Dhaka",
  "Asia/Dubai", "Asia/Jerusalem", "Asia/Karachi", "Asia/Kolkata", "Asia/Kuwait", "Asia/Muscat", "Asia/Qatar",
  "Asia/Riyadh", "Asia/Shanghai", "Asia/Singapore", "Asia/Tokyo", "Europe/Berlin", "Europe/Istanbul",
  "Europe/London", "Europe/Madrid", "Europe/Moscow", "Europe/Paris", "UTC",
];

export function timeZones(): string[] {
  try {
    const list = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone");
    if (list && list.length) return list.includes("UTC") ? list : [...list, "UTC"];
  } catch { /* older browser */ }
  return FALLBACK_ZONES;
}
