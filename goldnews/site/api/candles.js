// Candle XAU/USD untuk chart website (Twelve Data, key di env Vercel).
// GET /api/candles?interval=15min|1h|4h&end=<epoch detik, opsional>
const ALLOWED = { "15min": 2000, "1h": 2500, "4h": 1500 };

export default async function handler(req, res) {
  const url = new URL(req.url, "http://x");
  const interval = ALLOWED[url.searchParams.get("interval")] ? url.searchParams.get("interval") : "15min";
  const end = Number(url.searchParams.get("end") || 0);
  const params = new URLSearchParams({
    symbol: "XAU/USD",
    interval,
    outputsize: String(ALLOWED[interval]),
    timezone: "UTC",
    apikey: process.env.TWELVEDATA_API_KEY || "",
  });
  if (end > 0) {
    params.set("end_date", new Date(end * 1000).toISOString().slice(0, 19).replace("T", " "));
  }
  try {
    const r = await fetch("https://api.twelvedata.com/time_series?" + params);
    const js = await r.json();
    if (js.status !== "ok") throw new Error(js.message || "twelvedata error");
    const bars = js.values
      .map((v) => [
        Math.floor(Date.parse(v.datetime.replace(" ", "T") + "Z") / 1000),
        +(+v.open).toFixed(2), +(+v.high).toFixed(2), +(+v.low).toFixed(2), +(+v.close).toFixed(2),
      ])
      .reverse();
    res.setHeader("Cache-Control", end > 0 ? "s-maxage=86400" : "s-maxage=300, stale-while-revalidate=600");
    res.status(200).json(bars);
  } catch (e) {
    res.status(502).json({ error: String(e.message || e) });
  }
}
