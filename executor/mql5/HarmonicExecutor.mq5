//+------------------------------------------------------------------+
//| HarmonicExecutor.mq5                                              |
//| Eksekutor sinyal harmonic-signals untuk MetaTrader 5 (Windows/Mac)|
//|                                                                   |
//| Membaca antrean order dari Upstash Redis (REST) yang ditulis      |
//| scanner di GitHub Actions, lalu memasang pending limit / market   |
//| dengan lot = risiko % ekuitas, 50/50 TP1/TP2, SL ke breakeven     |
//| setelah TP1, cancel saat "jangan kejar" / kedaluwarsa, batas      |
//| setup aktif & rugi harian. Logika = executor/ (Python).           |
//|                                                                   |
//| WAJIB: Tools > Options > Expert Advisors > Allow WebRequest untuk |
//|   https://<akun>.upstash.io  dan  https://api.telegram.org        |
//+------------------------------------------------------------------+
#property copyright "harmonic-signals"
#property version   "1.00"
#property strict
#include <Trade\Trade.mqh>

input string InpUpstashUrl    = "";        // Upstash REST URL (https://xxx.upstash.io)
input string InpUpstashToken  = "";        // Upstash REST token
input string InpTelegramToken = "";        // Telegram bot token (kosong = tanpa notifikasi)
input string InpTelegramChat  = "";        // Telegram chat id
input double InpRiskPct       = 1.0;       // Risiko % ekuitas per trade (Grade A)
input double InpRiskBFactor   = 0.5;       // Grade B = risiko x faktor
input int    InpMaxOpen       = 3;         // Maks setup aktif (pending + posisi)
input double InpDailyLossPct  = 3.0;       // Rugi harian % saldo -> stop sampai besok
input bool   InpSplitTP       = true;      // 50% lot TP1 + 50% lot TP2
input int    InpPollSec       = 20;        // Interval cek antrean (detik)
input int    InpMagic         = 260917;    // Magic number
input int    InpDeviation     = 20;        // Slippage market order (point)
input string InpSymbolSuffix  = "";        // Suffix simbol broker (mis. .z)
input string InpQueueKey      = "mt5:queue";
input string InpHaltKey       = "mt5:halt";

CTrade   trade;
long     g_haltDay = 0;          // yyyymmdd saat batas rugi harian kena
datetime g_lastPoll = 0;

//+------------------------------------------------------------------+
//| Util: log + Telegram                                              |
//+------------------------------------------------------------------+
void Log(const string msg) { Print("[HS] ", msg); }

string JsonEscape(string s)
  {
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   StringReplace(s, "\n", "\\n");
   return s;
  }

bool HttpPost(const string url, const string headers, const string body, string &out, int timeout = 8000)
  {
   char data[]; char result[]; string rh;
   int n = StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(n > 0) ArrayResize(data, n - 1);          // buang terminator 0
   ResetLastError();
   int code = WebRequest("POST", url, headers, timeout, data, result, rh);
   out = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   if(code == -1)
     {
      Log("WebRequest gagal (" + IntegerToString(GetLastError()) + ") — URL sudah diizinkan di Options > Expert Advisors? " + url);
      return false;
     }
   if(code < 200 || code >= 300) { Log("HTTP " + IntegerToString(code) + ": " + StringSubstr(out, 0, 200)); return false; }
   return true;
  }

void Notify(const string text)
  {
   Log(text);
   if(InpTelegramToken == "" || InpTelegramChat == "") return;
   string body = "{\"chat_id\":\"" + InpTelegramChat + "\",\"text\":\"" + JsonEscape("🤖 MT5 EA · " + text) + "\",\"parse_mode\":\"HTML\"}";
   string out;
   HttpPost("https://api.telegram.org/bot" + InpTelegramToken + "/sendMessage", "Content-Type: application/json\r\n", body, out);
  }

//+------------------------------------------------------------------+
//| Upstash REST: kirim perintah, kembalikan isi "result" (unescaped) |
//+------------------------------------------------------------------+
bool Upstash(const string cmdJson, string &result, bool &isNull)
  {
   string out;
   isNull = false;
   if(InpUpstashUrl == "" || InpUpstashToken == "") { Log("Upstash URL/token kosong"); return false; }
   if(!HttpPost(InpUpstashUrl, "Authorization: Bearer " + InpUpstashToken + "\r\nContent-Type: application/json\r\n", cmdJson, out))
      return false;
   int p = StringFind(out, "\"result\":");
   if(p < 0) { Log("respons Upstash aneh: " + StringSubstr(out, 0, 200)); return false; }
   p += 9;
   while(p < StringLen(out) && StringGetCharacter(out, p) == ' ') p++;
   ushort c = StringGetCharacter(out, p);
   if(c == 'n') { isNull = true; result = ""; return true; }
   if(c != '"')                                   // angka (LLEN dsb.)
     {
      int e = p;
      while(e < StringLen(out) && StringGetCharacter(out, e) != ',' && StringGetCharacter(out, e) != '}') e++;
      result = StringSubstr(out, p, e - p);
      return true;
     }
   p++;
   string s = "";
   while(p < StringLen(out))
     {
      ushort ch = StringGetCharacter(out, p);
      if(ch == '\\')
        {
         ushort nx = StringGetCharacter(out, p + 1);
         if(nx == 'n') s += "\n"; else if(nx == 't') s += "\t"; else s += ShortToString(nx);
         p += 2; continue;
        }
      if(ch == '"') break;
      s += ShortToString(ch); p++;
     }
   result = s;
   return true;
  }

//+------------------------------------------------------------------+
//| JSON flat: ambil nilai key (string / angka / array mentah)        |
//+------------------------------------------------------------------+
string JGet(const string json, const string key)
  {
   string k = "\"" + key + "\":";
   int p = StringFind(json, k);
   if(p < 0) return "";
   p += StringLen(k);
   while(p < StringLen(json) && StringGetCharacter(json, p) == ' ') p++;
   ushort c = StringGetCharacter(json, p);
   if(c == '"')
     {
      string s = ""; p++;
      while(p < StringLen(json))
        {
         ushort ch = StringGetCharacter(json, p);
         if(ch == '\\') { s += ShortToString(StringGetCharacter(json, p + 1)); p += 2; continue; }
         if(ch == '"') break;
         s += ShortToString(ch); p++;
        }
      return s;
     }
   if(c == '[') { int e = StringFind(json, "]", p); return StringSubstr(json, p, e - p + 1); }
   int e = p;
   while(e < StringLen(json) && StringGetCharacter(json, e) != ',' && StringGetCharacter(json, e) != '}') e++;
   return StringSubstr(json, p, e - p);
  }

double JNum(const string json, const string key) { return StringToDouble(JGet(json, key)); }

//+------------------------------------------------------------------+
//| Tag setup: "HS" + 8 hex pertama sha1(id) (sama dengan Python)     |
//+------------------------------------------------------------------+
string TagOf(const string id)
  {
   uchar src[], key[], hash[];
   int n = StringToCharArray(id, src, 0, WHOLE_ARRAY, CP_UTF8);
   if(n > 0) ArrayResize(src, n - 1);
   if(CryptEncode(CRYPT_HASH_SHA1, src, key, hash) <= 0) return "HS" + StringSubstr(id, 0, 8);
   string hex = "";
   for(int i = 0; i < 4; i++) hex += StringFormat("%02x", hash[i]);
   return "HS" + hex;
  }

string CommentTag(const string comment) { int p = StringFind(comment, "|"); return p < 0 ? comment : StringSubstr(comment, 0, p); }

//+------------------------------------------------------------------+
//| ISO "2026-09-23T06:31:00+00:00" -> datetime (UTC)                 |
//+------------------------------------------------------------------+
datetime ParseIso(string iso)
  {
   if(StringLen(iso) < 19) return 0;
   string s = StringSubstr(iso, 0, 19);
   StringReplace(s, "-", ".");
   StringReplace(s, "T", " ");
   return StringToTime(s);
  }

//+------------------------------------------------------------------+
//| Simbol broker: EUR/USD -> EURUSD | #EURUSD | EURUSD<suffix>       |
//+------------------------------------------------------------------+
string ResolveSymbol(const string pair)
  {
   string base = pair;
   StringReplace(base, "/", "");
   string cands[3];
   cands[0] = base + InpSymbolSuffix; cands[1] = base; cands[2] = "#" + base;
   for(int i = 0; i < 3; i++)
      if(SymbolSelect(cands[i], true)) return cands[i];
   return "";
  }

//+------------------------------------------------------------------+
//| Lot dari risiko % ekuitas                                          |
//+------------------------------------------------------------------+
double NormalizeLot(const string sym, double lot)
  {
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   if(step > 0) lot = MathFloor(lot / step + 1e-9) * step;
   if(lot < vmin) return 0.0;
   return MathMin(lot, vmax);
  }

double LotForRisk(const string sym, double riskPct, double entry, double sl)
  {
   double dist = MathAbs(entry - sl);
   double tsize = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double tval  = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   if(dist <= 0 || tsize <= 0 || tval <= 0) return 0.0;
   double lossPerLot = dist / tsize * tval;
   return NormalizeLot(sym, AccountInfoDouble(ACCOUNT_EQUITY) * riskPct / 100.0 / lossPerLot);
  }

//+------------------------------------------------------------------+
//| Apakah tag sudah ada (order / posisi / history 7 hari)            |
//+------------------------------------------------------------------+
bool TagExists(const string tag)
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t > 0 && OrderGetInteger(ORDER_MAGIC) == InpMagic && CommentTag(OrderGetString(ORDER_COMMENT)) == tag) return true;
     }
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic && CommentTag(PositionGetString(POSITION_COMMENT)) == tag) return true;
     }
   if(HistorySelect(TimeCurrent() - 7 * 86400, TimeCurrent() + 86400))
      for(int i = HistoryOrdersTotal() - 1; i >= 0; i--)
        {
         ulong t = HistoryOrderGetTicket(i);
         if(t > 0 && HistoryOrderGetInteger(t, ORDER_MAGIC) == InpMagic && CommentTag(HistoryOrderGetString(t, ORDER_COMMENT)) == tag) return true;
        }
   return false;
  }

int ActiveSetups()
  {
   string tags[]; int n = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0 || OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;
      string tg = CommentTag(OrderGetString(ORDER_COMMENT)); bool seen = false;
      for(int j = 0; j < n; j++) if(tags[j] == tg) seen = true;
      if(!seen) { ArrayResize(tags, n + 1); tags[n++] = tg; }
     }
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      string tg = CommentTag(PositionGetString(POSITION_COMMENT)); bool seen = false;
      for(int j = 0; j < n; j++) if(tags[j] == tg) seen = true;
      if(!seen) { ArrayResize(tags, n + 1); tags[n++] = tg; }
     }
   return n;
  }

//+------------------------------------------------------------------+
//| Pasang order sesuai event                                          |
//+------------------------------------------------------------------+
bool SendLeg(const string sym, bool isBuy, bool market, double vol, double price, double sl, double tp, const string comment)
  {
   trade.SetTypeFillingBySymbol(sym);
   bool ok;
   if(market) ok = isBuy ? trade.Buy(vol, sym, 0.0, sl, tp, comment) : trade.Sell(vol, sym, 0.0, sl, tp, comment);
   else       ok = isBuy ? trade.BuyLimit(vol, price, sym, sl, tp, ORDER_TIME_GTC, 0, comment)
                         : trade.SellLimit(vol, price, sym, sl, tp, ORDER_TIME_GTC, 0, comment);
   uint rc = trade.ResultRetcode();
   if(!ok || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_PLACED))
     {
      Log("order gagal " + comment + ": " + IntegerToString(rc) + " " + trade.ResultRetcodeDescription());
      return false;
     }
   return true;
  }

void Place(const string ev)
  {
   string id = JGet(ev, "id"), label = JGet(ev, "label"), side = JGet(ev, "side"), grade = JGet(ev, "grade");
   string tag = TagOf(id);
   double entry = JNum(ev, "entry"), sl = JNum(ev, "sl"), tp1 = JNum(ev, "tp1"), tp2 = JNum(ev, "tp2");
   int    expH  = (int)JNum(ev, "expires_hours"); if(expH <= 0) expH = 24;

   datetime created = ParseIso(JGet(ev, "created_at"));
   if(created > 0 && TimeGMT() - created > expH * 3600) { Log("skip " + label + ": event kedaluwarsa"); return; }
   if(TagExists(tag)) { Log("skip " + label + ": sudah pernah dipasang (" + tag + ")"); return; }
   string halt = HaltReason();
   if(halt != "") { Log("skip " + label + ": halt (" + halt + ")"); return; }
   if(ActiveSetups() >= InpMaxOpen) { Log("skip " + label + ": setup aktif >= " + IntegerToString(InpMaxOpen)); return; }

   string sym = ResolveSymbol(JGet(ev, "symbol"));
   if(sym == "") { Notify("⚠️ " + label + ": simbol tidak ada di broker"); return; }
   bool isBuy = (side == "buy");
   double risk = (grade == "A") ? InpRiskPct : InpRiskPct * InpRiskBFactor;
   double lot = LotForRisk(sym, risk, entry, sl);
   if(lot <= 0) { Notify("⚠️ " + label + " tidak dipasang: SL terlalu jauh untuk lot minimal"); return; }

   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double minDist = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL) * SymbolInfoDouble(sym, SYMBOL_POINT);
   if(MathAbs(entry - sl) < minDist || MathAbs(entry - tp1) < minDist) { Notify("⚠️ " + label + ": SL/TP lebih dekat dari stop level broker"); return; }

   double ask = SymbolInfoDouble(sym, SYMBOL_ASK), bid = SymbolInfoDouble(sym, SYMBOL_BID);
   bool market = isBuy ? (ask <= entry) : (bid >= entry);
   double half = NormalizeLot(sym, lot / 2.0);
   string hs = "|" + IntegerToString(expH);
   entry = NormalizeDouble(entry, digits); sl = NormalizeDouble(sl, digits);
   tp1 = NormalizeDouble(tp1, digits); tp2 = NormalizeDouble(tp2, digits);

   bool ok;
   if(InpSplitTP && half > 0)
     {
      ok = SendLeg(sym, isBuy, market, half, entry, sl, tp1, tag + "|TP1" + hs);
      if(ok) ok = SendLeg(sym, isBuy, market, half, entry, sl, tp2, tag + "|TP2" + hs);
     }
   else ok = SendLeg(sym, isBuy, market, lot, entry, sl, tp1, tag + "|TP1" + hs);

   if(ok) Notify("✅ " + label + " · " + (market ? "market" : "limit") + " " + (isBuy ? "BUY" : "SELL") + " " + DoubleToString(lot, 2) +
                 " lot @ " + DoubleToString(entry, digits) + " · SL " + DoubleToString(sl, digits) + " · TP1 " + DoubleToString(tp1, digits) +
                 " · TP2 " + DoubleToString(tp2, digits) + " · Grade " + grade);
   else   Notify("⚠️ " + label + ": order ditolak broker, lihat log Experts");
  }

int Cancel(const string tag)
  {
   int n = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t > 0 && OrderGetInteger(ORDER_MAGIC) == InpMagic && CommentTag(OrderGetString(ORDER_COMMENT)) == tag)
         if(trade.OrderDelete(t)) n++;
     }
   return n;
  }

//+------------------------------------------------------------------+
//| Manajemen: breakeven, kedaluwarsa, rugi harian, halt              |
//+------------------------------------------------------------------+
void ManageBreakeven()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      string c = PositionGetString(POSITION_COMMENT);
      if(StringFind(c, "|TP2") < 0) continue;
      string tag = CommentTag(c);
      // leg TP1 masih terbuka?
      bool tp1Open = false;
      for(int j = PositionsTotal() - 1; j >= 0; j--)
        {
         ulong t2 = PositionGetTicket(j);
         if(t2 > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic && StringFind(PositionGetString(POSITION_COMMENT), tag + "|TP1") == 0) tp1Open = true;
        }
      PositionSelectByTicket(t);
      if(tp1Open) continue;
      double be = PositionGetDouble(POSITION_PRICE_OPEN), sl = PositionGetDouble(POSITION_SL), tp = PositionGetDouble(POSITION_TP);
      long type = PositionGetInteger(POSITION_TYPE);
      bool already = (type == POSITION_TYPE_BUY && sl >= be) || (type == POSITION_TYPE_SELL && sl > 0 && sl <= be);
      if(already) continue;
      // TP1 tertutup untung? cari deal masuk berkomentar tag|TP1, lalu deal keluarnya lewat position id
      if(!HistorySelect(TimeCurrent() - 7 * 86400, TimeCurrent() + 86400)) continue;
      bool profit = false;
      for(int d = HistoryDealsTotal() - 1; d >= 0 && !profit; d--)
        {
         ulong dt = HistoryDealGetTicket(d);
         if(dt == 0 || HistoryDealGetInteger(dt, DEAL_MAGIC) != InpMagic) continue;
         if(HistoryDealGetInteger(dt, DEAL_ENTRY) != DEAL_ENTRY_IN || StringFind(HistoryDealGetString(dt, DEAL_COMMENT), tag + "|TP1") != 0) continue;
         long pid = HistoryDealGetInteger(dt, DEAL_POSITION_ID);
         for(int e = HistoryDealsTotal() - 1; e >= 0; e--)
           {
            ulong et = HistoryDealGetTicket(e);
            if(et > 0 && HistoryDealGetInteger(et, DEAL_POSITION_ID) == pid && HistoryDealGetInteger(et, DEAL_ENTRY) == DEAL_ENTRY_OUT
               && HistoryDealGetDouble(et, DEAL_PROFIT) > 0) profit = true;
           }
        }
      if(!profit) continue;
      if(trade.PositionModify(t, be, tp)) Notify("🔒 " + PositionGetString(POSITION_SYMBOL) + " " + tag + " SL→BE " + DoubleToString(be, (int)SymbolInfoInteger(PositionGetString(POSITION_SYMBOL), SYMBOL_DIGITS)));
     }
  }

void ExpirePendings()
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0 || OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;
      string c = OrderGetString(ORDER_COMMENT);
      int p = StringFind(c, "|", StringFind(c, "|") + 1);
      int hours = (p < 0) ? 24 : (int)StringToInteger(StringSubstr(c, p + 1));
      if(hours <= 0) hours = 24;
      if(TimeCurrent() - (datetime)OrderGetInteger(ORDER_TIME_SETUP) > hours * 3600)
         if(trade.OrderDelete(t)) Notify("⌛ " + OrderGetString(ORDER_SYMBOL) + " " + CommentTag(c) + ": pending kedaluwarsa dibatalkan");
     }
  }

double DailyPnl()
  {
   datetime day = TimeCurrent() - (TimeCurrent() % 86400);
   if(!HistorySelect(day, TimeCurrent() + 86400)) return 0.0;
   double total = 0.0;
   for(int d = HistoryDealsTotal() - 1; d >= 0; d--)
     {
      ulong dt = HistoryDealGetTicket(d);
      if(dt == 0 || HistoryDealGetInteger(dt, DEAL_MAGIC) != InpMagic || HistoryDealGetInteger(dt, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      total += HistoryDealGetDouble(dt, DEAL_PROFIT) + HistoryDealGetDouble(dt, DEAL_COMMISSION) + HistoryDealGetDouble(dt, DEAL_SWAP);
     }
   return total;
  }

long TodayNum() { MqlDateTime m; TimeToStruct(TimeCurrent(), m); return (long)m.year * 10000 + m.mon * 100 + m.day; }

void CheckDailyLoss()
  {
   double pnl = DailyPnl(), bal = AccountInfoDouble(ACCOUNT_BALANCE);
   if(pnl <= -bal * InpDailyLossPct / 100.0 && g_haltDay != TodayNum())
     {
      g_haltDay = TodayNum();
      GlobalVariableSet("HS_HALT_DAY", (double)g_haltDay);
      Notify("⛔ Rugi hari ini " + DoubleToString(pnl, 2) + " ≥ " + DoubleToString(InpDailyLossPct, 1) + "% saldo → tidak pasang order baru sampai besok");
     }
  }

string HaltReason()
  {
   if(GlobalVariableCheck("HS_HALT") && GlobalVariableGet("HS_HALT") > 0) return "global variable HS_HALT";
   if(g_haltDay == TodayNum()) return "batas rugi harian";
   string r; bool isNull;
   if(Upstash("[\"GET\",\"" + InpHaltKey + "\"]", r, isNull) && !isNull && (r == "1" || r == "true")) return "key Upstash " + InpHaltKey;
   return "";
  }

//+------------------------------------------------------------------+
//| Loop                                                               |
//+------------------------------------------------------------------+
void Tick()
  {
   for(int k = 0; k < 50; k++)
     {
      string ev; bool isNull;
      if(!Upstash("[\"LPOP\",\"" + InpQueueKey + "\"]", ev, isNull) || isNull) break;
      string action = JGet(ev, "action"), id = JGet(ev, "id"), label = JGet(ev, "label");
      if(action == "cancel")
        {
         int n = Cancel(TagOf(id));
         if(n > 0) Notify("❌ " + label + ": " + IntegerToString(n) + " pending dibatalkan (" + JGet(ev, "stage") + ")");
        }
      else if(action == "place") Place(ev);
     }
   ManageBreakeven();
   ExpirePendings();
   CheckDailyLoss();
  }

int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpDeviation);
   trade.SetAsyncMode(false);
   if(GlobalVariableCheck("HS_HALT_DAY")) g_haltDay = (long)GlobalVariableGet("HS_HALT_DAY");
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) Log("Tombol Algo Trading OFF — order tidak akan masuk sampai dinyalakan");
   EventSetTimer(MathMax(5, InpPollSec));
   Notify("EA jalan · akun " + IntegerToString((int)AccountInfoInteger(ACCOUNT_LOGIN)) + " · ekuitas " +
          DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + " " + AccountInfoString(ACCOUNT_CURRENCY) +
          " · risiko " + DoubleToString(InpRiskPct, 1) + "% · antrean " + InpQueueKey);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) { EventKillTimer(); }
void OnTimer() { Tick(); }
void OnTick() {}
//+------------------------------------------------------------------+
