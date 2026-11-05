# -*- coding: utf-8 -*-
"""
RusFusion 2.0 — русификатор интерфейса Autodesk Fusion.

Перевод собирается из трёх источников (по убыванию приоритета):
  1. Ручной перевод сообщества RusFus — скачивается при установке из
     репозитория kiryxabykiryxaby/fusion360-russian-localization.
     Используется, только если английская строка не изменилась
     и служебные вставки (%1%, {name}) совпадают — иначе Fusion может упасть.
  0. Словарь RusFusion (glossary.py) — названия основных команд
     по общепринятой русской САПР-терминологии (важнее всех).
  3. Машинный перевод (Google) — только для строк, которых нет ни там, ни там
     (обычно это новые функции из свежих обновлений Fusion).

Перевод ставится в «родной» русский слот Fusion (StringTable/ru-RU),
язык выбирается в настройках: Preferences → General → User Language → Russian.

Запуск:  python rusfusion.py            — установить/обновить перевод
         python rusfusion.py --restore  — убрать перевод
         python rusfusion.py --auto     — тихий режим для автозапуска
"""
import os, sys, re, json, glob, time, shutil, zipfile, subprocess, io
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glossary import GLOSSARY

VERSION = "2.0"
LOCAL = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
PROD = os.path.join(LOCAL, "Autodesk", "webdeploy", "production")
WORK = os.path.join(LOCAL, "RusFusion")
CACHE_FILE = os.path.join(WORK, "cache_ru.json")
BASE_DIR = os.path.join(WORK, "rusfus")          # ручной перевод сообщества
BASE_ZIP_URL = ("https://codeload.github.com/kiryxabykiryxaby/"
                "fusion360-russian-localization/zip/refs/heads/main")
BASE_MAX_AGE = 7 * 24 * 3600                       # обновлять раз в неделю
MARKER = "rusfusion.json"                          # метка в ru-RU: что и когда ставили
AUTO = "--auto" in sys.argv

os.makedirs(WORK, exist_ok=True)

# ---------- оформление консоли ----------
os.system("")  # включает цвета в консоли Windows
C = {"g": "\033[92m", "y": "\033[93m", "r": "\033[91m", "c": "\033[96m", "b": "\033[1m", "0": "\033[0m"}


def log(msg="", color=None):
    if AUTO:
        with open(os.path.join(WORK, "auto.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M ") + re.sub(r"\033\[\d+m", "", msg) + "\n")
        return
    print((C[color] + msg + C["0"]) if color else msg, flush=True)


def fail(msg):
    log("ОШИБКА: " + msg, "r")
    if not AUTO:
        input("\nНажми Enter, чтобы закрыть…")
    sys.exit(1)


# ---------- поиск установки ----------
def find_fusion():
    """Активная сборка: сначала по FusionLauncher.exe.ini (так делает сам Autodesk)."""
    if not os.path.isdir(PROD):
        fail("Fusion не найден в " + PROD)
    inis = sorted(glob.glob(os.path.join(PROD, "*", "FusionLauncher.exe.ini")),
                  key=os.path.getmtime, reverse=True)
    for ini in inis:
        try:
            text = open(ini, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        m = re.search(r"production[\\/]([0-9a-fA-F]{20,})[\\/]Fusion360\.exe", text)
        if m:
            cand = os.path.join(PROD, m.group(1))
            if os.path.isfile(os.path.join(cand, "Fusion360.exe")):
                return cand
    exes = [e for e in glob.glob(os.path.join(PROD, "*", "Fusion360.exe"))
            if os.path.isdir(os.path.join(os.path.dirname(e), "StringTable"))]
    if not exes:
        fail("Не нашёл установленный Fusion. Запусти его один раз и попробуй снова.")
    exes.sort(key=os.path.getmtime, reverse=True)
    return os.path.dirname(exes[0])


def fusion_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Fusion360.exe"],
                             capture_output=True, text=True, errors="ignore").stdout
        return "Fusion360.exe" in out
    except Exception:
        return False


# ---------- ручной перевод сообщества ----------
def update_base():
    stamp = os.path.join(BASE_DIR, ".downloaded")
    fresh = os.path.exists(stamp) and time.time() - os.path.getmtime(stamp) < BASE_MAX_AGE
    if fresh and "--refresh" not in sys.argv:
        return True
    log("Скачиваю ручной перевод сообщества RusFus…", "c")
    try:
        req = urllib.request.Request(BASE_ZIP_URL, headers={"User-Agent": "RusFusion/" + VERSION})
        data = urllib.request.urlopen(req, timeout=120).read()
        z = zipfile.ZipFile(io.BytesIO(data))
        tmp = BASE_DIR + ".new"
        shutil.rmtree(tmp, ignore_errors=True)
        for info in z.infolist():
            parts = info.filename.split("/", 1)
            if len(parts) < 2 or not parts[1].startswith("files/") or info.is_dir():
                continue
            rel = parts[1][len("files/"):]
            if ".." in rel.split("/") or rel.startswith("/"):
                continue
            dst = os.path.join(tmp, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(z.read(info))
        if not os.path.isdir(os.path.join(tmp, "ru-RU")):
            raise RuntimeError("в архиве нет папки ru-RU")
        shutil.rmtree(BASE_DIR, ignore_errors=True)
        os.replace(tmp, BASE_DIR)
        open(stamp, "w").close()
        log("  готово", "g")
        return True
    except Exception as e:
        if os.path.isdir(os.path.join(BASE_DIR, "ru-RU")):
            log(f"  не удалось обновить ({e}), беру сохранённую копию", "y")
            return True
        log(f"  не удалось скачать ({e}) — будет только словарь и машинный перевод", "y")
        return False


# ---------- служебные вставки ----------
FMT_RE = re.compile(r"%\d+%|%%|%[a-zA-Z]|\{\w+\}|%")


def fmt_tokens(s):
    """Набор форматных вставок — должен совпадать с английским, иначе Fusion падает."""
    return sorted(set(FMT_RE.findall(s or "")))


TOKEN_RE = re.compile(
    r"(<[^<>]+>|%\d+%|%\w+%|%[sdifu]|%\d|\{[^{}]*\}|\$\{[^{}]*\}"
    r"|&[a-zA-Z]+;|&#\d+;|https?://\S+|\n|\t)"
)


def protect(s):
    toks = []
    def sub(m):
        toks.append(m.group(0))
        return "XQ%dQX" % (len(toks) - 1)
    return TOKEN_RE.sub(sub, s), toks


def unprotect(s, toks):
    for i, t in enumerate(toks):
        s, n = re.subn(r"XQ\s*%d\s*QX" % i, lambda m, t=t: t, s, count=1)
        if n == 0:
            return None
    if re.search(r"XQ\s*\d+\s*QX", s):
        return None
    return s


def needs_translation(s):
    return bool(s) and bool(re.search(r"[A-Za-z]{2,}", s))


def fix_case(src, dst):
    lead = src[:len(src) - len(src.lstrip())]
    trail = src[len(src.rstrip()):]
    dst = dst.strip()
    if src.strip()[:1].isupper() and dst[:1].islower():
        dst = dst[:1].upper() + dst[1:]
    return lead + dst + trail


def gloss(src):
    """Словарь с учётом регистра: SOLID -> ТЕЛО, Solid -> Тело."""
    key = src.strip()
    if key in GLOSSARY:
        return fix_case(src, GLOSSARY[key])
    if key.isupper():
        for k, v in GLOSSARY.items():
            if k.upper() == key:
                return fix_case(src, v.upper())
    return None


# ---------- машинный перевод ----------
GT_URL = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ru&dt=t"


def gtranslate(text):
    data = urllib.parse.urlencode({"q": text}).encode()
    for attempt in range(6):
        try:
            req = urllib.request.Request(GT_URL, data=data, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                js = json.loads(r.read().decode("utf-8"))
            return "".join(seg[0] for seg in js[0] if seg[0])
        except Exception as e:
            time.sleep(5 * (attempt + 1))
    return None


def translate_one(src):
    p, toks = protect(src)
    out = gtranslate(p)
    if out is None:
        return None
    res = unprotect(out.strip(), toks)
    return fix_case(src, res) if res else src


def translate_batch(items):
    result = {}
    prot = [protect(s) for s in items]
    out = gtranslate("\n".join(p for p, _ in prot))
    lines = out.split("\n") if out is not None else []
    if len(lines) == len(items):
        for src, (p, toks), line in zip(items, prot, lines):
            res = unprotect(line.strip(), toks)
            result[src] = fix_case(src, res) if res else None
    for src in items:
        if result.get(src) is None:
            r = translate_one(src)
            if r is not None:
                result[src] = r
    return result


def load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)


def machine_translate(todo, cache):
    todo = [s for s in todo if s not in cache]
    if not todo:
        return
    log(f"Машинный перевод новых строк: {len(todo)}", "c")
    batches, cur, size = [], [], 0
    for s in todo:
        if cur and (size + len(s) > 3500 or len(cur) >= 60):
            batches.append(cur); cur, size = [], 0
        cur.append(s); size += len(s) + 10
    if cur:
        batches.append(cur)
    t0, done = time.time(), 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for res in ex.map(translate_batch, batches):
            cache.update({k: v for k, v in res.items() if v is not None})
            done += 1
            if done % 10 == 0 or done == len(batches):
                save_cache(cache)
                left = (time.time() - t0) / done * (len(batches) - done)
                log(f"  {done}/{len(batches)} пачек, осталось ~{int(left // 60) + 1} мин")


# ---------- сборка перевода ----------
def read_labels(path):
    return ET.parse(path).getroot()


def build(root_dir, have_base):
    en_dir = os.path.join(root_dir, "StringTable", "en-US")
    ru_dir = os.path.join(root_dir, "StringTable", "ru-RU")
    base_ru = os.path.join(BASE_DIR, "ru-RU")
    if not os.path.isdir(en_dir):
        fail("Нет папки " + en_dir)

    files = sorted(f for f in os.listdir(en_dir) if f.lower().endswith(".xml"))

    # 1) ручной перевод: по ID строки и «память переводов» по тексту
    human_by_id, memory = {}, {}
    if have_base:
        for fn in os.listdir(base_ru):
            if not fn.lower().endswith(".xml"):
                continue
            try:
                for l in read_labels(os.path.join(base_ru, fn)).iter("label"):
                    dev, tr = l.get("devLabel") or "", l.get("translation") or ""
                    if dev and tr and fmt_tokens(dev) == fmt_tokens(tr):
                        human_by_id[(fn, l.get("commandName"))] = (dev, tr)
                        memory.setdefault(dev, tr)
            except ET.ParseError:
                pass

    trees, plan = {}, []
    stat = {"human": 0, "memory": 0, "gloss": 0, "machine": 0, "english": 0}
    need_mt = set()
    for fn in files:
        try:
            tree = ET.parse(os.path.join(en_dir, fn))
        except ET.ParseError:
            continue
        trees[fn] = tree
        for l in tree.getroot().iter("label"):
            en = l.get("devLabel") or ""
            if not en:
                continue
            h = human_by_id.get((fn, l.get("commandName")))
            if gloss(en):
                plan.append((l, "gloss", gloss(en)))
            elif h and h[0] == en:
                plan.append((l, "human", h[1]))
            elif en in memory:
                plan.append((l, "memory", memory[en]))
            elif needs_translation(en):
                plan.append((l, "machine", en)); need_mt.add(en)
            else:
                plan.append((l, "english", en))

    cache = load_cache()
    machine_translate(sorted(need_mt), cache)
    save_cache(cache)

    for l, kind, val in plan:
        en = l.get("devLabel")
        if kind == "machine":
            tr = cache.get(en)
            if not tr or fmt_tokens(tr) != fmt_tokens(en):
                tr, kind = en, "english"
        else:
            tr = val
        # финальная страховка от вылетов
        if fmt_tokens(tr) != fmt_tokens(en):
            tr, kind = en, "english"
        l.set("translation", tr)
        stat[kind] += 1

    tmp = ru_dir + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for fn, tree in trees.items():
        tree.write(os.path.join(tmp, fn), encoding="utf-8", xml_declaration=True)
    with open(os.path.join(tmp, MARKER), "w", encoding="utf-8") as f:
        json.dump({"version": VERSION, "date": time.strftime("%Y-%m-%d %H:%M"), **stat}, f)
    shutil.rmtree(ru_dir, ignore_errors=True)
    os.replace(tmp, ru_dir)
    return stat


def install_cam(root_dir):
    """Справка и строки CAM из перевода сообщества."""
    n = 0
    src_help = os.path.join(BASE_DIR, "ru-html")
    if os.path.isdir(src_help):
        dst = os.path.join(root_dir, "NeuCAM", "UI", "NeuCAMUI", "Resources", "Help", "ru-html")
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src_help, dst)
        n += 1
    src_cam = os.path.join(BASE_DIR, "russian_ru.xml")
    if os.path.isfile(src_cam):
        dst_dir = os.path.join(root_dir, "Applications", "CAM360", "Data", "Translations")
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copyfile(src_cam, os.path.join(dst_dir, "russian_ru.xml"))
        n += 1
    return n


def undo_turkish(root_dir):
    """RusFusion 1.x ставил перевод вместо турецкого — возвращаем турецкий на место."""
    z = os.path.join(WORK, f"backup_{os.path.basename(root_dir)}.zip")
    if os.path.exists(z):
        with zipfile.ZipFile(z) as zz:
            zz.extractall(root_dir)
        os.rename(z, z + ".restored")
        log("Вернул турецкий язык, который заменяла старая версия RusFusion.", "y")


def restore(root_dir):
    for p in [os.path.join(root_dir, "StringTable", "ru-RU"),
              os.path.join(root_dir, "NeuCAM", "UI", "NeuCAMUI", "Resources", "Help", "ru-html")]:
        shutil.rmtree(p, ignore_errors=True)
    cam = os.path.join(root_dir, "Applications", "CAM360", "Data", "Translations", "russian_ru.xml")
    if os.path.exists(cam):
        os.remove(cam)
    undo_turkish(root_dir)
    log("Перевод удалён. В настройках Fusion выбери English.", "g")


# ---------- автообновление ----------
STARTUP = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                       "Start Menu", "Programs", "Startup", "RusFusion.bat")


def autostart_enabled():
    return os.path.exists(STARTUP)


def enable_autostart():
    py = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(py):
        py = sys.executable
    with open(STARTUP, "w", encoding="cp866", errors="ignore") as f:
        f.write(f'@start "" "{py}" "{os.path.abspath(__file__)}" --auto\r\n')


def disable_autostart():
    if os.path.exists(STARTUP):
        os.remove(STARTUP)


def already_done(root_dir):
    return os.path.exists(os.path.join(root_dir, "StringTable", "ru-RU", MARKER))


# ---------- главное ----------
def main():
    if not AUTO:
        log(f"\n  RusFusion {VERSION} — русификатор Autodesk Fusion\n", "b")
    root = find_fusion()

    if "--restore" in sys.argv:
        if fusion_running():
            fail("Закрой Fusion и запусти ещё раз.")
        restore(root)
        disable_autostart()
        return

    if AUTO:
        if already_done(root) or fusion_running():
            return
        log("Найдено обновление Fusion — переустанавливаю перевод")

    log("Fusion: " + os.path.basename(root))
    if fusion_running():
        fail("Fusion запущен. Закрой его полностью и запусти ещё раз.")

    undo_turkish(root)
    have_base = update_base()
    stat = build(root, have_base)
    cam = install_cam(root) if have_base else 0

    total = sum(stat.values()) or 1
    pct = lambda k: f"{stat[k]} ({stat[k] * 100 // total}%)"
    log("\nГотово! Источники перевода:", "g")
    log(f"  ручной перевод RusFus:   {pct('human')}")
    log(f"  тот же текст в RusFus:   {pct('memory')}")
    log(f"  словарь RusFusion:       {pct('gloss')}")
    log(f"  машинный перевод:        {pct('machine')}")
    log(f"  осталось на английском:  {pct('english')}")
    if cam:
        log("  + справка и строки CAM")

    if AUTO:
        return
    if not autostart_enabled():
        ans = input("\nПроверять обновления Fusion при входе в Windows и сразу "
                    "переустанавливать перевод? (Д/н): ").strip().lower()
        if ans in ("", "д", "y", "да", "yes"):
            enable_autostart()
            log("Автообновление включено.", "g")
    log("\nТеперь в Fusion: Preferences (Ctrl+,) → General → User Language → Russian", "b")
    log("и подтверди перезапуск.\n")
    input("Нажми Enter, чтобы закрыть…")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except SystemExit:
        raise
    except Exception:
        import traceback
        log(traceback.format_exc(), "r")
        if not AUTO:
            input("\nНажми Enter, чтобы закрыть…")
