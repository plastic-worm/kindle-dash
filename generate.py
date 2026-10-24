"""Render the Kindle 3 dashboard (600x800, 8-bit greyscale PNG).

Data: Open-Meteo forecast + air quality (free, no key), US National Weather
Service alerts (free, no key). Pollen: not connected yet (placeholder).
Usage:  python generate.py            -> live data, writes dashboard.png
        python generate.py fixtures/  -> uses saved JSON files (for testing)
"""
import calendar, datetime as dt, json, math, os, sys, urllib.request
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont

# ---------------- settings ----------------
PLACE = "Potrero Hill"
LAT, LON = 37.7576, -122.3986
TZ = ZoneInfo("America/Los_Angeles")
OUT = "dashboard.png"
HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts") if os.path.isdir(os.path.join(HERE, "fonts")) else HERE

BLACK, DARK, MID, LIGHT, PALE, WHITE = 0, 70, 140, 200, 232, 255

_fc = {}
def F(size, bold=False):
    k = (size, bold)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(os.path.join(FONTS, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), size)
    return _fc[k]

# ---------------- data ----------------
FORECAST = ("https://api.open-meteo.com/v1/forecast"
            f"?latitude={LAT}&longitude={LON}&timezone=America%2FLos_Angeles&forecast_days=11"
            "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,is_day"
            "&hourly=temperature_2m,weather_code,precipitation_probability,precipitation,wind_speed_10m,is_day"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset")
AIR = ("https://air-quality-api.open-meteo.com/v1/air-quality"
       f"?latitude={LAT}&longitude={LON}&timezone=America%2FLos_Angeles&current=us_aqi")
ALERTS = f"https://api.weather.gov/alerts/active?point={LAT},{LON}"

def get(url, fixture_dir, name, headers=None):
    if fixture_dir:
        with open(os.path.join(fixture_dir, name)) as f:
            return json.load(f)
    req = urllib.request.Request(url, headers={"User-Agent": "kindle-dash (github.com/plastic-worm)", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def icon_for(code, is_day=1):
    if code in (0, 1): return "sun" if is_day else "moon"
    if code == 2: return "partly" if is_day else "cloud"
    if code in (3, 45, 48): return "cloud"
    return "rain"        # drizzle, rain, showers, snow, thunder

COND = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Fog",
        51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
        71: "Snow", 73: "Snow", 75: "Snow", 77: "Snow", 80: "Showers", 81: "Showers", 82: "Heavy showers",
        85: "Snow showers", 86: "Snow showers", 95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm"}

def aqi_cat(v):
    return ("Good" if v <= 50 else "Moderate" if v <= 100 else "Unhealthy*" if v <= 150
            else "Unhealthy" if v <= 200 else "Very unhealthy" if v <= 300 else "Hazardous")

def load(fixture_dir=None):
    now = dt.datetime.now(TZ)
    fc = get(FORECAST, fixture_dir, "forecast.json")
    try:
        aq = get(AIR, fixture_dir, "air.json")["current"]["us_aqi"]
    except Exception as e:
        print("air quality unavailable:", e); aq = None
    try:
        feats = get(ALERTS, fixture_dir, "alerts.json", {"Accept": "application/geo+json"})["features"]
        alerts = [f["properties"]["event"] for f in feats]
    except Exception as e:
        print("alerts unavailable:", e); alerts = None

    cur, hr, dy = fc["current"], fc["hourly"], fc["daily"]
    # hourly: start at the current hour, 25 points (now .. +24 h)
    key = now.strftime("%Y-%m-%dT%H:00")
    i0 = hr["time"].index(key) if key in hr["time"] else 0
    sl = slice(i0, i0 + 25)
    hours = [int(t[11:13]) for t in hr["time"][sl]]
    D = dict(
        now=now, place=PLACE,
        temp=round(cur["temperature_2m"]), feels=round(cur["apparent_temperature"]),
        wind=round(cur["wind_speed_10m"]), code=cur["weather_code"], is_day=cur["is_day"],
        cond=COND.get(cur["weather_code"], ""),
        hi=round(dy["temperature_2m_max"][0]), lo=round(dy["temperature_2m_min"][0]),
        hours=hours,
        htemp=[round(v) for v in hr["temperature_2m"][sl]],
        hcond=[icon_for(c, d) for c, d in zip(hr["weather_code"][sl], hr["is_day"][sl])],
        hprob=[v or 0 for v in hr["precipitation_probability"][sl]],
        hmm=[v or 0 for v in hr["precipitation"][sl]],
        hwind=[v or 0 for v in hr["wind_speed_10m"][sl]],
        days=[], aqi=aq, alerts=alerts,
        sunrise=dt.datetime.fromisoformat(dy["sunrise"][0]).replace(tzinfo=TZ),
        sunset=dt.datetime.fromisoformat(dy["sunset"][0]).replace(tzinfo=TZ),
    )
    for k in range(10):
        day = dt.date.fromisoformat(dy["time"][k])
        D["days"].append(("Today" if k == 0 else day.strftime("%a"), icon_for(dy["weather_code"][k]),
                          round(dy["temperature_2m_min"][k]), round(dy["temperature_2m_max"][k]),
                          dy["precipitation_probability_max"][k] or 0))
    return D

# ---------------- drawing ----------------
def hl(h):
    hh = h % 24
    return "12 am" if hh == 0 else "12 pm" if hh == 12 else f"{hh} am" if hh < 12 else f"{hh-12} pm"

def clock(t):
    return t.strftime("%I:%M %p").lstrip("0")

class Canvas:
    def __init__(self, D):
        self.D = D
        self.im = Image.new("L", (600, 800), WHITE)
        self.d = ImageDraw.Draw(self.im)

    def text(self, xy, s, font, fill=BLACK, anchor="la"):
        self.d.text(xy, s, font=font, fill=fill, anchor=anchor)

    def panel(self, x, y, w, h, title=None):
        self.d.rounded_rectangle([x, y, x+w, y+h], radius=10, outline=BLACK, width=2)
        if title:
            self.text((x+10, y+8), title.upper(), F(12, True), fill=MID)

    def cfill(self, l, r, y0, y1, frac, fill=DARK):
        if frac <= 0: return
        m = (y0+y1)/2; hh = max(1, (y1-y0-2)*frac/2)
        self.d.rectangle([l+1, m-hh, r-1, m+hh], fill=fill)

    def icon(self, kind, cx, cy, s):
        d = self.d
        if kind == "sun":
            r = s*0.22
            for i in range(8):
                a = i*math.pi/4
                d.line([cx+math.cos(a)*r*1.45, cy+math.sin(a)*r*1.45, cx+math.cos(a)*r*2.1, cy+math.sin(a)*r*2.1],
                       fill=BLACK, width=max(2, int(s/14)))
            d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=DARK, outline=BLACK, width=2)
        elif kind == "moon":
            r = s*0.3
            d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=DARK)
            d.ellipse([cx-r+r*0.6, cy-r-r*0.25, cx+r+r*0.6, cy+r-r*0.25], fill=WHITE)
        else:  # cloud, rain, partly
            if kind == "partly":
                self.icon("sun", cx+s*0.18, cy-s*0.16, s*0.75)
                cx, cy = cx-s*0.06, cy+s*0.1
            ccy = cy - (s*0.1 if kind == "rain" else 0)
            def blob(pad, fill):
                d.ellipse([cx-s*0.42-pad, ccy-s*0.05-pad, cx-s*0.02+pad, ccy+s*0.25+pad], fill=fill)
                d.ellipse([cx-s*0.22-pad, ccy-s*0.28-pad, cx+s*0.16+pad, ccy+s*0.12+pad], fill=fill)
                d.ellipse([cx+s*0.02-pad, ccy-s*0.12-pad, cx+s*0.42+pad, ccy+s*0.25+pad], fill=fill)
                d.rectangle([cx-s*0.24, ccy+s*0.05-pad, cx+s*0.24, ccy+s*0.25+pad], fill=fill)
            blob(2, BLACK); blob(0, PALE)
            if kind == "rain":
                for k in (-0.2, 0, 0.2):
                    x0 = cx + s*k
                    d.line([x0, ccy+s*0.33, x0-s*0.08, ccy+s*0.5], fill=BLACK, width=max(2, int(s/14)))

    # ---- panels ----
    def weather_today(self, x, y, w, h, big=62):
        D = self.D
        self.panel(x, y, w, h)
        b = y+30
        self.text((x+14, b), D["place"], F(18, True), anchor="ls")
        self.text((x+w-12, y+8), "Updated " + clock(D["now"]), F(12), fill=DARK, anchor="ra")
        b += 58
        num = str(D["temp"])
        self.text((x+10, b), num, F(big, True), anchor="ls")
        nx = x+10+F(big, True).getlength(num)+2
        self.text((nx, b-big*0.72), "°C", F(24, True), anchor="lt")
        self.icon(icon_for(D["code"], D["is_day"]), x+w-52, b-big*0.36, 72)
        b += 20
        self.text((x+16, b), f'{round(D["temp"]*9/5+32)}°F', F(17, True), fill=DARK, anchor="ls")
        b += 25
        hl_ = f'H:{D["hi"]}°  L:{D["lo"]}°'
        cond = D["cond"]
        while cond and F(18, True).getlength(cond + "   " + hl_) > w-24:
            cond = cond[:-1]
        self.text((x+14, b), (cond + "   " if cond else "") + hl_, F(18, True), anchor="ls")
        b += 22
        feels = f'Feels {D["feels"]}°'
        self.text((x+14, b), feels, F(15), fill=DARK, anchor="ls")
        self.text((x+14+F(15).getlength(feels)+18, b), f'Wind {D["wind"]} km/h', F(15), fill=DARK, anchor="ls")
        b += 23
        n = D["now"]
        self.text((x+14, b), f'{n.strftime("%A")}, {n.day} {n.strftime("%B %Y")}', F(15, True), anchor="ls")

    def small_sun(self, x, y, w, h):
        D = self.D
        self.panel(x, y, w, h, "Sunrise/Sunset")
        cx, cy, r = x+w/2+18, y+h-26, min(w*0.3, h*0.42)
        self.d.arc([cx-r, cy-r, cx+r, cy+r], 180, 360, fill=MID, width=2)
        self.d.line([cx-r-6, cy, cx+r+6, cy], fill=BLACK, width=1)
        sr, ss, n = D["sunrise"], D["sunset"], D["now"]
        if sr <= n <= ss:
            f = (n-sr)/(ss-sr)
            sx, sy = cx-r*math.cos(math.pi*f), cy-r*math.sin(math.pi*f)
            self.d.ellipse([sx-5, sy-5, sx+5, sy+5], fill=BLACK)
        else:  # night: hollow dot on the horizon
            sx = cx+r if n > ss else cx-r
            self.d.ellipse([sx-5, cy-5, sx+5, cy+5], fill=WHITE, outline=BLACK, width=2)
        self.text((x+10, y+h-10), "↑" + clock(sr).replace(" AM", ""), F(13, True), anchor="ls")
        self.text((x+w-10, y+h-10), "↓" + clock(ss).replace(" PM", ""), F(13, True), anchor="rs")

    def small_aqi(self, x, y, w, h):
        v = self.D["aqi"]
        self.panel(x, y, w, h, "Air quality")
        if v is None:
            self.text((x+10, y+50), "n/a", F(20, True), fill=MID, anchor="ls"); return
        v = round(v)
        self.text((x+10, y+50), str(v), F(28, True), anchor="ls")
        self.text((x+16+F(28, True).getlength(str(v)), y+50), aqi_cat(v), F(15), anchor="ls")
        bx0, bx1, by = x+10, x+w-10, y+h-14
        for i, (lo_, hi_) in enumerate([(0, 50), (50, 100), (100, 150), (150, 200), (200, 300)]):
            a = bx0+(bx1-bx0)*lo_/300; b = bx0+(bx1-bx0)*hi_/300
            self.d.rectangle([a, by-4, b-1, by+4], fill=[215, 165, 115, 60, 0][i], outline=DARK if i == 0 else None)
        mx = bx0+(bx1-bx0)*min(v, 300)/300
        self.d.polygon([(mx, by-6), (mx-5, by-12), (mx+5, by-12)], fill=BLACK)

    def small_pollen(self, x, y, w, h):
        self.panel(x, y, w, h, "Pollen")
        self.text((x+w/2, y+h/2+8), "not connected", F(13), fill=MID, anchor="mm")

    def small_alert(self, x, y, w, h):
        al = self.D["alerts"]
        self.panel(x, y, w, h, "Alerts")
        cx, cy = x+24, y+h/2+8
        active = bool(al)
        col = BLACK if active else MID
        self.d.polygon([(cx, cy-13), (cx-13, cy+10), (cx+13, cy+10)], outline=col, width=2)
        self.text((cx, cy+3), "!", F(13, True), fill=col, anchor="mm")
        msg = "unavailable" if al is None else (al[0] + (f" +{len(al)-1}" if len(al) > 1 else "")) if al else "No active alerts"
        fnt = F(14, True) if active else F(14)
        words, lines = msg.split(), [""]
        for wd in words:
            t = (lines[-1] + " " + wd).strip()
            if F(14, True).getlength(t) <= w-54: lines[-1] = t
            else: lines.append(wd)
        lines = lines[:2]
        for k, ln in enumerate(lines):
            self.text((x+44, cy + (k-(len(lines)-1)/2)*18), ln, fnt, anchor="lm")

    def next24(self, x, y, w, h, step=3):
        D = self.D
        self.panel(x, y, w, h, "Next 24 h")
        hrs, t, c = D["hours"], D["htemp"], D["hcond"]
        n = len(hrs)
        px0, px1 = x+46, x+w-22
        top, bot = y+64, y+h-24-59
        cbot = bot
        lo, hi = min(t)-1, max(t)+1
        X = lambda i: px0 + (px1-px0)*i/(n-1)
        Y = lambda v: cbot - (cbot-top)*(v-lo)/(hi-lo)
        pts = [(X(i), Y(v)) for i, v in enumerate(t)]
        self.d.polygon(pts + [(px1, cbot), (px0, cbot)], fill=PALE)
        self.d.line(pts, fill=BLACK, width=3)
        cwid = (px1-px0)/(n-1)
        wy0, wy1 = bot+4, bot+19
        py0, py1 = bot+22, bot+37
        iy0, iy1 = bot+40, bot+55
        lx = x+20
        wc = (wy0+wy1)/2; x0 = lx-9
        self.d.line([x0, wc-3, x0+11, wc-3], fill=DARK, width=2)
        self.d.arc([x0+8, wc-9, x0+14, wc-3], -90, 180, fill=DARK, width=2)
        self.d.line([x0-1, wc+3, x0+14, wc+3], fill=DARK, width=2)
        self.d.arc([x0+11, wc+3, x0+17, wc+9], 0, 270, fill=DARK, width=2)
        self.text((lx, (py0+py1)/2), "%", F(13, True), fill=DARK, anchor="mm")
        dy_ = (iy0+iy1)/2+1
        self.d.polygon([(lx, dy_-8), (lx-4, dy_), (lx+4, dy_)], fill=DARK)
        self.d.ellipse([lx-4.3, dy_-3, lx+4.3, dy_+5], fill=DARK)
        for i in range(n):
            l, r = X(i)-cwid/2+1, X(i)+cwid/2-1
            ws, pr, mm = D["hwind"][i], D["hprob"][i], D["hmm"][i]
            wl = 0 if ws < 5 else 1 if ws < 20 else 2 if ws < 39 else 3
            rl = 0 if mm == 0 else 1 if mm < 2.5 else 2 if mm <= 7.6 else 3
            for (a, b_), frac, fill in (((wy0, wy1), wl/3, DARK), ((py0, py1), pr/100, MID), ((iy0, iy1), rl/3, DARK)):
                self.d.rectangle([l, a, r, b_], outline=LIGHT)
                self.cfill(l, r, a, b_, frac, fill)
        lab_y = iy1
        idx = list(range(0, n, step)) + ([n-1] if (n-1) % step else [])
        for i in idx:
            px, py = pts[i]
            self.d.ellipse([px-4, py-4, px+4, py+4], fill=BLACK)
            self.text((px, py-8), f"{t[i]}°", F(14, True), anchor="mb")
            self.icon(c[i], px, y+36, 26)
            self.text((px, lab_y+5), "Now" if i == 0 else hl(hrs[i]), F(13, True) if i == 0 else F(13),
                      fill=BLACK if i == 0 else DARK, anchor="ma")

    def ten_day(self, x, y, w, h):
        D = self.D
        self.panel(x, y, w, h, "10-day forecast")
        days = D["days"]
        lo_all = min(d[2] for d in days); hi_all = max(d[3] for d in days)
        if hi_all == lo_all: hi_all += 1
        cw = (w-20)/len(days)
        rt, rb = y+88, y+h-12
        Yv = lambda v: rb-(rb-rt)*(v-lo_all)/(hi_all-lo_all)
        for i, (name, ic, lo, hi, pr) in enumerate(days):
            cx = x+10+cw*i+cw/2
            self.text((cx, y+24), name, F(14, True), anchor="ma")
            self.icon(ic, cx, y+52, 28)
            if pr >= 20: self.text((cx, y+71), f"{pr}%", F(11, True), anchor="ma")
            bx = cx-12
            self.d.rounded_rectangle([bx-3, rt, bx+3, rb], radius=3, fill=PALE)
            self.d.rounded_rectangle([bx-3, Yv(hi), bx+3, Yv(lo)], radius=3, fill=DARK)
            if i == 0:
                m = Yv(min(max(D["temp"], lo_all), hi_all))
                self.d.ellipse([bx-5, m-5, bx+5, m+5], fill=WHITE, outline=BLACK, width=2)
            self.text((bx+7, rt-1), f"{hi}°", F(14, True), anchor="lt")
            self.text((bx+7, rb+1), f"{lo}°", F(13), fill=DARK, anchor="lb")

    def minical(self, x, y, w, h, year, month, today=None):
        self.panel(x, y, w, h)
        self.text((x+12, y+8), f"{calendar.month_name[month]} {year}", F(16, True))
        cal = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
        gx0, gx1 = x+8, x+w-8
        cw = (gx1-gx0)/7
        hy = y+34
        twd = dt.date(year, month, today).weekday() if today else None
        for i, l in enumerate("MTWTFSS"):
            cx = gx0+cw*i+cw/2
            if i == twd:
                self.text((cx, hy), l, F(13, True), fill=BLACK, anchor="ma")
                self.d.line([cx-7, hy+16, cx+7, hy+16], fill=BLACK, width=2)
            else:
                self.text((cx, hy), l, F(12, True), fill=MID if i >= 5 else DARK, anchor="ma")
        rh = (y+h-8-(hy+18))/6
        for r, week in enumerate(cal):
            for c, dd in enumerate(week):
                if not dd: continue
                cx = gx0+cw*c+cw/2; cy = hy+18+rh*r+rh/2
                if dd == today:
                    s = min(cw, rh)*0.48
                    self.d.rounded_rectangle([cx-s, cy-s, cx+s, cy+s], radius=4, fill=BLACK)
                    self.text((cx, cy), str(dd), F(14, True), fill=WHITE, anchor="mm")
                else:
                    self.text((cx, cy), str(dd), F(14), fill=MID if c >= 5 else BLACK, anchor="mm")

def render(D, out=OUT):
    c = Canvas(D)
    H = 190; ys = [8, 206, 404, 602]
    sw, sh = 140, (H-8)//2
    c.weather_today(8, ys[0], 288, H)
    c.small_sun(304, ys[0], sw, sh);           c.small_aqi(304+sw+8, ys[0], sw, sh)
    c.small_pollen(304, ys[0]+sh+8, sw, sh);   c.small_alert(304+sw+8, ys[0]+sh+8, sw, sh)
    c.next24(8, ys[1], 584, H)
    c.ten_day(8, ys[2], 584, H)
    n = D["now"]
    nm = (n.year + n.month // 12, n.month % 12 + 1)
    c.minical(8, ys[3], 288, H, n.year, n.month, today=n.day)
    c.minical(304, ys[3], 288, H, nm[0], nm[1])
    c.im.save(out, optimize=True)
    print("wrote", out)

if __name__ == "__main__":
    render(load(sys.argv[1] if len(sys.argv) > 1 else None))
