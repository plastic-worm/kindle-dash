"""Render the Kindle 3 dashboard (600x800, 8-bit greyscale PNG).

Data: Open-Meteo forecast + air quality (free, no key), US National Weather
Service alerts (free, no key). Pollen: not connected yet (placeholder).
Usage:  python generate.py            -> live data, writes dashboard.png
        python generate.py fixtures/  -> uses saved JSON files (for testing)
"""
import calendar, datetime as dt, json, math, os, sys, time, urllib.request
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
    # enlarge small text for e-ink legibility (+3 px up to 15 px, +2 px for 16-18 px)
    size = size + 3 if size <= 15 else size + 2 if size <= 18 else size
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
    for attempt in range(1, 5):               # 4 tries; servers sometimes time out
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as e:
            print(f"{name}: try {attempt} failed: {e}")
            if attempt == 4: raise
            time.sleep(15)

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
        htemp=[round(cur["temperature_2m"])] + [round(v) for v in hr["temperature_2m"][sl][1:]],
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
        # all text is solid black for e-ink legibility (white only on the black "today" box)
        self.d.text(xy, s, font=font, fill=WHITE if fill == WHITE else BLACK, anchor=anchor)

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
        b += 58
        num = str(D["temp"])
        self.text((x+10, b), num, F(big, True), anchor="ls")
        nx = x+10+F(big, True).getlength(num)+2
        self.text((nx, b-big*0.72), "°C", F(24, True), anchor="lt")
        self.icon(icon_for(D["code"], D["is_day"]), x+w-52, b-big*0.36, 72)
        b += 20
        self.text((x+16, b), f'{round(D["temp"]*9/5+32)}°F    H:{D["hi"]}°  L:{D["lo"]}°', F(17, True), anchor="ls")
        n = D["now"]
        b += 36
        self.text((x+14, b), n.strftime("%A"), F(28, True), anchor="ls")
        b += 32
        date = f'{n.day} {n.strftime("%B %Y")}'
        sz = 26
        while sz > 19 and F(sz, True).getlength(date) > w-26:
            sz -= 1
        self.text((x+14, b), date, F(sz, True), anchor="ls")

    def sun_icon(self, cx, cy, up):
        d = self.d
        d.line([cx-11, cy+3, cx+11, cy+3], fill=BLACK, width=2)          # horizon
        d.pieslice([cx-7, cy-4, cx+7, cy+10], 180, 360, fill=BLACK)      # half sun
        ax = cx+15
        if up:
            d.line([ax, cy+4, ax, cy-9], fill=BLACK, width=2); d.polygon([(ax-4, cy-6), (ax+4, cy-6), (ax, cy-12)], fill=BLACK)
        else:
            d.line([ax, cy-9, ax, cy+4], fill=BLACK, width=2); d.polygon([(ax-4, cy+1), (ax+4, cy+1), (ax, cy+7)], fill=BLACK)

    def small_sun(self, x, y, w, h):
        D = self.D
        self.panel(x, y, w, h, "Daylight")
        for k, (t, up) in enumerate(((D["sunrise"], True), (D["sunset"], False))):
            base = y+52+k*28
            self.sun_icon(x+20, base-7, up)
            self.text((x+44, base), clock(t).replace("AM", "am").replace("PM", "pm"), F(20, True), anchor="ls")

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
        if al is None: names = ["unavailable"]
        elif not al: names = ["No active alerts"]
        else:
            names = []
            for n in al:                      # NWS often repeats the same alert (updates)
                if n not in names: names.append(n)
        fnt = F(14, True) if active else F(14)
        groups = []
        for n in names:                       # each alert on its own line(s), wrapped
            g, cur = [], ""
            for wd in n.split():
                t = (cur + " " + wd).strip()
                if fnt.getlength(t) <= w-54: cur = t
                else: g.append(cur); cur = wd
            groups.append(g + [cur])
        lines, shown = [], 0
        for g in groups:                      # max 3 lines; keep 1 for "and N more" if needed
            room = 3 if shown == len(groups) - 1 else 2
            if len(lines) + len(g) > room: break
            lines += g; shown += 1
        if shown < len(groups):
            lines.append(f"and {len(groups) - shown} more")
        for k, ln in enumerate(lines):
            self.text((x+44, cy + (k-(len(lines)-1)/2)*17), ln, fnt, anchor="lm")

    def next24(self, x, y, w, h, step=3):
        D = self.D
        self.panel(x, y, w, h, "Next 24 h")
        self.text((x+w-12, y+8), "Updated " + clock(D["now"]), F(12), anchor="ra")
        hrs, t, c = D["hours"], D["htemp"], D["hcond"]
        n = len(hrs)
        px0, px1 = x+56, x+w-22
        top, bot = y+80, y+h-24-65
        cbot = bot
        lo, hi = min(t)-1, max(t)+1
        X = lambda i: px0 + (px1-px0)*i/(n-1)
        Y = lambda v: cbot - (cbot-top)*(v-lo)/(hi-lo)
        pts = [(X(i), Y(v)) for i, v in enumerate(t)]
        self.d.polygon(pts + [(px1, cbot), (px0, cbot)], fill=PALE)
        self.d.line(pts, fill=BLACK, width=3)
        cwid = (px1-px0)/(n-1)
        wy0, wy1 = bot+4, bot+21
        py0, py1 = bot+24, bot+41
        iy0, iy1 = bot+44, bot+61
        lx = x+24
        wc = (wy0+wy1)/2; x0 = lx-13
        self.d.line([x0, wc-4, x0+16, wc-4], fill=BLACK, width=3)
        self.d.arc([x0+12, wc-13, x0+21, wc-4], -90, 180, fill=BLACK, width=3)
        self.d.line([x0-1, wc+4, x0+20, wc+4], fill=BLACK, width=3)
        self.d.arc([x0+16, wc+4, x0+25, wc+13], 0, 270, fill=BLACK, width=3)
        self.text((lx, (py0+py1)/2), "%", F(19, True), anchor="mm")
        dy_ = (iy0+iy1)/2+2
        self.d.polygon([(lx, dy_-12), (lx-6, dy_), (lx+6, dy_)], fill=BLACK)
        self.d.ellipse([lx-6.3, dy_-5, lx+6.3, dy_+7], fill=BLACK)
        for i in range(n):
            l, r = X(i)-cwid/2+1, X(i)+cwid/2-1
            ws, pr, mm = D["hwind"][i], D["hprob"][i], D["hmm"][i]
            wl = 0 if ws < 5 else 1 if ws < 20 else 2 if ws < 39 else 3
            rl = 0 if mm == 0 else 1 if mm < 2.5 else 2 if mm <= 7.6 else 3
            for (a, b_), frac, fill in (((wy0, wy1), wl/3, BLACK), ((py0, py1), pr/100, BLACK), ((iy0, iy1), rl/3, BLACK)):
                self.d.rectangle([l, a, r, b_], outline=MID)
                self.cfill(l, r, a, b_, frac, fill)
        lab_y = iy1
        idx = list(range(0, n, step)) + ([n-1] if (n-1) % step else [])
        for i in idx:
            px, py = pts[i]
            self.d.ellipse([px-4, py-4, px+4, py+4], fill=BLACK)
            self.text((px, py-8), f"{t[i]}°", F(14, True), anchor="mb")
            self.icon(c[i], px, y+40, 34)
            if i < n-1:   # no label under the last point: it would collide with the one before
                self.text((px, lab_y+5), "Now" if i == 0 else hl(hrs[i]), F(13, True), anchor="ma")

    def ten_day(self, x, y, w, h):
        D = self.D
        self.panel(x, y, w, h, "10-day forecast")
        days = D["days"]
        lo_all = min(d[2] for d in days); hi_all = max(d[3] for d in days)
        if hi_all == lo_all: hi_all += 1
        cw = (w-20)/len(days)
        rt, rb = y+116, y+h-26
        Yv = lambda v: rb-(rb-rt)*(v-lo_all)/(hi_all-lo_all)
        for i, (name, ic, lo, hi, pr) in enumerate(days):
            cx = x+10+cw*i+cw/2
            self.text((cx, y+22), name, F(14, True), anchor="ma")
            self.icon(ic, cx, y+58, 36)
            if pr >= 20: self.text((cx, y+80), f"{pr}%", F(11, True), anchor="ma")
            self.d.rounded_rectangle([cx-4, rt, cx+4, rb], radius=4, fill=LIGHT)   # full range track
            self.d.rounded_rectangle([cx-4, Yv(hi), cx+4, Yv(lo)], radius=4, fill=BLACK)      # this day's range
            if i == 0:
                m = Yv(min(max(D["temp"], lo_all), hi_all))
                self.d.ellipse([cx-5, m-5, cx+5, m+5], fill=WHITE, outline=BLACK, width=2)
            self.text((cx+2, rt-4), f"{hi}°", F(15, True), anchor="mb")   # highs on one row
            self.text((cx+2, rb+4), f"{lo}°", F(14), anchor="mt")         # lows on one row

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
                    s = min(cw, rh)*0.6
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
    c.small_alert(304, ys[0]+sh+8, 288, sh)
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
