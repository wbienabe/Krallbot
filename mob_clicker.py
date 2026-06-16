#!/usr/bin/env python3
"""KrallBot grind helper — auto-select nearest monster + spell spam, with a GUI.

Pure mouse/keyboard input (like AHK) — no packets, nothing for the anti-cheat to
detect. Monster names in Silkroad are WHITE (players/NPCs are coloured), so we
click the nearest white name to select it, and spam the skill keys on it.

F8 = start/stop (sélection des mobs + spam des sorts)
F7 = capture debug (debug_mob.png)   |   fermer la fenêtre = quitter

Keep the GAME window focused while it runs (the keys go to the active window).
"""
from __future__ import annotations
import ctypes
import os
import sys
import threading
import time
import tkinter as tk
import winsound

import mss
import numpy as np

user32 = ctypes.windll.user32

# dossier des fichiers (à côté de l'.exe, sinon à côté du .py). Important : en admin
# le dossier courant est system32, donc on ancre tout sur l'emplacement réel.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- CONFIG ----------------------------------------------------------------
SELECT_PERIOD = 2.5        # secondes entre deux sélections (défaut ; éditable en ms dans le bot)
PERIOD_FILE = os.path.join(BASE_DIR, "period_ms.txt")
# --- laisse / retour a la maison (rester dans un rayon autour du point de depart) ---
LEASH_RANGE = 70           # rayon (unites X/Y) ; au-dela -> retour. Editable dans le bot
LEASH_FILE = os.path.join(BASE_DIR, "leash.txt")
RETURN_ON_FILE = os.path.join(BASE_DIR, "return_on.txt")   # retour maison activé ?
LEASH_INNER = 15           # "rentre" quand a moins de ca de la maison
CAST_SETTLE = 0.7          # attente pour finir le sort en cours avant de bouger
MOVE_SETTLE = 1.2          # attente apres un clic (le perso marche jusqu'au point)
RETURN_FRAC = 0.9          # clic loin = 90% du chemin vers le bord (gros pas monde)
RETURN_FRAC_NEAR = 0.45    # clic moins loin quand on approche (pas de depassement)
RETURN_STEPS = 10          # nb max de clics pour rentrer
VK_HIDE = 0x56             # touche 'v' maintenue pendant le retour (cache les mobs)
KEY_DELAY = 0.04           # délai entre touches de sort (comme ton AHK)
# touches de sorts = AZERTY & é " ' ( - _  (slots 1,2,3,4,5,6,8)
SPELL_KEYS = [0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x38]
WHITE_MIN = 220           # nom de mob = blanc PUR (coeur 255) ; neige/glace/quête plafonnent ~207-214
GRAY_TOL = 32              # écart max entre R/G/B : un nom de mob est BLANC (peu saturé)
NAME_CLICK_DROP = 45       # clic X px sous le nom (sur le corps du mob)
MARGIN_TOP = 140
# fenêtre de chat (coin bas-gauche)
CHAT_W = 440
CHAT_H = 460
# berserk auto sur les Giant : icône dorée de rang dans la fenêtre de cible (haut, centrée)
BERSERK_KEY = 0x09         # Tab
GIANT_Y0 = 56              # ligne du rang dans la fenêtre de cible (px depuis le haut)
GIANT_Y1 = 92
GIANT_X0 = -66            # fenêtre de l'icône, par rapport au centre de l'écran
GIANT_X1 = -8
GIANT_GOLD_MIN = 15        # Giant ~28, général ~3, champion ~0 -> seuil 15
GIANT_LOCK_MAX = 60.0      # sécurité : jamais verrouillé sur un giant plus de 60 s
GIANT_LOSE_GRACE = 1.5     # garde le verrou si l'icône a été vue il y a moins de ça (anti-flicker)
GIANT_CONFIRM_TRIES = 6    # relectures du rang après un clic (la fenêtre de cible peut tarder)
MARGIN_BOTTOM = 150
MARGIN_LEFT = 10
MARGIN_RIGHT = 230
# zone autour de toi à ignorer (toi + ton pet, au centre). Asymétrique : plus
# bas, car le nom du pet ("< No name >") s'affiche juste sous le tien.
PLAYER_UP = 140
PLAYER_DOWN = 205
PLAYER_HALFW = 160
# exclusion qui SUIT ton nom (texte vert). Marge large = "plus ou moins vert".
GREEN_MIN = 115            # le vert (canal G) au moins à ça
GREEN_MARGIN = 24          # G doit dépasser R et B d'au moins ça (marge couleur)
GREEN_DX0, GREEN_DX1 = -135, 150   # boîte autour du nom (couvre le pet juste dessous)
GREEN_DY0, GREEN_DY1 = -26, 95
# secours si le vert n'est pas détecté : petite zone centrée
SELF_DX, SELF_DY = 0, 0
SELF_HALFW = 120
SELF_UP, SELF_DOWN = 130, 130
# --- lecture des coords X/Y (texte blanc en haut a droite). Recherche DYNAMIQUE :
# on trouve la ligne de chiffres dans le coin, et la taille est normalisee avant
# comparaison -> marche a n'importe quelle resolution.
COORD_W = 300       # largeur de recherche depuis le bord droit
COORD_H = 56        # hauteur de recherche (au-dessus de la minimap)
COORD_DIGITS_MAX = 5  # une coord a au plus ~5 chiffres ; au-dela = fusion de 2 lignes (misread)
COORD_MAX = 30000   # |coord| plausible ; au-dela = misread OCR -> rejeté
COORD_STEP = 600    # saut max plausible entre 2 lectures (~0.6 s) ; au-dela = misread/téléport
COORD_ANCHOR_MIN = 3  # un saut n'est cru qu'apres 3 lectures cohérentes d'affilée (anti-misread)
LEASH_CONFIRM_SEC = 1.5  # il faut rester hors-range au moins ça avant de rentrer (anti-spike)
DIGIT_TPL = {
    "0": ".###.#...##...##...##...##...##...##...#.###.",
    "1": "...##..#####.##...##...##...##...##...##...##",
    "2": ".###.#...#....#....#...#....#...#...#...#####",
    "3": ".###.#...#....#....#..##.....#....##...#.###.",
    "4": "...#...##...##..#.#..#.#.#..#.#####...#....#.",
    "5": ".####.#...#....####.#...#....#....##...#.###.",
    "6": ".###.#...##....#.##.##..##...##...##...#.###.",
    "7": "#####...#....#...#....#....#...#....#....#...",
    "8": ".###.#...##...##...#.###.#...##...##...#.###.",
    "9": ".###.#...##...##...##..##.##.#....##...#.###.",
}
MIN_BLOB = 16
EXCLUDE_RADIUS = 90        # ne pas re-cibler un mob à moins de X px d'une cible récente
RECENT_KEEP = 3            # nb de dernières cibles à éviter

# --- thème Silkroad Online (or / brun / parchemin) --------------------------
C_BG = "#1a1206"           # brun très sombre (fond)
C_PANEL = "#2c1d0c"        # panneau bois
C_EDGE = "#c9a227"         # or (bordures)
C_GOLD = "#f0d27a"         # or clair (titre)
C_GOLD_DIM = "#9c7b2e"     # or terni (légende)
C_PARCH = "#e6d6b0"        # parchemin (texte info)
C_RUN = "#f2c94c"          # or vif (en cours)
C_STOP = "#c0552c"         # rouge brique (arrêté)
# ----------------------------------------------------------------------------

state = {"running": False, "target": None, "attacks": 0, "selects": 0,
         "blobs": 0, "winrect": None, "giant": False, "gold": 0,
         "period": SELECT_PERIOD, "xy": ("--", "--"),
         "leash": LEASH_RANGE, "home": None, "returning": False, "ret_dir": 0,
         "leash_on": True}
_stop = False


def _win_exclude(mon):
    """Rect (frame coords) de la fenêtre du bot, pour ne jamais cliquer dessus."""
    wr = state.get("winrect")
    if not wr:
        return []
    x, y, ww, hh = wr
    pad = 10
    return [(x - mon["left"] - pad, y - mon["top"] - pad,
             x - mon["left"] + ww + pad, y - mon["top"] + hh + pad)]


def click(x, y):
    user32.SetCursorPos(int(x), int(y))
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.02)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def press_key(vk):
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.01)
    user32.keybd_event(vk, 0, 2, 0)


def key_down(vk):
    return user32.GetAsyncKeyState(vk) & 0x8000 != 0


CELL = 12                  # grille fine pour bien découper les noms


def _cluster_names(dense, gh, gw):
    """Connected-components sur la grille de cellules -> centres des textes (x, y)."""
    dd = dense.tolist()
    sj = [[False] * gw for _ in range(gh)]
    names = []
    for i in range(gh):
        row = dd[i]
        for j in range(gw):
            if not row[j] or sj[i][j]:
                continue
            stack = [(i, j)]
            sj[i][j] = True
            cells = []
            while stack:
                y, x = stack.pop()
                cells.append((y, x))
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1),
                               (y, x + 2), (y + 1, x + 1), (y + 1, x - 1)):
                    if 0 <= ny < gh and 0 <= nx < gw and dd[ny][nx] and not sj[ny][nx]:
                        sj[ny][nx] = True
                        stack.append((ny, nx))
            yy = [c[0] for c in cells]
            xx = [c[1] for c in cells]
            wc = max(xx) - min(xx) + 1
            hc = max(yy) - min(yy) + 1
            # un nom = texte horizontal : qq cellules de large, 1-3 de haut, + large que haut
            if 3 <= wc <= 22 and 1 <= hc <= 3 and wc >= hc + 1 and len(cells) >= 4:
                mx = (min(xx) + max(xx)) / 2 * CELL + CELL // 2
                my = (min(yy) + max(yy)) / 2 * CELL + CELL // 2
                names.append((int(mx), int(my)))
    return names


def _player_green(img, w, h):
    """Centre de TON nom (texte vert) le plus proche du centre, ou None."""
    cx, cy = w // 2, h // 2
    ri = img[:, :, 0].astype(np.int16)
    gi = img[:, :, 1].astype(np.int16)
    bi = img[:, :, 2].astype(np.int16)
    green = (gi >= GREEN_MIN) & (gi - ri >= GREEN_MARGIN) & (gi - bi >= GREEN_MARGIN)
    green[:max(0, cy - 360), :] = False           # fenêtre autour de toi
    green[min(h, cy + 120):, :] = False
    green[:, :max(0, cx - 360)] = False
    green[:, min(w, cx + 360):] = False
    gh, gw = h // CELL, w // CELL
    dense = green[:gh * CELL, :gw * CELL].reshape(gh, CELL, gw, CELL).sum(axis=(1, 3)) >= 5
    blobs = _cluster_names(dense, gh, gw)
    if not blobs:
        return None
    return min(blobs, key=lambda p: (p[0] - cx) ** 2 + (p[1] - (cy - 80)) ** 2)


def _names(img, w, h, exclude_rects=()):
    """Return list of (x, y) name centres (white name-text blobs)."""
    r, g, b = img[:, :, 0], img[:, :, 1], img[:, :, 2]
    # vrai BLANC seulement : tous les canaux clairs ET peu saturés.
    # -> rejette le texte de quête vert/jaune (un canal domine).
    mx = np.maximum(np.maximum(r, g), b).astype(np.int16)
    mn = np.minimum(np.minimum(r, g), b).astype(np.int16)
    white = (r >= WHITE_MIN) & (g >= WHITE_MIN) & (b >= WHITE_MIN) & ((mx - mn) <= GRAY_TOL)
    white[:MARGIN_TOP, :] = False
    white[h - MARGIN_BOTTOM:, :] = False
    white[:, :MARGIN_LEFT] = False
    white[:, w - MARGIN_RIGHT:] = False
    cx, cy = w // 2, h // 2
    white[h - CHAT_H:, :CHAT_W] = False           # fenêtre de chat (bas-gauche)
    for (x0, y0, x1, y1) in exclude_rects:        # zone de la fenêtre du bot
        x0 = max(0, x0); y0 = max(0, y0); x1 = min(w, x1); y1 = min(h, y1)
        if x1 > x0 and y1 > y0:
            white[y0:y1, x0:x1] = False
    pg = _player_green(img, w, h)                 # exclusion qui suit ton nom vert
    if pg:
        gx, gy = pg
        white[max(0, gy + GREEN_DY0):min(h, gy + GREEN_DY1),
              max(0, gx + GREEN_DX0):min(w, gx + GREEN_DX1)] = False
    else:                                         # secours : petite zone centrée
        sx, sy = cx + SELF_DX, cy + SELF_DY
        white[max(0, sy - SELF_UP):min(h, sy + SELF_DOWN),
              max(0, sx - SELF_HALFW):min(w, sx + SELF_HALFW)] = False
    gh, gw = h // CELL, w // CELL
    dense = white[:gh * CELL, :gw * CELL].reshape(gh, CELL, gw, CELL).sum(axis=(1, 3)) >= 6
    # ignore white text sitting on a TEAL UI box (quest tracker "Hunt X Red Yeowa")
    ri, gi, bi = r.astype(np.int16), g.astype(np.int16), b.astype(np.int16)
    teal = (gi >= 80) & (bi >= 80) & (ri <= 110) & (gi - ri >= 20) & (bi - ri >= 20)
    # only a SOLID teal cell (the quest box), not scattered bluish magic effects
    tcell = teal[:gh * CELL, :gw * CELL].reshape(gh, CELL, gw, CELL).sum(axis=(1, 3)) >= (CELL * CELL // 2)
    d = tcell.copy()                             # dilate by 1 cell only
    d[1:, :] |= tcell[:-1, :]; d[:-1, :] |= tcell[1:, :]
    d[:, 1:] |= tcell[:, :-1]; d[:, :-1] |= tcell[:, 1:]
    dense &= ~d
    return _cluster_names(dense, gh, gw)


def detect(img, w, h, avoid=(), exclude_rects=()):
    cx, cy = w // 2, h // 2
    names = _names(img, w, h, exclude_rects)
    if not names:
        return None, 0
    # exclude names too close to a recently-picked spot (= same mob)
    r2 = EXCLUDE_RADIUS ** 2
    fresh = [p for p in names
             if all((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2 > r2 for a in avoid)]
    pool = fresh if fresh else names           # si tous évités, on reprend le + proche
    # nearest name to the character (centre, slightly up)
    best = min(pool, key=lambda p: (p[0] - cx) ** 2 + (p[1] - (cy - 40)) ** 2)
    return best, len(names)


def _giant_gold(img, w, h):
    """Compte les pixels dorés dans l'icône de rang de la fenêtre de cible."""
    cx = w // 2
    x0 = max(0, cx + GIANT_X0)
    x1 = min(w, cx + GIANT_X1)
    reg = img[GIANT_Y0:GIANT_Y1, x0:x1]
    r = reg[:, :, 0].astype(np.int16)
    g = reg[:, :, 1].astype(np.int16)
    b = reg[:, :, 2].astype(np.int16)
    gold = (r > 170) & (g > 120) & (b < 120) & (r - b > 70) & (g - b > 40)
    return int(gold.sum())


def is_giant(img, w, h):
    return _giant_gold(img, w, h) >= GIANT_GOLD_MIN


CHAR_ARR = {c: np.array([1 if p == "#" else 0 for p in s]) for c, s in DIGIT_TPL.items()}


def _resize(g, H=9, W=5):
    h, w = g.shape
    return g[(np.arange(H) * h // H)][:, (np.arange(W) * w // W)]


def _match_char(g):
    a = _resize(g).astype(int).flatten()
    best, bs = None, -1
    for c, t in CHAR_ARR.items():
        s = int((a == t).sum())
        if s > bs:
            bs, best = s, c
    return best if bs >= 36 else None            # rejette ":" et le bruit


def _read_band(band):
    """Decoupe une bande horizontale en glyphes -> ([(centre_x, caractere)], [centres_rates]).
    'rates' = blobs de la taille d'un chiffre qu'on n'a PAS su lire. Un chiffre rate au
    milieu d'un nombre fausse la coord d'un facteur ~10 (ex: -1877 lu -827), donc on le
    signale pour rejeter la lecture plutot que de laisser le chiffre disparaitre."""
    cols = band.any(axis=0)
    out, fail = [], []
    i, n = 0, len(cols)
    while i < n:
        if cols[i]:
            j = i
            while j < n and cols[j]:
                j += 1
            sub = band[:, i:j]
            rows = sub.any(axis=1)
            ys = np.where(rows)[0]
            if rows.sum() >= 3 and (j - i) >= 2:
                c = _match_char(sub[ys.min():ys.max() + 1, :])
                if c:
                    out.append(((i + j) // 2, c))
                elif 3 <= (j - i) <= 12 and rows.sum() >= 6:
                    fail.append((i + j) // 2)        # chiffre probable mais illisible
            elif (3 <= (j - i) <= 10 and 1 <= rows.sum() <= 3
                  and ys.min() >= band.shape[0] // 2 - 4
                  and ys.max() <= band.shape[0] // 2 + 3):
                out.append(((i + j) // 2, "-"))     # barre fine centree = signe moins
            i = j
        else:
            i += 1
    return out, fail


def _clean_coord(s):
    """Garde un eventuel '-' en tete (coord negative), jette le reste du bruit.
    Rejette aussi un groupe trop long = fusion de deux lignes (misread)."""
    neg = s.startswith("-")
    digits = "".join(c for c in s if c.isdigit())
    if not digits or len(digits) > COORD_DIGITS_MAX:
        return ""
    return ("-" + digits) if neg else digits


def read_xy(img, w, h):
    """Lit X/Y dynamiquement : la ligne des coords est la seule a donner plein de
    chiffres propres. On la trouve, puis on separe X/Y au plus grand espace.
    Taille normalisee -> marche a n'importe quelle resolution."""
    reg = img[0:COORD_H, max(0, w - COORD_W):w]
    r, g, b = reg[:, :, 0], reg[:, :, 1], reg[:, :, 2]
    white = (r > 165) & (g > 165) & (b > 150)
    best, bfail = [], []
    for cy in range(7, COORD_H - 6, 2):
        d, f = _read_band(white[cy - 7:cy + 8, :])
        if len(d) > len(best):
            best, bfail = d, f
    if len(best) < 4:                            # ligne des coords = au moins 4 chiffres
        return "", ""
    split = max(range(len(best) - 1), key=lambda k: best[k + 1][0] - best[k][0])
    xg, yg = best[:split + 1], best[split + 1:]
    xs = "".join(c for _, c in xg)
    ys = "".join(c for _, c in yg)
    # un chiffre illisible A L'INTERIEUR d'un nombre -> chiffre disparu, coord fausse : on rejette
    if any(xg[0][0] < fc < xg[-1][0] for fc in bfail):
        xs = ""
    if any(yg[0][0] < fc < yg[-1][0] for fc in bfail):
        ys = ""
    return _clean_coord(xs), _clean_coord(ys)


def coords_loop():
    """Lit le X/Y (en haut a droite) toutes les ~0.6 s, avec garde-fou anti-misread :
    un petit déplacement (proche de la dernière position) est suivi tout de suite ;
    un saut énorme n'est cru qu'après COORD_ANCHOR_MIN lectures cohérentes d'affilée
    (vrai téléport / 1er ancrage) -> une valeur OCR aberrante isolée est ignorée."""
    sct = mss.MSS()
    mon = sct.monitors[1]
    w, h = mon["width"], mon["height"]
    last = None                                   # dernière position de confiance (nombres)
    run = []                                      # série de lectures cohérentes en attente d'ancrage

    def _near(a, b):
        return abs(a[0] - b[0]) <= COORD_STEP and abs(a[1] - b[1]) <= COORD_STEP

    while not _stop:
        try:
            frame = np.array(sct.grab(mon))[:, :, :3][:, :, ::-1]
            xs, ys = read_xy(frame, w, h)
            nx, ny = _signed(xs), _signed(ys)
            if nx is not None and ny is not None and abs(nx) <= COORD_MAX and abs(ny) <= COORD_MAX:
                p = (nx, ny)
                if last is not None and _near(p, last):
                    last, run = p, []             # déplacement plausible -> on suit direct
                    state["xy"] = (xs, ys)
                else:                             # saut suspect / pas encore d'ancre
                    run = run + [p] if (run and _near(p, run[-1])) else [p]
                    if len(run) >= COORD_ANCHOR_MIN:   # confirmé N fois -> vrai (téléport/ancre)
                        last, run = p, []
                        state["xy"] = (xs, ys)
        except Exception:
            pass
        time.sleep(0.6)


def save_debug(img, w, h, exclude_rects=()):
    from PIL import Image, ImageDraw
    names = _names(img, w, h, exclude_rects)
    tgt, n = detect(img, w, h, exclude_rects=exclude_rects)
    pim = Image.fromarray(img.astype(np.uint8))
    dr = ImageDraw.Draw(pim)
    dr.rectangle([MARGIN_LEFT, MARGIN_TOP, w - MARGIN_RIGHT, h - MARGIN_BOTTOM],
                 outline=(0, 120, 255), width=2)
    for (x, y) in names:                       # tous les noms détectés
        dr.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(0, 255, 0), width=2)
        dr.ellipse([x - 2, y + NAME_CLICK_DROP - 2, x + 2, y + NAME_CLICK_DROP + 2],
                   fill=(0, 255, 0))           # point de clic (sous le nom)
    if tgt:                                     # cible choisie = rouge
        x, y = tgt
        dr.ellipse([x - 13, y - 13, x + 13, y + 13], outline=(255, 0, 0), width=3)
    cx, cy = w // 2, h // 2                      # zone exclue (toi + pet) = magenta
    pg = _player_green(img, w, h)
    if pg:                                        # vert détecté = vert + croix
        gx, gy = pg
        dr.rectangle([gx + GREEN_DX0, gy + GREEN_DY0, gx + GREEN_DX1, gy + GREEN_DY1],
                     outline=(255, 0, 255), width=2)
        dr.line([gx - 8, gy, gx + 8, gy], fill=(0, 255, 0), width=2)
        dr.line([gx, gy - 8, gx, gy + 8], fill=(0, 255, 0), width=2)
    else:                                         # secours = zone centrée
        sx, sy = cx + SELF_DX, cy + SELF_DY
        dr.rectangle([sx - SELF_HALFW, sy - SELF_UP, sx + SELF_HALFW, sy + SELF_DOWN],
                     outline=(255, 0, 255), width=2)
    gc = _giant_gold(img, w, h)                 # zone + score détection Giant
    cx = w // 2
    dr.rectangle([cx + GIANT_X0, GIANT_Y0, cx + GIANT_X1, GIANT_Y1],
                 outline=(255, 215, 0), width=2)
    dr.text((cx + GIANT_X0, GIANT_Y1 + 3),
            f"gold={gc}  giant={gc >= GIANT_GOLD_MIN}", fill=(255, 215, 0))
    pim.save(os.path.join(BASE_DIR, "debug_mob.png"))


def toggle():
    state["running"] = not state["running"]
    winsound.Beep(880 if state["running"] else 350, 120)


def load_period():
    """Intervalle de sélection en ms (défaut = SELECT_PERIOD)."""
    try:
        with open(PERIOD_FILE, encoding="utf-8") as f:
            return max(200, int(f.read().strip()))
    except Exception:
        return int(SELECT_PERIOD * 1000)


def save_period(ms):
    try:
        with open(PERIOD_FILE, "w", encoding="utf-8") as f:
            f.write(str(int(ms)))
    except Exception:
        pass


def load_leash():
    try:
        with open(LEASH_FILE, encoding="utf-8") as f:
            return max(15, int(f.read().strip()))
    except Exception:
        return LEASH_RANGE


def save_leash(v):
    try:
        with open(LEASH_FILE, "w", encoding="utf-8") as f:
            f.write(str(int(v)))
    except Exception:
        pass


def load_return_on():
    try:
        with open(RETURN_ON_FILE, encoding="utf-8") as f:
            return f.read().strip() != "0"
    except Exception:
        return True


def save_return_on(on):
    try:
        with open(RETURN_ON_FILE, "w", encoding="utf-8") as f:
            f.write("1" if on else "0")
    except Exception:
        pass


def hotkey_loop():
    """Fast, dedicated F8/F7/F10 polling so a quick press is never missed."""
    global _stop
    sct = mss.MSS()
    mon = sct.monitors[1]
    w, h = mon["width"], mon["height"]
    pf8 = pf7 = False
    while not _stop:
        f8 = key_down(0x77)
        if f8 and not pf8:
            toggle()
        pf8 = f8
        f7 = key_down(0x76)
        if f7 and not pf7:
            try:
                shot = np.array(sct.grab(mon))[:, :, :3][:, :, ::-1]
                save_debug(shot, w, h, _win_exclude(mon))
                winsound.Beep(1200, 80)
            except Exception:
                pass
        pf7 = f7
        time.sleep(0.015)


def _signed(s):
    """'929' ou '-929' -> int ; sinon None."""
    body = s[1:] if s.startswith("-") else s
    return int(s) if body.isdigit() else None


def _xy_num():
    """Coords courantes (depuis la GUI) en nombres, ou None."""
    xs, ys = state.get("xy", ("--", "--"))
    nx, ny = _signed(xs), _signed(ys)
    return (nx, ny) if (nx is not None and ny is not None) else None


def _cur_xy(sct, mon, w, h):
    """Lecture FRAICHE des coords (grab + OCR), ou None."""
    try:
        f = np.array(sct.grab(mon))[:, :, :3][:, :, ::-1]
        xs, ys = read_xy(f, w, h)
        nx, ny = _signed(xs), _signed(ys)
        if nx is not None and ny is not None:
            return nx, ny
    except Exception:
        pass
    return None


# 8 directions ecran (normalisees), pour tester ou cliquer
_D = 0.7071
DIRS8 = [(0, -1), (_D, -_D), (1, 0), (_D, _D),
         (0, 1), (-_D, _D), (-1, 0), (-_D, -_D)]


def _click_toward(mon, w, h, dx, dy, frac):
    """Clic au sol dans la direction (dx,dy), a `frac` du chemin jusqu'au bord ecran
    (frac proche de 1 = clic loin = gros pas pour le perso)."""
    cx, cy = w // 2, h // 2
    m, top, big = 30, MARGIN_TOP + 20, 1e9
    tx = big if dx == 0 else (((w - m) if dx > 0 else m) - cx) / dx
    ty = big if dy == 0 else (((h - m) if dy > 0 else top) - cy) / dy
    t = max(0.0, min(tx, ty)) * frac
    click(mon["left"] + cx + int(dx * t), mon["top"] + cy + int(dy * t))


def _home_dist(pos):
    hx, hy = state["home"]
    return ((pos[0] - hx) ** 2 + (pos[1] - hy) ** 2) ** 0.5


def return_home(sct, mon, w, h):
    """Hill-climbing : clique loin dans une direction ; si ca rapproche on garde la
    direction, sinon on tourne. 'v' maintenu pour cacher les mobs (pas de clic-mob)."""
    state["returning"] = True
    vdown = False
    try:
        time.sleep(CAST_SETTLE)                       # laisse finir le sort en cours
        user32.keybd_event(VK_HIDE, 0, 0, 0)          # maintient 'v' -> cache les mobs
        vdown = True
        idx = state.get("ret_dir", 0)
        for _ in range(RETURN_STEPS):
            if _stop or not state["running"] or not state["home"]:
                return
            pos = _cur_xy(sct, mon, w, h)
            if not pos:
                return
            d = _home_dist(pos)
            if d <= LEASH_INNER:
                return                                # rentre
            frac = RETURN_FRAC if d > 35 else RETURN_FRAC_NEAR
            dx, dy = DIRS8[idx % 8]
            _click_toward(mon, w, h, dx, dy, frac)
            time.sleep(MOVE_SETTLE)
            npos = _cur_xy(sct, mon, w, h)
            if not npos:
                return
            if _home_dist(npos) < d - 2:              # ca rapproche -> on garde la direction
                state["ret_dir"] = idx % 8
            else:                                     # ca n'aide pas -> on tourne
                idx += 1
    finally:
        if vdown:
            user32.keybd_event(VK_HIDE, 0, 2, 0)      # relache 'v'
        state["returning"] = False


def action_loop():
    """Spell spam + mob selection while running. Checks the flag between keys."""
    sct = mss.MSS()
    mon = sct.monitors[1]
    w, h = mon["width"], mon["height"]
    last_select = 0.0
    giant_since = 0.0                             # depuis quand on est verrouillé sur un giant
    giant_seen = 0.0                              # dernière fois que l'icône de rang a été vue
    far_since = 0.0                               # depuis quand on est hors-range (0 = dedans)
    recent = []                                   # dernières positions cliquées
    while not _stop:
        if not state["running"]:
            state["home"] = None                  # re-ancre la maison au prochain Start
            state["giant"] = False                # libère le verrou giant
            far_since = 0.0
            time.sleep(0.04)
            continue
        try:
            # ancre la maison au demarrage, puis surveille la laisse (si activee)
            cur = _xy_num()
            if cur:
                if state["home"] is None:
                    state["home"] = cur
                elif state["leash_on"]:
                    hx, hy = state["home"]
                    far = (cur[0] - hx) ** 2 + (cur[1] - hy) ** 2 > state["leash"] ** 2
                    if not far:
                        far_since = 0.0
                    else:
                        if far_since == 0.0:
                            far_since = time.time()
                        if time.time() - far_since >= LEASH_CONFIRM_SEC:   # hors-range confirmé
                            far_since = 0.0
                            return_home(sct, mon, w, h)   # stoppe le spam et rentre
                            continue
            for vk in SPELL_KEYS:                 # spam des sorts
                if not state["running"]:
                    break
                press_key(vk)
                state["attacks"] += 1
                time.sleep(KEY_DELAY)
            if state["running"] and time.time() - last_select >= state["period"]:
                last_select = time.time()
                frame = np.array(sct.grab(mon))[:, :, :3][:, :, ::-1]
                # giant encore ta cible (icône de rang dorée présente = vivant) -> on garde
                if state.get("giant"):
                    if _giant_gold(frame, w, h) >= GIANT_GOLD_MIN:
                        giant_seen = time.time()
                    if (time.time() - giant_seen < GIANT_LOSE_GRACE
                            and time.time() - giant_since < GIANT_LOCK_MAX):
                        continue
                    state["giant"] = False              # giant mort/perdu -> on repart
                tgt, n = detect(frame, w, h, avoid=recent, exclude_rects=_win_exclude(mon))
                state["target"], state["blobs"] = tgt, n
                if tgt:
                    click(mon["left"] + tgt[0], mon["top"] + tgt[1] + NAME_CLICK_DROP)
                    state["selects"] += 1
                    recent.append(tgt)
                    recent[:] = recent[-RECENT_KEEP:]   # garde les 2 dernières
                    gc = 0                              # scrute le rang : la fenêtre de cible tarde parfois
                    for _ in range(GIANT_CONFIRM_TRIES):
                        time.sleep(0.1)
                        gc = _giant_gold(np.array(sct.grab(mon))[:, :, :3][:, :, ::-1], w, h)
                        if gc >= GIANT_GOLD_MIN:
                            break
                    state["gold"] = gc
                    if gc >= GIANT_GOLD_MIN:
                        press_key(BERSERK_KEY)          # berserk (Tab) sur les Giant
                        state["giant"] = True
                        giant_since = giant_seen = time.time()   # démarre le verrou sur ce giant
        except Exception:
            import traceback
            open(os.path.join(BASE_DIR, "mob_clicker_error.txt"), "w", encoding="utf-8").write(traceback.format_exc())


# ---- GUI -------------------------------------------------------------------
def main():
    root = tk.Tk()
    root.title("KrallBot")
    root.configure(bg=C_EDGE)
    root.attributes("-topmost", True)
    root.geometry("280x345+20+20")
    state["period"] = load_period() / 1000.0
    state["leash"] = load_leash()
    state["leash_on"] = load_return_on()

    # cadre or -> panneau bois (bordure dorée façon fenêtre SRO)
    panel = tk.Frame(root, bg=C_PANEL, highlightbackground=C_EDGE,
                     highlightthickness=2)
    panel.pack(fill="both", expand=True, padx=3, pady=3)

    tk.Label(panel, text="KrallBot (AMK)", bg=C_PANEL, fg=C_GOLD,
             font=("Trajan Pro", 13, "bold")).pack(pady=(10, 0))
    tk.Label(panel, text="fuck you Cockito", bg=C_PANEL, fg=C_GOLD_DIM,
             font=("Segoe UI", 9, "italic")).pack(pady=(0, 0))
    xy_lbl = tk.Label(panel, text="X: --   Y: --", bg=C_PANEL, fg=C_PARCH,
                      font=("Consolas", 10))
    xy_lbl.pack(pady=(0, 2))

    prow = tk.Frame(panel, bg=C_PANEL)
    prow.pack(pady=(4, 0))
    tk.Label(prow, text="select (ms)", bg=C_PANEL, fg=C_GOLD_DIM,
             font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
    ms_var = tk.StringVar(value=str(load_period()))
    ms_entry = tk.Entry(prow, textvariable=ms_var, justify="center", bg=C_BG,
                        fg=C_GOLD, insertbackground=C_GOLD, relief="flat", bd=2,
                        width=6, font=("Consolas", 10))
    ms_entry.pack(side="left")

    def apply_ms(*_):
        try:
            ms = max(200, int(ms_var.get()))
        except ValueError:
            return
        state["period"] = ms / 1000.0
        save_period(ms)
        ms_var.set(str(ms))
    ms_entry.bind("<FocusOut>", apply_ms)
    ms_entry.bind("<Return>", lambda e: (apply_ms(), panel.focus_set()))

    lrow = tk.Frame(panel, bg=C_PANEL)
    lrow.pack(pady=(4, 0))
    tk.Label(lrow, text="range", bg=C_PANEL, fg=C_GOLD_DIM,
             font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
    lz_var = tk.IntVar(value=load_leash())

    def apply_lz(v):
        state["leash"] = int(float(v))

    def save_lz(*_):
        save_leash(state["leash"])
    lz_scale = tk.Scale(lrow, from_=15, to=100, orient="horizontal",
                        variable=lz_var, command=apply_lz, length=180,
                        bg=C_PANEL, fg=C_GOLD, troughcolor=C_BG,
                        activebackground=C_GOLD, highlightthickness=0,
                        bd=0, sliderrelief="flat", font=("Consolas", 8))
    lz_scale.pack(side="left")
    lz_scale.bind("<ButtonRelease-1>", save_lz)

    gbrow = tk.Frame(panel, bg=C_PANEL)
    gbrow.pack(pady=(0, 0))
    gb_var = tk.BooleanVar(value=state["leash_on"])

    def apply_gb():
        state["leash_on"] = gb_var.get()
        save_return_on(gb_var.get())
    tk.Checkbutton(gbrow, text="go back", variable=gb_var, command=apply_gb,
                   bg=C_PANEL, fg=C_PARCH, selectcolor=C_BG, activebackground=C_PANEL,
                   activeforeground=C_PARCH, font=("Segoe UI", 9),
                   bd=0, highlightthickness=0).pack()

    tk.Frame(panel, bg=C_EDGE, height=1).pack(fill="x", padx=18, pady=(6, 6))
    st = tk.Label(panel, text="● STOPPED", bg=C_PANEL, fg=C_STOP,
                  font=("Segoe UI Semibold", 13))
    st.pack(pady=2)
    info = tk.Label(panel, text="", bg=C_PANEL, fg=C_PARCH,
                    font=("Consolas", 9), justify="left")
    info.pack(pady=2)
    btn = tk.Button(panel, text="START  (F8)", bg=C_EDGE, fg="#2c1d0c",
                    activebackground=C_GOLD, relief="flat", bd=0,
                    font=("Segoe UI Semibold", 10), command=toggle)
    btn.pack(pady=6, ipadx=6, ipady=2)

    threading.Thread(target=hotkey_loop, daemon=True).start()
    threading.Thread(target=action_loop, daemon=True).start()
    threading.Thread(target=coords_loop, daemon=True).start()

    def refresh():
        if _stop:
            root.destroy()
            return
        state["winrect"] = (root.winfo_rootx(), root.winfo_rooty(),
                            root.winfo_width(), root.winfo_height())
        on = state["running"]
        if state.get("returning"):
            st.config(text="↩ GOING BACK", fg=C_GOLD)
        else:
            st.config(text="● Fakiring" if on else "● STOPPED",
                      fg=C_RUN if on else C_STOP)
        btn.config(text="STOP  (F8)" if on else "START  (F8)",
                   bg=C_STOP if on else C_EDGE,
                   fg="#f0e6c8" if on else "#2c1d0c")
        xy = state.get("xy", ("--", "--"))
        xy_lbl.config(text=f"X: {xy[0]}   Y: {xy[1]}")
        cur, hm = _xy_num(), state.get("home")
        if cur and hm:
            hd = int(((cur[0] - hm[0]) ** 2 + (cur[1] - hm[1]) ** 2) ** 0.5)
            far = hd >= state["leash"]
            dist_txt = f"{hd} m" + ("  ⚠" if far else "")
        else:
            dist_txt = "--"
        info.config(text=f"distance from center : {dist_txt}"
                         f"{'  [GIANT]' if state.get('giant') else ''}")
        root.after(200, refresh)

    def on_close():
        global _stop
        _stop = True
        root.after(150, root.destroy)

    root.protocol("WM_DELETE_WINDOW", on_close)
    refresh()
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        open(os.path.join(BASE_DIR, "mob_clicker_error.txt"), "w", encoding="utf-8").write(traceback.format_exc())
        winsound.Beep(200, 600)
