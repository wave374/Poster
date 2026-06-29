import io
import re
import math
import textwrap
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H  = 1280, 720
WHITE = (255, 255, 255)
GRAY  = (180, 180, 180)
BLACK = (0, 0, 0)
GOLD  = (212, 168, 85)

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

# ─── HELPERS ──────────────────────────────────────────────────────────────────
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
        import os
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def extract_season(title):
    match = re.search(r'\b(season\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b', title, flags=re.IGNORECASE)
    if match:
        num = re.search(r'\d+', match.group(0)).group(0)
        clean = re.sub(r'\s*\b(season\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b', '', title, flags=re.IGNORECASE).strip()
        return clean, f"SEASON {num}"
    return title, None

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
            pts = [(cx + hex_size * math.cos(math.radians(60*i)),
                    cy + hex_size * math.sin(math.radians(60*i))) for i in range(6)]
            draw.polygon(pts, outline=hex_out, fill=hex_fill)

def _save(base):
    out = io.BytesIO()
    base.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out.read()

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

    return _save(base)

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
    syn_clean = re.sub(r'<[^>]+>|\[.*?\]|\(.*?\)', '', synopsis).strip()

    bg_src     = Image.open(io.BytesIO(photo_bytes)).convert("RGB").resize((W,H), Image.LANCZOS)
    bg_blurred = bg_src.filter(ImageFilter.GaussianBlur(32))
    base = Image.blend(bg_blurred, Image.new("RGB",(W,H),(8,9,14)), 0.78)

    vignette = Image.new("RGBA",(W,H),(0,0,0,0))
    vd = ImageDraw.Draw(vignette)
    for i in range(120):
        vd.rectangle([i,i,W-i,H-i], outline=(0,0,0,255-int(160*(i/120)**2)))
    base = Image.alpha_composite(base.convert("RGBA"), vignette).convert("RGB")
    draw = ImageDraw.Draw(base)

    LEFT = 72
    badge_text = f"◆  {brand.upper()}"
    f_badge = load_font(13, True)
    btw = draw.textbbox((0,0), badge_text, font=f_badge)[2]
    bh = 36; bx1, by1 = LEFT, 48; bx2, by2 = bx1+btw+32, by1+bh
    draw.rounded_rectangle([bx1,by1,bx2,by2], radius=18, outline=ACCENT, width=2)
    draw.text((bx1+16, by1+bh//2), badge_text, font=f_badge, fill=WHITE, anchor="lm")

    title_upper = clean_title.upper()
    ty = by2+32
    f_title = load_font(86, True)
    max_title_w = int(W*0.52)
    while f_title.size > 32:
        if draw.textbbox((0,0), title_upper, font=f_title)[2] <= max_title_w: break
        f_title = load_font(f_title.size-4, True)

    words = title_upper.split(); lines, current = [], []
    for word in words:
        test = " ".join(current+[word])
        if draw.textbbox((0,0), test, font=f_title)[2] <= max_title_w: current.append(word)
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
        draw.text((LEFT,ty), line, font=f_title, fill=WHITE); ty += line_h
    if season_text:
        f_s = load_font(int(f_title.size*0.42), True)
        draw.text((LEFT,ty+4), season_text, font=f_s, fill=ACCENT)
        ty += int(f_s.size*1.4)+4
    title_bottom = ty

    gy = title_bottom+24; gx = LEFT
    f_genre = load_font(12, True); pill_h = 32
    GENRE_COLORS = [(255,100,100),(0,210,200),(100,180,255),(180,100,255),(255,180,50),(100,255,150)]
    for g in genres:
        gtw = draw.textbbox((0,0), g.upper(), font=f_genre)[2]; pw = gtw+22
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

    card_x, card_y = LEFT, gy+pill_h+30; card_w, card_h = int(W*0.54), 148
    region = base.crop((card_x,card_y,card_x+card_w,card_y+card_h))
    blurred_r = region.filter(ImageFilter.GaussianBlur(16))
    cmask = Image.new("L",(card_w,card_h),0)
    ImageDraw.Draw(cmask).rounded_rectangle([0,0,card_w,card_h], radius=16, fill=255)
    base.paste(blurred_r,(card_x,card_y),cmask)
    tr = max(0,min(255,ACCENT[0]//6)); tg = max(0,min(255,ACCENT[1]//6)); tb = max(0,min(255,ACCENT[2]//6))
    tint_layer = Image.new("RGB",(card_w,card_h),(tr,tg,tb))
    tint_alpha = Image.new("L",(card_w,card_h),120)
    base.paste(tint_layer,(card_x,card_y), Image.composite(tint_alpha,Image.new("L",(card_w,card_h),0),cmask))
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle([card_x,card_y,card_x+card_w,card_y+card_h], radius=16, outline=ACCENT, width=1)
    f_syn = load_font(14); wrapped = textwrap.wrap(syn_clean, width=66)
    sy = card_y+20; text_color = tuple(min(255,180+c//4) for c in ACCENT)
    for line in wrapped[:5]:
        draw.text((card_x+20,sy), line, font=f_syn, fill=text_color); sy += 22
    if len(wrapped) > 5:
        draw.text((card_x+20,sy), "...read more", font=f_syn, fill=ACCENT)

    meta_y = H-72
    meta_items = [("STUDIO",studio),("EPISODES",episodes),("RELEASED",year),("FORMAT","TV"),("SCORE",f"{score}%")]
    col_w_m = card_w//len(meta_items)
    f_mlabel = load_font(10, True); f_mval = load_font(17, True)
    for idx,(label,val) in enumerate(meta_items):
        mx = card_x+idx*col_w_m
        draw.text((mx,meta_y), label, font=f_mlabel, fill=(110,110,120))
        draw.text((mx,meta_y+16), val, font=f_mval, fill=ACCENT if label=="SCORE" else WHITE)

    poster_x, poster_y = int(W*0.615), 40; poster_w, poster_h = int(W*0.285), H-90
    p_img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    tr2 = poster_w/poster_h; ir = p_img.width/p_img.height
    if ir > tr2:
        nw = int(p_img.height*tr2); p_img = p_img.crop(((p_img.width-nw)//2,0,(p_img.width-nw)//2+nw,p_img.height))
    else:
        nh = int(p_img.width/tr2); p_img = p_img.crop((0,(p_img.height-nh)//2,p_img.width,(p_img.height-nh)//2+nh))
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
    offset,cl,cw = 18,36,2; ax = ACCENT
    tlx,tly = poster_x-offset,poster_y-offset
    draw.line([(tlx,tly),(tlx+cl,tly)],fill=ax,width=cw); draw.line([(tlx,tly),(tlx,tly+cl)],fill=ax,width=cw)
    trx,try_ = poster_x+poster_w+offset,poster_y-offset
    draw.line([(trx-cl,try_),(trx,try_)],fill=ax,width=cw); draw.line([(trx,try_),(trx,try_+cl)],fill=ax,width=cw)
    blx,bly = poster_x-offset,poster_y+poster_h+offset
    draw.line([(blx,bly-cl),(blx,bly)],fill=ax,width=cw); draw.line([(blx,bly),(blx+cl,bly)],fill=ax,width=cw)
    brx,bry = poster_x+poster_w+offset,poster_y+poster_h+offset
    draw.line([(brx,bry-cl),(brx,bry)],fill=ax,width=cw); draw.line([(brx-cl,bry),(brx,bry)],fill=ax,width=cw)

    return _save(base)

# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 3 — Modern UI
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
    syn_clean = re.sub(r'<[^>]+>|\[.*?\]|\(.*?\)', '', synopsis).strip()

    bg = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    bg_ratio = bg.width / bg.height
    if bg_ratio > W / H: new_h = H; new_w = int(bg_ratio * H)
    else: new_w = W; new_h = int(W / bg_ratio)
    bg = bg.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - W) // 2; top = (new_h - H) // 2
    bg = bg.crop((left, top, left+W, top+H))
    bg_blur = bg.filter(ImageFilter.GaussianBlur(18))
    base = Image.blend(bg_blur, Image.new("RGB",(W,H),(8,6,16)), 0.52)
    draw = ImageDraw.Draw(base)

    LEFT = 60; BADGE_Y = 168
    GAP_BADGE_TITLE = 24; GAP_TITLE_DESC = 26; GAP_DESC_GENRE = 24; GAP_GENRE_META = 42

    # Glossy gradient badge
    badge_text = f"✦ {brand.upper()}"
    f_badge = load_font(13, True)
    btw = draw.textbbox((0,0), badge_text, font=f_badge)[2]
    bw, bh = btw + 40, 36; bx, by = LEFT, BADGE_Y
    bmask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(bmask).rounded_rectangle([0,0,bw,bh], radius=bh//2, fill=255)
    badge_img = Image.new("RGB", (bw, bh), ACCENT)
    for gx_b in range(bw):
        t = gx_b / bw
        r_ = int(min(255, ACCENT[0]+(1-t)*60)); g_ = int(min(255, ACCENT[1]+(1-t)*60)); b_ = int(min(255, ACCENT[2]+(1-t)*60))
        ImageDraw.Draw(badge_img).line([(gx_b,0),(gx_b,bh)], fill=(r_,g_,b_))
    for gy_b in range(bh//2):
        a2 = int(40*(1-gy_b/(bh//2)))
        r_ = min(255,ACCENT[0]+80); g_ = min(255,ACCENT[1]+80); b_ = min(255,ACCENT[2]+80)
        ImageDraw.Draw(badge_img).line([(0,gy_b),(bw,gy_b)], fill=(r_,g_,b_))
    glow_sz = 10
    glow = Image.new("RGBA", (bw+glow_sz*2, bh+glow_sz*2), (0,0,0,0))
    ImageDraw.Draw(glow).rounded_rectangle([glow_sz,glow_sz,bw+glow_sz,bh+glow_sz],
        radius=bh//2+glow_sz//2, fill=(ACCENT[0],ACCENT[1],ACCENT[2],70))
    glow = glow.filter(ImageFilter.GaussianBlur(7))
    base.paste(Image.new("RGB",glow.size,(0,0,0)), (bx-glow_sz,by-glow_sz), glow.split()[3])
    base.paste(badge_img, (bx,by), bmask)
    draw = ImageDraw.Draw(base)
    draw.text((bx+20, by+bh//2), badge_text, font=f_badge, fill=WHITE, anchor="lm")

    # Title
    ty = by + bh + GAP_BADGE_TITLE; max_title_w = int(W*0.575)
    f_title = load_font(72, True)
    while f_title.size > 32:
        if draw.textbbox((0,0), display_title, font=f_title)[2] <= max_title_w: break
        f_title = load_font(f_title.size-3, True)
    words = display_title.split(); lines, cur = [], []
    for word in words:
        test = " ".join(cur+[word])
        if draw.textbbox((0,0), test, font=f_title)[2] <= max_title_w: cur.append(word)
        else:
            if cur: lines.append(" ".join(cur))
            cur = [word]
    if cur: lines.append(" ".join(cur))
    line_h = int(f_title.size*1.08)
    for line in lines[:2]:
        draw.text((LEFT, ty), line, font=f_title, fill=WHITE); ty += line_h
    title_bottom = ty

    # Description card
    card_x = LEFT; card_y = title_bottom+GAP_TITLE_DESC; card_w = int(W*0.505); card_h = 128; bar_w = 4; pad = 20
    region = base.crop((card_x,card_y,card_x+card_w,card_y+card_h)).filter(ImageFilter.GaussianBlur(18))
    cmask = Image.new("L",(card_w,card_h),0)
    ImageDraw.Draw(cmask).rounded_rectangle([0,0,card_w,card_h], radius=10, fill=255)
    base.paste(region,(card_x,card_y),cmask)
    tint = Image.new("RGB",(card_w,card_h),(10,7,20))
    base.paste(tint,(card_x,card_y), Image.composite(Image.new("L",(card_w,card_h),175),Image.new("L",(card_w,card_h),0),cmask))
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle([card_x,card_y,card_x+bar_w,card_y+card_h], radius=2, fill=ACCENT)
    f_syn = load_font(14); wrapped = textwrap.wrap(syn_clean, width=60); sy = card_y+pad
    for line in wrapped[:4]:
        draw.text((card_x+bar_w+pad, sy), line, font=f_syn, fill=(205,200,220)); sy += 26
    if len(wrapped) > 4: draw.text((card_x+bar_w+pad, sy), "...", font=f_syn, fill=(150,140,170))

    # Genre pills with glow
    gy = card_y+card_h+GAP_DESC_GENRE; gx = LEFT; f_genre = load_font(12, True); pill_h = 32
    for g in genres:
        gtw = draw.textbbox((0,0), g.upper(), font=f_genre)[2]; pw = gtw+26
        pmask = Image.new("L",(pw,pill_h),0)
        ImageDraw.Draw(pmask).rounded_rectangle([0,0,pw,pill_h], radius=pill_h//2, fill=255)
        pill_bg = Image.new("RGB",(pw,pill_h),(int(ACCENT[0]*0.12),int(ACCENT[1]*0.12),int(ACCENT[2]*0.12)))
        base.paste(pill_bg,(gx,gy),pmask)
        draw = ImageDraw.Draw(base)
        pg_sz = 5
        pg = Image.new("RGBA",(pw+pg_sz*2,pill_h+pg_sz*2),(0,0,0,0))
        ImageDraw.Draw(pg).rounded_rectangle([pg_sz,pg_sz,pw+pg_sz,pill_h+pg_sz],
            radius=pill_h//2+pg_sz//2, fill=(ACCENT[0],ACCENT[1],ACCENT[2],50))
        pg = pg.filter(ImageFilter.GaussianBlur(4))
        base.paste(Image.new("RGB",pg.size,(0,0,0)),(gx-pg_sz,gy-pg_sz),pg.split()[3])
        draw = ImageDraw.Draw(base)
        draw.rounded_rectangle([gx,gy,gx+pw,gy+pill_h], radius=pill_h//2, outline=ACCENT, width=2)
        draw.text((gx+pw//2,gy+pill_h//2), g.upper(), font=f_genre, fill=ACCENT, anchor="mm")
        gx += pw+12

    # Metadata
    meta_y = gy+pill_h+GAP_GENRE_META; f_label = load_font(11,True); f_val = load_font(22,True)
    meta_items = [("STUDIO",studio),("EPISODES",episodes),("SCORE",f"{score}%"),("RATING","R")]
    mx = LEFT
    for label,val in meta_items:
        draw.text((mx,meta_y), label, font=f_label, fill=ACCENT)
        draw.text((mx,meta_y+20), val, font=f_val, fill=WHITE); mx += 110

    # Right portrait
    pw_img = int(W*0.255); ph_img = int(pw_img*1.42)
    px = W-pw_img-55; py = (H-ph_img)//2
    p_img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    ratio = pw_img/ph_img; ir = p_img.width/p_img.height
    if ir > ratio:
        nw = int(p_img.height*ratio); p_img = p_img.crop(((p_img.width-nw)//2,0,(p_img.width-nw)//2+nw,p_img.height))
    else:
        nh = int(p_img.width/ratio); p_img = p_img.crop((0,(p_img.height-nh)//2,p_img.width,(p_img.height-nh)//2+nh))
    p_img = p_img.resize((pw_img,ph_img), Image.LANCZOS)
    rmask = Image.new("L",(pw_img,ph_img),0)
    ImageDraw.Draw(rmask).rounded_rectangle([0,0,pw_img,ph_img], radius=18, fill=255)
    sh = 28
    shadow = Image.new("RGBA",(pw_img+sh*2,ph_img+sh*2),(0,0,0,0))
    ImageDraw.Draw(shadow).rounded_rectangle([sh,sh,pw_img+sh,ph_img+sh], radius=20, fill=(0,0,0,160))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    base.paste(Image.new("RGB",shadow.size,(0,0,0)),(px-sh,py-sh),shadow.split()[3])
    base.paste(p_img,(px,py),rmask)
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle([px,py,px+pw_img,py+ph_img], radius=18, outline=(90,75,115), width=1)

    return _save(base)

# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 4 — Channel Banner
# ═══════════════════════════════════════════════════════════════════════════════
def build_poster_banner(anime, photo_bytes, brand, theme_name="green"):
    theme  = THEMES.get(theme_name, THEMES["green"])
    ACCENT = theme["accent"]

    title    = anime.get("title_english") or anime.get("title", "UNKNOWN")
    genres   = [g["name"].upper() for g in anime.get("genres", [])][:3]
    synopsis = anime.get("synopsis") or "No synopsis available."
    clean_title, season_text = extract_season(title)
    if season_text:
        season_num = re.search(r'\d+', season_text).group(0)
        display_title = f"{clean_title.upper()} S{season_num.zfill(2)}"
    else:
        display_title = clean_title.upper()
    syn_clean = re.sub(r'<[^>]+>|\[.*?\]|\(.*?\)', '', synopsis).strip()

    base = Image.new("RGB", (W, H), (0,0,0))
    char = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    cr = char.width/char.height
    if cr > W/H:
        nw = int(char.height*(W/H)); char = char.crop(((char.width-nw)//2,0,(char.width-nw)//2+nw,char.height))
    else:
        nh = int(char.width/(W/H)); char = char.crop((0,(char.height-nh)//2,char.width,(char.height-nh)//2+nh))
    char = char.resize((W,H), Image.LANCZOS)

    base_arr = base.convert("RGBA"); char_arr = char.convert("RGBA")
    result = Image.new("RGBA",(W,H))
    fade_start = int(W*0.30); fade_end = int(W*0.55)
    for x in range(W):
        if x < fade_start: alpha = 0
        elif x < fade_end:
            t = (x-fade_start)/(fade_end-fade_start); alpha = int(255*(t**1.6))
        else: alpha = 255
        for y in range(H):
            cp = char_arr.getpixel((x,y)); bp = base_arr.getpixel((x,y))
            blended = tuple(int(bp[i]*(1-alpha/255)+cp[i]*(alpha/255)) for i in range(3))
            result.putpixel((x,y), blended+(255,))
    base = result.convert("RGB")

    vig = Image.new("RGBA",(W,H),(0,0,0,0)); vd = ImageDraw.Draw(vig)
    for i in range(60):
        a = int(180*(1-i/60))
        vd.rectangle([0,i,W,i+1], fill=(0,0,0,a)); vd.rectangle([0,H-i-1,W,H-i], fill=(0,0,0,a))
    base = Image.alpha_composite(base.convert("RGBA"), vig).convert("RGB")
    draw = ImageDraw.Draw(base)

    top_text = "O F F I C I A L   H I N D I   D U B B E D"
    f_top = load_font(16, True)
    tw = draw.textbbox((0,0), top_text, font=f_top)[2]
    draw.text(((W-tw)//2, 28), top_text, font=f_top, fill=(220,220,220))

    LEFT = 72
    draw.text((LEFT, 185), brand.upper(), font=load_font(15,True), fill=ACCENT)

    f_title = load_font(90, True); max_title_w = int(W*0.50)
    while f_title.size > 36:
        bbox = draw.textbbox((0,0), display_title, font=f_title)
        if (bbox[2]-bbox[0]) <= max_title_w: break
        f_title = load_font(f_title.size-4, True)

    words = display_title.split(); lines, cur = [], []
    for word in words:
        test = " ".join(cur+[word])
        if draw.textbbox((0,0), test, font=f_title)[2] <= max_title_w: cur.append(word)
        else:
            if cur: lines.append(" ".join(cur))
            cur = [word]
    if cur: lines.append(" ".join(cur))

    ty = 222; line_h = int(f_title.size*1.08)
    for line in lines[:3]:
        draw.text((LEFT,ty), line, font=f_title, fill=WHITE); ty += line_h
    title_bottom = ty

    f_syn_hdr = load_font(20, True); sy_hdr_y = title_bottom+14
    draw.text((LEFT,      sy_hdr_y), "‼",        font=f_syn_hdr, fill=(220,50,50))
    draw.text((LEFT+36,   sy_hdr_y), " SYNOPSIS", font=f_syn_hdr, fill=ACCENT)

    f_syn = load_font(15); wrapped = textwrap.wrap(syn_clean, width=58); sy = sy_hdr_y+36
    for line in wrapped[:3]:
        draw.text((LEFT,sy), line, font=f_syn, fill=(210,210,210)); sy += 26
    if len(wrapped) > 3:
        draw.text((LEFT,sy), "...read more", font=f_syn, fill=(170,170,170)); sy += 26

    gy = sy+10; gx = LEFT; f_genre = load_font(16,True)
    for g in genres:
        draw.text((gx,gy), g, font=f_genre, fill=WHITE)
        gx += draw.textbbox((0,0), g, font=f_genre)[2]+48

    line_y = gy+30
    draw.line([(LEFT,line_y),(LEFT+520,line_y)], fill=(200,200,200), width=1)

    badge_y = line_y+20; icon_r = 26; icon_cx = LEFT+icon_r; icon_cy = badge_y+icon_r
    draw.ellipse([icon_cx-icon_r,icon_cy-icon_r,icon_cx+icon_r,icon_cy+icon_r], fill=ACCENT)
    draw.polygon([(icon_cx-10,icon_cy+6),(icon_cx+12,icon_cy-2),(icon_cx-3,icon_cy+2)], fill=WHITE)
    draw.polygon([(icon_cx-10,icon_cy+6),(icon_cx-3,icon_cy+2),(icon_cx-6,icon_cy-4)], fill=(220,220,220))

    f_pill = load_font(15,True); pill_text = brand.upper()
    ptw = draw.textbbox((0,0), pill_text, font=f_pill)[2]
    pill_x = icon_cx+icon_r+6; pill_w = ptw+32; pill_h2 = icon_r*2; pill_y = icon_cy-icon_r
    pmask = Image.new("L",(pill_w,pill_h2),0)
    ImageDraw.Draw(pmask).rounded_rectangle([0,0,pill_w,pill_h2], radius=pill_h2//2, fill=255)
    base.paste(Image.new("RGB",(pill_w,pill_h2),WHITE),(pill_x,pill_y),pmask)
    draw = ImageDraw.Draw(base)
    draw.text((pill_x+pill_w//2,pill_y+pill_h2//2), pill_text, font=f_pill, fill=BLACK, anchor="mm")

    return _save(base)