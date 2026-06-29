import os
import io
import time
import threading
import re
import math
import textwrap
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

# ── Dummy HTTP server ──
class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    def log_message(self, *args):
        pass

_port = int(os.environ.get("PORT", 10000))
_server = HTTPServer(("0.0.0.0", _port), _Handler)
threading.Thread(target=_server.serve_forever, daemon=True).start()
print(f"Dummy server listening on port {_port}")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN  = "8955163269:AAHuq5mCGQZlPaoDdiTJAtBSFeelgz74sAU"
BRAND_NAME = "ANIMEFLIO"
JIKAN_API  = "https://api.jikan.moe/v4"

ASK_ANIME, ASK_CONFIRM, ASK_PHOTO, ASK_STYLE, ASK_COLOR, ASK_BRAND = range(6)

# ─── COLOR THEMES ─────────────────────────────────────────────────────────────
THEMES = {
    "green":  {"accent": (34, 197, 94),  "bg": (13, 26, 13),  "hex_out": (30, 55, 30),  "hex_fill": (13, 22, 13), "emoji": "🟢"},
    "orange": {"accent": (251, 146, 60), "bg": (26, 16, 8),   "hex_out": (55, 30, 10),  "hex_fill": (22, 13, 6),  "emoji": "🟠"},
    "cyan":   {"accent": (34, 211, 238), "bg": (8, 22, 26),   "hex_out": (10, 45, 55),  "hex_fill": (6, 18, 22),  "emoji": "🔵"},
    "red":    {"accent": (239, 68, 68),  "bg": (26, 10, 10),  "hex_out": (55, 15, 15),  "hex_fill": (22, 8, 8),   "emoji": "🔴"},
    "purple": {"accent": (168, 85, 247), "bg": (18, 10, 26),  "hex_out": (40, 20, 55),  "hex_fill": (15, 8, 22),  "emoji": "🟣"},
    "blue":   {"accent": (59, 130, 246), "bg": (8, 14, 26),   "hex_out": (15, 30, 55),  "hex_fill": (6, 12, 22),  "emoji": "💙"},
    "pink":   {"accent": (236, 72, 153), "bg": (26, 8, 18),   "hex_out": (55, 15, 40),  "hex_fill": (22, 6, 16),  "emoji": "🩷"},
    "yellow": {"accent": (234, 179, 8),  "bg": (26, 22, 5),   "hex_out": (55, 48, 10),  "hex_fill": (22, 19, 4),  "emoji": "🟡"},
    "white":  {"accent": (255, 255, 255),"bg": (20, 20, 20),  "hex_out": (180,180,180), "hex_fill": (35, 35, 35), "emoji": "⚪"},
}

GOLD  = (212, 168, 85)
WHITE = (255, 255, 255)
GRAY  = (180, 180, 180)
BLACK = (0, 0, 0)
W, H  = 1280, 720

# ─── FONT LOADER ──────────────────────────────────────────────────────────────
def load_font(size, bold=False):
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "C:/Windows/Fonts/arialbd.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "C:/Windows/Fonts/arial.ttf"]
    )
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# ─── SEASON EXTRACTOR ─────────────────────────────────────────────────────────
def extract_season(title):
    match = re.search(r'\b(season\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b',
                      title, flags=re.IGNORECASE)
    if match:
        num = re.search(r'\d+', match.group(0)).group(0)
        clean = re.sub(r'\s*\b(season\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b',
                       '', title, flags=re.IGNORECASE).strip()
        return clean, f"SEASON {num}"
    return title, None

# ─── HEX GRID ─────────────────────────────────────────────────────────────────
def draw_hex_grid(draw, width, height, hex_out, hex_fill):
    hex_size = 55
    hex_h    = math.sqrt(3) * hex_size
    col_w    = hex_size * 2 * 0.75
    cols = int(width / col_w) + 2
    rows = int(height / hex_h) + 2
    for col in range(cols):
        for row in range(rows):
            cx = col * col_w - hex_size
            cy = row * hex_h + (hex_h / 2 if col % 2 else 0) - hex_h / 2
            pts = [
                (cx + hex_size * math.cos(math.radians(60 * i)),
                 cy + hex_size * math.sin(math.radians(60 * i)))
                for i in range(6)
            ]
            draw.polygon(pts, outline=hex_out, fill=hex_fill)

# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 1 — Classic Hex
# ═══════════════════════════════════════════════════════════════════════════════
def build_poster_hex(anime, photo_bytes, brand, theme_name="green"):
    theme   = THEMES.get(theme_name, THEMES["green"])
    ACCENT  = theme["accent"]
    BG_DARK = theme["bg"]

    title    = anime.get("title_english") or anime.get("title", "UNKNOWN")
    genres   = [g["name"].upper() for g in anime.get("genres", [])][:3]
    synopsis = anime.get("synopsis") or "No synopsis available."
    clean_title, season_text = extract_season(title)

    base = Image.new("RGB", (W, H), BG_DARK)
    draw_hex_grid(ImageDraw.Draw(base), W, H, theme["hex_out"], theme["hex_fill"])

    char_img = Image.open(io.BytesIO(photo_bytes)).convert("RGBA")
    char_w   = int(W * 0.62)
    scale    = H / char_img.height
    new_w    = int(char_img.width * scale)
    char_img = char_img.resize((new_w, H), Image.LANCZOS)
    if new_w > char_w:
        char_img = char_img.crop(((new_w-char_w)//2, 0, (new_w-char_w)//2+char_w, H))
    elif new_w < char_w:
        padded = Image.new("RGBA", (char_w, H), (0,0,0,0))
        padded.paste(char_img, ((char_w-new_w)//2, 0))
        char_img = padded

    fade_mask = Image.new("L", (char_w, H), 0)
    fade_zone = int(char_w * 0.55)
    for x in range(char_w):
        alpha = int(255 * ((x/fade_zone)**2.2)) if x < fade_zone else 255
        ImageDraw.Draw(fade_mask).line([(x,0),(x,H)], fill=alpha)

    char_rgba = char_img.convert("RGBA")
    r, g, b, a = char_rgba.split()
    a = Image.composite(a, Image.new("L", a.size, 0), fade_mask)
    char_rgba = Image.merge("RGBA", (r, g, b, a))
    base_rgba = base.convert("RGBA")
    base_rgba.paste(char_rgba, (W-char_w, 0), char_rgba)
    base = base_rgba.convert("RGB")

    overlay = Image.new("RGBA", (W, H), (0,0,0,0))
    ov_draw = ImageDraw.Draw(overlay)
    for x in range(int(W*0.52)):
        alpha = int(180*(1-x/(W*0.52))**0.5)
        ov_draw.line([(x,0),(x,H)], fill=(BG_DARK[0],BG_DARK[1],BG_DARK[2],alpha))
    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(base)

    logo_cx, logo_cy, logo_r = 30, 30, 20
    hex_pts = [(logo_cx+logo_r*math.cos(math.radians(60*i-30)),
                logo_cy+logo_r*math.sin(math.radians(60*i-30))) for i in range(6)]
    draw.polygon(hex_pts, outline=ACCENT, fill=BG_DARK)
    draw.text((logo_cx, logo_cy), brand[0].upper(), font=load_font(20,True), fill=ACCENT, anchor="mm")
    draw.text((58, 18), brand.upper(), font=load_font(17,True), fill=WHITE)

    title_upper = clean_title.upper()
    f_title = load_font(96, True)
    max_w = int(W*0.48)
    while f_title.size > 40:
        if draw.textbbox((0,0), title_upper, font=f_title)[2] <= max_w: break
        f_title = load_font(f_title.size-6, True)
    ty = int(H*0.28)
    draw.text((38, ty), title_upper, font=f_title, fill=WHITE)
    title_bottom = draw.textbbox((38, ty), title_upper, font=f_title)[3]

    if season_text:
        f_season = load_font(int(f_title.size*0.55), True)
        draw.text((38, title_bottom+6), season_text, font=f_season, fill=ACCENT)
        title_bottom = draw.textbbox((38, title_bottom+6), season_text, font=f_season)[3]

    gy, gx = title_bottom+20, 38
    f_genre = load_font(16, True)
    for gen in genres:
        draw.text((gx, gy), gen, font=f_genre, fill=GOLD)
        gx += draw.textbbox((0,0), gen, font=f_genre)[2]+28

    f_syn = load_font(15)
    syn_clean = re.sub(r'\[.*?\]|\(.*?\)', '', synopsis).strip()
    wrapped = textwrap.wrap(syn_clean, width=48)
    sy = gy+36
    for line in wrapped[:6]:
        draw.text((38, sy), line, font=f_syn, fill=GRAY)
        sy += 24
    if len(wrapped) > 6:
        draw.text((38, sy), "...read more", font=f_syn, fill=ACCENT)
        sy += 24

    btn_y = sy+18
    f_btn = load_font(16, True)
    for i, label in enumerate(["DOWNLOAD", "JOIN NOW"]):
        bx = 38+i*220
        bw, bh = 195, 48
        draw.rounded_rectangle([bx,btn_y,bx+bw,btn_y+bh], radius=5, fill=ACCENT)
        tw = draw.textbbox((0,0), label, font=f_btn)[2]
        draw.text((bx+(bw-tw)//2, btn_y+14), label, font=f_btn, fill=BLACK)

    out = io.BytesIO()
    base.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out.read()

# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 2 — Cinematic
# ═══════════════════════════════════════════════════════════════════════════════
def build_poster_cinematic(anime, photo_bytes, brand, theme_name="cyan"):
    theme  = THEMES.get(theme_name, THEMES["cyan"])
    ACCENT = theme["accent"]

    title    = anime.get("title_english") or anime.get("title", "UNKNOWN")
    genres   = [g["name"] for g in anime.get("genres", [])][:4]
    synopsis = anime.get("synopsis") or "No synopsis available."
    score    = anime.get("score") or "N/A"
    episodes = str(anime.get("episodes") or "?")
    year     = str(anime.get("year") or "N/A")
    studio   = str(anime.get("studio") or "Unknown")
    clean_title, season_text = extract_season(title)

    syn_clean = re.sub(r'<[^>]+>', '', synopsis)
    syn_clean = re.sub(r'\[.*?\]|\(.*?\)', '', syn_clean).strip()

    bg_src     = Image.open(io.BytesIO(photo_bytes)).convert("RGB").resize((W,H), Image.LANCZOS)
    bg_blurred = bg_src.filter(ImageFilter.GaussianBlur(32))
    base = Image.blend(bg_blurred, Image.new("RGB",(W,H),(8,9,14)), 0.78)

    vignette = Image.new("RGBA",(W,H),(0,0,0,0))
    vd = ImageDraw.Draw(vignette)
    for i in range(120):
        vd.rectangle([i,i,W-i,H-i], outline=(0,0,0,255-int(160*(i/120)**2)))
    base = Image.alpha_composite(base.convert("RGBA"), vignette).convert("RGB")
    draw = ImageDraw.Draw(base)

    LEFT, TOP = 72, 48
    badge_text = f"◆  {brand.upper()}"
    f_badge = load_font(13, True)
    btw = draw.textbbox((0,0), badge_text, font=f_badge)[2]
    bh = 36
    bx1, by1 = LEFT, TOP
    bx2, by2 = bx1+btw+32, by1+bh
    draw.rounded_rectangle([bx1,by1,bx2,by2], radius=18, outline=ACCENT, width=2)
    draw.text((bx1+16, by1+bh//2), badge_text, font=f_badge, fill=WHITE, anchor="lm")

    title_upper = clean_title.upper()
    ty = by2+32
    f_title = load_font(86, True)
    max_title_w = int(W*0.52)
    while f_title.size > 32:
        if draw.textbbox((0,0), title_upper, font=f_title)[2] <= max_title_w: break
        f_title = load_font(f_title.size-4, True)

    words = title_upper.split()
    lines, current = [], []
    for word in words:
        test = " ".join(current+[word])
        if draw.textbbox((0,0), test, font=f_title)[2] <= max_title_w:
            current.append(word)
        else:
            if current: lines.append(" ".join(current))
            current = [word]
    if current: lines.append(" ".join(current))
    line_h = int(f_title.size*1.15)

    glow_layer = Image.new("RGBA",(W,H),(0,0,0,0))
    gd = ImageDraw.Draw(glow_layer)
    glow_ty = ty
    for line in lines[:3]:
        gd.text((LEFT,glow_ty), line, font=f_title, fill=(255,255,255,90))
        glow_ty += line_h
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(7))
    base = Image.alpha_composite(base.convert("RGBA"), glow_layer).convert("RGB")
    draw = ImageDraw.Draw(base)

    for line in lines[:3]:
        draw.text((LEFT,ty), line, font=f_title, fill=WHITE)
        ty += line_h

    if season_text:
        f_s = load_font(int(f_title.size*0.42), True)
        draw.text((LEFT,ty+4), season_text, font=f_s, fill=ACCENT)
        ty += int(f_s.size*1.4)+4
    title_bottom = ty

    gy = title_bottom+24
    gx = LEFT
    f_genre = load_font(12, True)
    pill_h = 32
    GENRE_COLORS = [(255,100,100),(0,210,200),(100,180,255),(180,100,255),(255,180,50),(100,255,150)]
    for g in genres:
        gtw = draw.textbbox((0,0), g.upper(), font=f_genre)[2]
        pw = gtw+22
        pill_bg = Image.new("RGBA",(pw,pill_h),(0,0,0,0))
        pmask = Image.new("L",(pw,pill_h),0)
        ImageDraw.Draw(pmask).rounded_rectangle([0,0,pw,pill_h], radius=16, fill=255)
        pill_color = tuple(max(0,c-200) for c in ACCENT)
        ImageDraw.Draw(pill_bg).rounded_rectangle([0,0,pw,pill_h], radius=16, fill=pill_color)
        base.paste(pill_bg.convert("RGB"), (gx,gy), pmask)
        draw = ImageDraw.Draw(base)
        gc = GENRE_COLORS[genres.index(g) % len(GENRE_COLORS)]
        draw.rounded_rectangle([gx,gy,gx+pw,gy+pill_h], radius=16, outline=gc, width=2)
        draw.text((gx+pw//2,gy+pill_h//2), g.upper(), font=f_genre, fill=gc, anchor="mm")
        gx += pw+10

    card_x, card_y = LEFT, gy+pill_h+30
    card_w, card_h = int(W*0.54), 148
    region = base.crop((card_x,card_y,card_x+card_w,card_y+card_h))
    blurred_r = region.filter(ImageFilter.GaussianBlur(16))
    cmask = Image.new("L",(card_w,card_h),0)
    ImageDraw.Draw(cmask).rounded_rectangle([0,0,card_w,card_h], radius=16, fill=255)
    base.paste(blurred_r,(card_x,card_y),cmask)
    tint_r = max(0,min(255,ACCENT[0]//6))
    tint_g = max(0,min(255,ACCENT[1]//6))
    tint_b = max(0,min(255,ACCENT[2]//6))
    tint_layer = Image.new("RGB",(card_w,card_h),(tint_r,tint_g,tint_b))
    tint_alpha = Image.new("L",(card_w,card_h),120)
    base.paste(tint_layer,(card_x,card_y),
               Image.composite(tint_alpha,Image.new("L",(card_w,card_h),0),cmask))
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle([card_x,card_y,card_x+card_w,card_y+card_h], radius=16, outline=ACCENT, width=1)
    f_syn = load_font(14)
    wrapped = textwrap.wrap(syn_clean, width=66)
    sy = card_y+20
    text_color = tuple(min(255,180+c//4) for c in ACCENT)
    for line in wrapped[:5]:
        draw.text((card_x+20,sy), line, font=f_syn, fill=text_color)
        sy += 22
    if len(wrapped) > 5:
        draw.text((card_x+20,sy), "...read more", font=f_syn, fill=ACCENT)

    meta_y = H-72
    meta_items = [("STUDIO",studio),("EPISODES",episodes),("RELEASED",year),("FORMAT","TV"),("SCORE",f"{score}%")]
    col_w_m = card_w//len(meta_items)
    f_mlabel = load_font(10, True)
    f_mval   = load_font(17, True)
    for idx,(label,val) in enumerate(meta_items):
        mx = card_x+idx*col_w_m
        draw.text((mx,meta_y), label, font=f_mlabel, fill=(110,110,120))
        draw.text((mx,meta_y+16), val, font=f_mval, fill=ACCENT if label=="SCORE" else WHITE)

    poster_x, poster_y = int(W*0.615), 40
    poster_w, poster_h = int(W*0.285), H-90
    p_img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    tr = poster_w/poster_h
    ir = p_img.width/p_img.height
    if ir > tr:
        nw = int(p_img.height*tr)
        p_img = p_img.crop(((p_img.width-nw)//2,0,(p_img.width-nw)//2+nw,p_img.height))
    else:
        nh = int(p_img.width/tr)
        p_img = p_img.crop((0,(p_img.height-nh)//2,p_img.width,(p_img.height-nh)//2+nh))
    p_img = p_img.resize((poster_w,poster_h), Image.LANCZOS)
    pmask2 = Image.new("L",(poster_w,poster_h),0)
    ImageDraw.Draw(pmask2).rounded_rectangle([0,0,poster_w,poster_h], radius=20, fill=255)
    sh_sz = 20
    shadow = Image.new("RGBA",(poster_w+sh_sz*2,poster_h+sh_sz*2),(0,0,0,0))
    ImageDraw.Draw(shadow).rounded_rectangle([sh_sz,sh_sz,poster_w+sh_sz,poster_h+sh_sz], radius=22, fill=(0,0,0,100))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    base.paste(Image.new("RGB",shadow.size,(0,0,0)),(poster_x-sh_sz,poster_y-sh_sz),shadow.split()[3])
    base.paste(p_img,(poster_x,poster_y),pmask2)
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle([poster_x,poster_y,poster_x+poster_w,poster_y+poster_h], radius=20, outline=(180,180,195), width=1)
    offset,cl,cw = 18,36,2
    ax = ACCENT
    tlx,tly = poster_x-offset,poster_y-offset
    draw.line([(tlx,tly),(tlx+cl,tly)],fill=ax,width=cw)
    draw.line([(tlx,tly),(tlx,tly+cl)],fill=ax,width=cw)
    trx,try_ = poster_x+poster_w+offset,poster_y-offset
    draw.line([(trx-cl,try_),(trx,try_)],fill=ax,width=cw)
    draw.line([(trx,try_),(trx,try_+cl)],fill=ax,width=cw)
    blx,bly = poster_x-offset,poster_y+poster_h+offset
    draw.line([(blx,bly-cl),(blx,bly)],fill=ax,width=cw)
    draw.line([(blx,bly),(blx+cl,bly)],fill=ax,width=cw)
    brx,bry = poster_x+poster_w+offset,poster_y+poster_h+offset
    draw.line([(brx,bry-cl),(brx,bry)],fill=ax,width=cw)
    draw.line([(brx-cl,bry),(brx,bry)],fill=ax,width=cw)

    out = io.BytesIO()
    base.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out.read()

# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 3 — Modern UI (Netflix/AniList style)
# ═══════════════════════════════════════════════════════════════════════════════
def build_poster_modern(anime, photo_bytes, brand, theme_name="purple"):
    theme  = THEMES.get(theme_name, THEMES["purple"])
    ACCENT = theme["accent"]

    title    = anime.get("title_english") or anime.get("title", "UNKNOWN")
    genres   = [g["name"] for g in anime.get("genres", [])][:3]
    synopsis = anime.get("synopsis") or "No synopsis available."
    score    = str(anime.get("score") or "N/A")
    episodes = str(anime.get("episodes") or "?")
    studio   = str(anime.get("studio") or "Unknown")
    clean_title, season_text = extract_season(title)
    display_title = f"{clean_title.upper()} {season_text}" if season_text else clean_title.upper()

    syn_clean = re.sub(r'<[^>]+>', '', synopsis)
    syn_clean = re.sub(r'\[.*?\]|\(.*?\)', '', syn_clean).strip()

    # ── LAYER 1+2+3: Full canvas blurred bg + dark overlay ──
    bg = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    # cover-scale to fill full W×H
    bg_ratio = bg.width / bg.height
    if bg_ratio > W / H:
        new_h = H
        new_w = int(bg_ratio * H)
    else:
        new_w = W
        new_h = int(W / bg_ratio)
    bg = bg.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - W) // 2
    top  = (new_h - H) // 2
    bg = bg.crop((left, top, left+W, top+H))

    # heavy blur
    bg_blur = bg.filter(ImageFilter.GaussianBlur(30))

    # uniform dark overlay 62% opacity
    dark = Image.new("RGB", (W, H), (8, 6, 16))
    base = Image.blend(bg_blur, dark, 0.62)

    draw = ImageDraw.Draw(base)

    # ── SPACING SYSTEM ──
    LEFT   = 60   # outer left margin
    BADGE_Y = 168  # badge top
    GAP_BADGE_TITLE = 24
    GAP_TITLE_DESC  = 26
    GAP_DESC_GENRE  = 24
    GAP_GENRE_META  = 42

    # ── Brand badge (filled pill) ──
    badge_text = f"✦ {brand.upper()}"
    f_badge = load_font(13, True)
    btw = draw.textbbox((0,0), badge_text, font=f_badge)[2]
    bw, bh = btw + 32, 34
    bx, by = LEFT, BADGE_Y
    bmask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(bmask).rounded_rectangle([0,0,bw,bh], radius=bh//2, fill=255)
    badge_img = Image.new("RGB", (bw, bh), ACCENT)
    base.paste(badge_img, (bx, by), bmask)
    draw = ImageDraw.Draw(base)
    draw.text((bx+16, by+bh//2), badge_text, font=f_badge, fill=WHITE, anchor="lm")

    # ── Title ──
    ty = by + bh + GAP_BADGE_TITLE
    max_title_w = int(W * 0.575)
    f_title = load_font(72, True)
    while f_title.size > 32:
        if draw.textbbox((0,0), display_title, font=f_title)[2] <= max_title_w: break
        f_title = load_font(f_title.size - 3, True)

    # word wrap
    words = display_title.split()
    lines, cur = [], []
    for word in words:
        test = " ".join(cur + [word])
        if draw.textbbox((0,0), test, font=f_title)[2] <= max_title_w:
            cur.append(word)
        else:
            if cur: lines.append(" ".join(cur))
            cur = [word]
    if cur: lines.append(" ".join(cur))

    line_h = int(f_title.size * 1.08)
    for line in lines[:2]:
        draw.text((LEFT, ty), line, font=f_title, fill=WHITE)
        ty += line_h
    title_bottom = ty

    # ── Description card (glassmorphism, left accent bar) ──
    card_x  = LEFT
    card_y  = title_bottom + GAP_TITLE_DESC
    card_w  = int(W * 0.505)
    card_h  = 128
    bar_w   = 4
    pad     = 20

    # blur behind card
    region = base.crop((card_x, card_y, card_x+card_w, card_y+card_h))
    region = region.filter(ImageFilter.GaussianBlur(18))
    cmask  = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(cmask).rounded_rectangle([0,0,card_w,card_h], radius=10, fill=255)
    base.paste(region, (card_x, card_y), cmask)
    # dark tint
    tint = Image.new("RGB", (card_w, card_h), (14, 10, 26))
    base.paste(tint, (card_x, card_y),
               Image.composite(Image.new("L",(card_w,card_h),155),
                                Image.new("L",(card_w,card_h),0), cmask))
    draw = ImageDraw.Draw(base)
    # accent left bar
    draw.rounded_rectangle([card_x, card_y, card_x+bar_w, card_y+card_h],
                           radius=2, fill=ACCENT)
    # synopsis text
    f_syn   = load_font(14)
    wrapped = textwrap.wrap(syn_clean, width=60)
    sy = card_y + pad
    for line in wrapped[:4]:
        draw.text((card_x+bar_w+pad, sy), line, font=f_syn, fill=(205,200,220))
        sy += 26
    if len(wrapped) > 4:
        draw.text((card_x+bar_w+pad, sy), "...", font=f_syn, fill=(150,140,170))

    # ── Genre pills ──
    gy = card_y + card_h + GAP_DESC_GENRE
    gx = LEFT
    f_genre = load_font(12, True)
    pill_h  = 32
    for g in genres:
        gtw = draw.textbbox((0,0), g.upper(), font=f_genre)[2]
        pw  = gtw + 26
        pmask = Image.new("L", (pw, pill_h), 0)
        ImageDraw.Draw(pmask).rounded_rectangle([0,0,pw,pill_h], radius=pill_h//2, fill=255)
        # very dark fill
        pill_bg = Image.new("RGB", (pw, pill_h), (20, 15, 35))
        base.paste(pill_bg, (gx, gy), pmask)
        draw = ImageDraw.Draw(base)
        draw.rounded_rectangle([gx,gy,gx+pw,gy+pill_h], radius=pill_h//2, outline=WHITE, width=2)
        draw.text((gx+pw//2, gy+pill_h//2), g.upper(), font=f_genre, fill=WHITE, anchor="mm")
        gx += pw + 12

    # ── Metadata row ──
    meta_y  = gy + pill_h + GAP_GENRE_META
    f_label = load_font(11, True)
    f_val   = load_font(22, True)
    meta_items = [("STUDIO", studio), ("EPISODES", episodes),
                  ("SCORE", f"{score}%"), ("RATING", "R")]
    mx = LEFT
    col_gap = 110
    for label, val in meta_items:
        draw.text((mx, meta_y),      label, font=f_label, fill=ACCENT)
        draw.text((mx, meta_y + 20), val,   font=f_val,   fill=WHITE)
        mx += col_gap

    # ── Right portrait image — smaller, vertically centered, floating ──
    right_margin = 55
    pw_img = int(W * 0.255)   # ~327px — 15% smaller than before
    ph_img = int(pw_img * 1.42)  # movie poster ratio
    px = W - pw_img - right_margin
    py = (H - ph_img) // 2   # vertically centered

    p_img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    ratio = pw_img / ph_img
    ir    = p_img.width / p_img.height
    if ir > ratio:
        nw = int(p_img.height * ratio)
        p_img = p_img.crop(((p_img.width-nw)//2, 0, (p_img.width-nw)//2+nw, p_img.height))
    else:
        nh = int(p_img.width / ratio)
        p_img = p_img.crop((0, (p_img.height-nh)//2, p_img.width, (p_img.height-nh)//2+nh))
    p_img = p_img.resize((pw_img, ph_img), Image.LANCZOS)

    # rounded mask
    rmask = Image.new("L", (pw_img, ph_img), 0)
    ImageDraw.Draw(rmask).rounded_rectangle([0,0,pw_img,ph_img], radius=18, fill=255)

    # cinematic shadow
    sh = 28
    shadow = Image.new("RGBA", (pw_img+sh*2, ph_img+sh*2), (0,0,0,0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [sh, sh, pw_img+sh, ph_img+sh], radius=20, fill=(0,0,0,160))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    base.paste(Image.new("RGB", shadow.size, (0,0,0)),
               (px-sh, py-sh), shadow.split()[3])

    base.paste(p_img, (px, py), rmask)
    draw = ImageDraw.Draw(base)
    # subtle border
    draw.rounded_rectangle([px, py, px+pw_img, py+ph_img],
                           radius=18, outline=(90, 75, 115), width=1)

    out = io.BytesIO()
    base.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out.read()

# ─── ANIME FETCH ──────────────────────────────────────────────────────────────
def fetch_anime(name: str) -> list[dict]:
    try:
        query = """
        query ($search: String) {
          Page(perPage: 10) {
            media(search: $search, type: ANIME) {
              title { english romaji }
              genres averageScore episodes
              description(asHtml: false)
              startDate { year }
              studios(isMain: true) { nodes { name } }
            }
          }
        }
        """
        r = requests.post("https://graphql.anilist.co",
                          json={"query": query, "variables": {"search": name}},
                          timeout=20)
        if r.status_code == 200:
            items = r.json()["data"]["Page"]["media"]
            results = []
            for item in items:
                studios = item.get("studios", {}).get("nodes", [])
                results.append({
                    "title_english": item["title"].get("english") or item["title"].get("romaji"),
                    "title": item["title"].get("romaji") or item["title"].get("english"),
                    "genres": [{"name": g} for g in (item.get("genres") or [])],
                    "score": round((item.get("averageScore") or 0) / 10, 1) or "N/A",
                    "episodes": item.get("episodes") or "?",
                    "synopsis": item.get("description") or "No synopsis available.",
                    "year": (item.get("startDate") or {}).get("year"),
                    "studio": studios[0]["name"] if studios else "Unknown",
                })
            if results:
                return results
    except Exception:
        pass
    for attempt in range(3):
        try:
            r = requests.get(f"{JIKAN_API}/anime",
                             params={"q": name, "limit": 10}, timeout=30,
                             headers={"User-Agent": "AnimePosterBot/1.0"})
            if r.status_code in (429, 503, 504):
                time.sleep(4); continue
            if r.status_code == 200:
                data = r.json().get("data", [])
                if data: return data
        except Exception:
            time.sleep(3)
    return []

# ─── SHARED: ask anime name ───────────────────────────────────────────────────
async def _ask_anime_name(send_func):
    await send_func(
        "🔍 Eɴᴛᴇʀ ᴛʜᴇ *ᴀɴɪᴍᴇ ɴᴀᴍᴇ* ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ᴘᴏsᴛᴇʀ ғᴏʀ:",
        parse_mode="Markdown"
    )

# ─── HANDLERS ─────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    first = update.effective_user.first_name
    welcome_text = (
        f"*ʜᴇʟʟᴏ, {first}*\n\n"
        ">ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴀɴɪᴍᴇғʟɪᴏ ᴘᴏsᴛᴇʀ ʙᴏᴛ\n\n"
        ">ɪ'ᴍ ʏᴏᴜʀ ᴀᴜᴛᴏ ᴛʜᴜᴍʙɴᴀɪʟ ᴍᴀᴋᴇʀ, ʀᴇᴀᴅʏ ᴛᴏ ᴄʀᴇᴀᴛᴇ sᴛᴜɴɴɪɴɢ ᴀɴɪᴍᴇ ᴅᴇsɪɢɴs ғᴏʀ ʏᴏᴜ\\."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("• ᴍʏ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅꜱ •", callback_data="show_commands")],
        [InlineKeyboardButton("• ᴅᴇᴠᴇʟᴏᴘᴇʀ", callback_data="developer"),
         InlineKeyboardButton("ᴄʟᴏꜱᴇ •", callback_data="cmd_cancel")],
    ])
    await update.message.reply_photo(
        photo="https://i.postimg.cc/RF6b28py/e25348fdc52abcafa9e951f6a3d1a51a.jpg",
        caption=welcome_text, parse_mode="MarkdownV2", reply_markup=keyboard
        message_effect_id="5104841245755180586"
    )

async def show_commands_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("• ᴄʀᴇᴀᴛᴇ ᴘᴏꜱᴛᴇʀ •", callback_data="cmd_anime")],
        [InlineKeyboardButton("• ᴄʜᴀɴɢᴇ ʙʀᴀɴᴅ •", callback_data="cmd_brand")],
        [InlineKeyboardButton("ᴄʟᴏꜱᴇ", callback_data="cmd_cancel")],
    ])
    await update.callback_query.edit_message_reply_markup(reply_markup=keyboard)

async def cmd_cancel_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.delete()

async def developer_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dev_text = (
        "*ᴅᴇᴠᴇʟᴏᴘᴇʀ ɪɴғᴏ\\.\\.\\.*\n\n"
        "» ᴄʀᴇᴀᴛᴏʀ: [WAVE](https://t.me/wave_189)\n"
        "» ʙᴏᴛ: [Aᴜɢᴜsᴛᴀ](https://t.me/Roxy_x_bot)\n"
        "» sᴜᴘᴘᴏʀᴛ: [Sᴜᴘᴘᴏʀᴛ ᴄʜᴀᴛ](https://t.me/wave_domain)"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("ʙᴀᴄᴋ", callback_data="back_start"),
         InlineKeyboardButton("ᴄʟᴏꜱᴇ", callback_data="cmd_cancel")],
    ])
    await query.edit_message_caption(caption=dev_text, parse_mode="MarkdownV2", reply_markup=keyboard)

async def back_start_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    first = update.effective_user.first_name
    welcome_text = (
        f"*ʜᴇʟʟᴏ, {first}*\n\n"
        ">ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴀɴɪᴍᴇғʟɪᴏ ᴘᴏsᴛᴇʀ ʙᴏᴛ\n\n"
        ">ɪ'ᴍ ʏᴏᴜʀ ᴀᴜᴛᴏ ᴛʜᴜᴍʙɴᴀɪʟ ᴍᴀᴋᴇʀ, ʀᴇᴀᴅʏ ᴛᴏ ᴄʀᴇᴀᴛᴇ sᴛᴜɴɴɪɴɢ ᴀɴɪᴍᴇ ᴅᴇsɪɢɴs ғᴏʀ ʏᴏᴜ\\."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("• ᴍʏ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅꜱ •", callback_data="show_commands")],
        [InlineKeyboardButton("• ᴅᴇᴠᴇʟᴏᴘᴇʀ", callback_data="developer"),
         InlineKeyboardButton("ᴄʟᴏꜱᴇ •", callback_data="cmd_cancel")],
    ])
    await query.edit_message_caption(caption=welcome_text, parse_mode="MarkdownV2", reply_markup=keyboard)

async def cmd_anime_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    await query.message.reply_text(
        "🔍 Eɴᴛᴇʀ ᴛʜᴇ *ᴀɴɪᴍᴇ ɴᴀᴍᴇ* ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ᴘᴏsᴛᴇʀ ғᴏʀ:",
        parse_mode="Markdown"
    )
    return ASK_ANIME

async def cmd_anime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "🔍 Eɴᴛᴇʀ ᴛʜᴇ *ᴀɴɪᴍᴇ ɴᴀᴍᴇ* ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ᴘᴏsᴛᴇʀ ғᴏʀ:",
        parse_mode="Markdown"
    )
    return ASK_ANIME

async def received_anime_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _handle_anime_search(update, ctx)

async def _handle_anime_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    await update.message.reply_text(f"⏳ Searching for *{name}*...", parse_mode="Markdown")
    try:
        results = fetch_anime(name)
    except Exception:
        await update.message.reply_text("⏳ API is slow. Please wait and try /anime again.")
        return ConversationHandler.END
    if not results:
        await update.message.reply_text("❌ No anime found. Try a different name.")
        return ASK_ANIME
    ctx.user_data["results"] = results
    buttons = [
        [InlineKeyboardButton(
            f"{a.get('title_english') or a['title']} ({a.get('year') or '?'})",
            callback_data=str(i)
        )]
        for i, a in enumerate(results[:10])
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.message.reply_text("📋 Select the correct anime:",
                                    reply_markup=InlineKeyboardMarkup(buttons))
    return ASK_CONFIRM

async def anime_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END
    anime = ctx.user_data["results"][int(query.data)]
    ctx.user_data["anime"] = anime
    title  = anime.get("title_english") or anime["title"]
    genres = ", ".join(g["name"] for g in anime.get("genres", [])[:3]) or "N/A"
    await query.edit_message_text(
        f"✅ *{title}*\n🎭 Genres: {genres}\n\n"
        f"📸 Now send the *background / character image* for the poster:",
        parse_mode="Markdown"
    )
    return ASK_PHOTO

async def received_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1] if update.message.photo else None
    doc   = update.message.document
    if not photo and not doc:
        await update.message.reply_text("⚠️ Please send a photo or image file.")
        return ASK_PHOTO
    file        = await ctx.bot.get_file(photo.file_id if photo else doc.file_id)
    photo_bytes = await file.download_as_bytearray()
    ctx.user_data["photo_bytes"] = bytes(photo_bytes)

    await update.message.reply_text(
        "🖼️ Choose your *poster style*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎴 Style 1 — Classic Hex",  callback_data="style_hex")],
            [InlineKeyboardButton("🎬 Style 2 — Cinematic",    callback_data="style_cinematic")],
            [InlineKeyboardButton("🖥️ Style 3 — Modern UI",   callback_data="style_modern")],
        ])
    )
    return ASK_STYLE

async def style_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["style"] = query.data.replace("style_", "")
    buttons = [
        [
            InlineKeyboardButton(f"{THEMES[c]['emoji']} {c.capitalize()}", callback_data=f"color_{c}")
            for c in list(THEMES.keys())[i:i+2]
        ]
        for i in range(0, len(THEMES), 2)
    ]
    await query.edit_message_text(
        "🎨 Choose your *poster color theme*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ASK_COLOR

async def color_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    theme_name = query.data.replace("color_", "")
    style      = ctx.user_data.get("style", "hex")
    await query.edit_message_text(
        f"🎨 Creating your *{theme_name}* poster, please wait...",
        parse_mode="Markdown"
    )
    try:
        anime       = ctx.user_data["anime"]
        photo_bytes = ctx.user_data["photo_bytes"]
        brand       = ctx.user_data.get("brand", BRAND_NAME)

        if style == "cinematic":
            poster_bytes = build_poster_cinematic(anime, photo_bytes, brand, theme_name)
        elif style == "modern":
            poster_bytes = build_poster_modern(anime, photo_bytes, brand, theme_name)
        else:
            poster_bytes = build_poster_hex(anime, photo_bytes, brand, theme_name)

        title = anime.get("title_english") or anime["title"]
        await query.message.reply_photo(
            photo=io.BytesIO(poster_bytes),
            caption=f"🎌 *{title}* — {THEMES[theme_name]['emoji']} {theme_name.capitalize()} poster ready!\n\nSend /anime to make another.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.message.reply_text(f"❌ Failed to create poster: {e}")
    return ConversationHandler.END

async def cmd_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    current = ctx.user_data.get("brand", BRAND_NAME)
    await update.message.reply_text(
        f"🏷️ Current brand: *{current}*\n\nSend the new brand name:",
        parse_mode="Markdown"
    )
    return ASK_BRAND

async def cmd_brand_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    current = ctx.user_data.get("brand", BRAND_NAME)
    await update.callback_query.message.reply_text(
        f"🏷️ Current brand: *{current}*\n\nSend the new brand name:",
        parse_mode="Markdown"
    )
    return ASK_BRAND

async def received_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["brand"] = update.message.text.strip().upper()
    await update.message.reply_text(
        f"✅ Brand set to: *{ctx.user_data['brand']}*", parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    anime_conv = ConversationHandler(
        entry_points=[
            CommandHandler("anime", cmd_anime),
            CallbackQueryHandler(cmd_anime_callback, pattern="^cmd_anime$"),
        ],
        states={
            ASK_ANIME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, received_anime_name)],
            ASK_CONFIRM: [CallbackQueryHandler(anime_selected)],
            ASK_PHOTO:   [MessageHandler(filters.PHOTO | filters.Document.IMAGE, received_photo)],
            ASK_STYLE:   [CallbackQueryHandler(style_selected, pattern="^style_")],
            ASK_COLOR:   [CallbackQueryHandler(color_selected, pattern="^color_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        per_chat=True,
    )

    brand_conv = ConversationHandler(
        entry_points=[
            CommandHandler("brand", cmd_brand),
            CallbackQueryHandler(cmd_brand_callback, pattern="^cmd_brand$"),
        ],
        states={
            ASK_BRAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_brand)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(anime_conv)
    app.add_handler(brand_conv)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(show_commands_callback, pattern="^show_commands$"))
    app.add_handler(CallbackQueryHandler(cmd_cancel_callback,    pattern="^cmd_cancel$"))
    app.add_handler(CallbackQueryHandler(developer_callback,     pattern="^developer$"))
    app.add_handler(CallbackQueryHandler(back_start_callback,    pattern="^back_start$"))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
