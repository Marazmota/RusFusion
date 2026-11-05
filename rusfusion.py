# -*- coding: utf-8 -*-
"""
RusFusion — русификатор интерфейса Autodesk Fusion.

Как работает: Fusion хранит надписи интерфейса в XML-таблицах строк
(папки StringTable/<язык>). Русского языка там нет, поэтому скрипт
берёт английские надписи, переводит их на русский и записывает
вместо турецкого языка (tr-TR). Потом в настройках Fusion выбираешь
«Türkçe» — и интерфейс становится русским.

Запуск:  python rusfusion.py           — русифицировать
         python rusfusion.py --restore — вернуть как было

После обновления Fusion просто запусти ещё раз: уже переведённые
строки берутся из кэша, переводятся только новые.
"""
import os, sys, re, json, glob, time, shutil, zipfile, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glossary import GLOSSARY

TARGET = "tr-TR"          # какой язык заменяем русским
SOURCE = "en-US"
LOCAL = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
PROD = os.path.join(LOCAL, "Autodesk", "webdeploy", "production")
WORK = os.path.join(LOCAL, "RusFusion")
CACHE_FILE = os.path.join(WORK, "cache_ru.json")

os.makedirs(WORK, exist_ok=True)


def log(*a):
    print(*a, flush=True)


# ---------- поиск установки ----------
def find_fusion():
    exes = glob.glob(os.path.join(PROD, "*", "Fusion360.exe"))
    if not exes:
        sys.exit("Не нашёл Fusion в " + PROD)
    exes.sort(key=os.path.getmtime, reverse=True)
    return os.path.dirname(exes[0])


def lang_pairs(root):
    """Все папки tr-TR, рядом с которыми есть en-US."""
    for dirpath, dirnames, _ in os.walk(root):
        if TARGET in dirnames and SOURCE in dirnames:
            yield os.path.join(dirpath, SOURCE), os.path.join(dirpath, TARGET)


def is_string_table(path):
    if not path.lower().endswith(".xml"):
        return False
    try:
        with open(path, "rb") as f:
            head = f.read(4000)
        return b"<Resource" in head and b"devLabel" in head
    except OSError:
        return False


# ---------- защита служебных вставок ----------
TOKEN_RE = re.compile(
    r"(<[^<>]+>"            # html-теги
    r"|%\d+%|%\w+%|%[sdifu]|%\d"   # %1% %s %1
    r"|\{[^{}]*\}|\$\{[^{}]*\}"     # {0} ${x}
    r"|&[a-zA-Z]+;|&#\d+;"          # сущности
    r"|https?://\S+"                # ссылки
    r"|\n|\t)"
)


def protect(s):
    toks = []
    def sub(m):
        toks.append(m.group(0))
        return "XQ%dQX" % (len(toks) - 1)
    return TOKEN_RE.sub(sub, s), toks


def unprotect(s, toks):
    for i, t in enumerate(toks):
        new, n = re.subn(r"XQ\s*%d\s*QX" % i, lambda m, t=t: t, s, count=1)
        if n == 0:
            return None
        s = new
    if re.search(r"XQ\s*\d+\s*QX", s):
        return None
    return s


def needs_translation(s):
    if not s or not re.search(r"[A-Za-z]{2,}", s):
        return False
    return True


# ---------- переводчик ----------
URL = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ru&dt=t"


def gtranslate(text):
    data = urllib.parse.urlencode({"q": text}).encode()
    for attempt in range(6):
        try:
            req = urllib.request.Request(URL, data=data, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                js = json.loads(r.read().decode("utf-8"))
            return "".join(seg[0] for seg in js[0] if seg[0])
        except Exception as e:
            wait = 5 * (attempt + 1)
            log(f"  сеть: {e}; жду {wait} c")
            time.sleep(wait)
    return None


def fix_case(src, dst):
    lead = src[:len(src) - len(src.lstrip())]
    trail = src[len(src.rstrip()):]
    core_src, dst = src.strip(), dst.strip()
    if core_src[:1].isupper() and dst[:1].islower():
        dst = dst[:1].upper() + dst[1:]
    return lead + dst + trail


def gloss(src):
    """Словарь с учётом регистра: SOLID -> ТЕЛО, Solid -> Тело."""
    key = src.strip()
    if key in GLOSSARY:
        return GLOSSARY[key]
    if key.isupper():
        for k, v in GLOSSARY.items():
            if k.upper() == key:
                return v.upper()
    return None


def translate_one(src):
    if gloss(src):
        return gloss(src)
    p, toks = protect(src)
    out = gtranslate(p)
    if out is None:
        return None
    res = unprotect(out.strip(), toks)
    return fix_case(src, res) if res else src


def translate_batch(items):
    """items: список английских строк. Возвращает dict en->ru."""
    result = {}
    prot = [protect(s) for s in items]
    joined = "\n".join(p for p, _ in prot)
    out = gtranslate(joined)
    lines = out.split("\n") if out is not None else []
    if len(lines) == len(items):
        for src, (p, toks), line in zip(items, prot, lines):
            res = unprotect(line.strip(), toks)
            result[src] = fix_case(src, res) if res else None
    # что не вышло пачкой — по одной
    for src in items:
        if result.get(src) is None:
            r = translate_one(src)
            if r is not None:
                result[src] = r
    return result


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)


def translate_all(strings, cache):
    todo = [s for s in strings if s not in cache and needs_translation(s)]
    todo = [s for s in todo if not gloss(s)]
    log(f"Строк всего: {len(strings)}, нужно перевести: {len(todo)}")
    if not todo:
        return
    batches, cur, size = [], [], 0
    for s in todo:
        l = len(s) + 10
        if cur and (size + l > 3500 or len(cur) >= 60):
            batches.append(cur); cur, size = [], 0
        cur.append(s); size += l
    if cur:
        batches.append(cur)
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=4) as ex:
        for res in ex.map(translate_batch, batches):
            cache.update({k: v for k, v in res.items() if v is not None})
            done += 1
            if done % 10 == 0 or done == len(batches):
                save_cache(cache)
                el = time.time() - t0
                left = el / done * (len(batches) - done)
                log(f"  переведено пачек {done}/{len(batches)}, осталось ~{int(left // 60)} мин")


# ---------- запись ----------
def collect(path):
    root = ET.parse(path).getroot()
    return [l.get("devLabel") or "" for l in root.iter("label")]


def write_translated(src_path, dst_path, cache):
    tree = ET.parse(src_path)
    for l in tree.getroot().iter("label"):
        en = l.get("devLabel") or ""
        l.set("translation", (gloss(en) or cache.get(en, en)) if en else "")
    tree.write(dst_path, encoding="utf-8", xml_declaration=True)


def backup(root):
    name = os.path.basename(root)
    zpath = os.path.join(WORK, f"backup_{name}.zip")
    if os.path.exists(zpath):
        return
    log("Делаю резервную копию турецких файлов…")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for _, tgt in lang_pairs(root):
            for dp, _, fns in os.walk(tgt):
                for fn in fns:
                    full = os.path.join(dp, fn)
                    z.write(full, os.path.relpath(full, root))
    log("  копия:", zpath)


def restore(root):
    zpath = os.path.join(WORK, f"backup_{os.path.basename(root)}.zip")
    if not os.path.exists(zpath):
        sys.exit("Резервной копии для этой версии Fusion нет — восстанавливать нечего.")
    with zipfile.ZipFile(zpath) as z:
        z.extractall(root)
    log("Готово, турецкий язык восстановлен.")


def main():
    root = find_fusion()
    log("Fusion найден:", root)
    if "--restore" in sys.argv:
        restore(root)
        return

    pairs = list(lang_pairs(root))
    if not pairs:
        sys.exit("Не нашёл папок с языками.")
    backup(root)

    jobs = []   # (откуда брать английский, куда писать)
    copies = []
    for en_dir, tgt_dir in pairs:
        en_files = set(os.listdir(en_dir))
        for fn in en_files:
            src = os.path.join(en_dir, fn)
            if os.path.isdir(src):
                continue
            if is_string_table(src):
                jobs.append((src, os.path.join(tgt_dir, fn)))
            else:
                copies.append((src, os.path.join(tgt_dir, fn)))
        for fn in os.listdir(tgt_dir):
            p = os.path.join(tgt_dir, fn)
            if fn not in en_files and os.path.isfile(p) and is_string_table(p):
                jobs.append((p, p))   # своих английских нет — берём devLabel из него

    log(f"Таблиц строк: {len(jobs)}, прочих файлов: {len(copies)}")
    strings = set()
    for src, _ in jobs:
        try:
            strings.update(collect(src))
        except ET.ParseError as e:
            log("  пропускаю (битый XML):", src, e)
    strings.discard("")

    cache = load_cache()
    translate_all(sorted(strings), cache)
    save_cache(cache)

    log("Записываю файлы…")
    ok = 0
    for src, dst in jobs:
        try:
            write_translated(src, dst, cache)
            ok += 1
        except Exception as e:
            log("  ошибка:", dst, e)
    # остальное (например .qm) — английское, чтобы не вылезал турецкий
    for src, dst in copies:
        try:
            shutil.copyfile(src, dst)
        except Exception as e:
            log("  ошибка копирования:", dst, e)
    log(f"\nГотово! Переведено таблиц: {ok}.")
    log("Теперь в Fusion: Настройки (Preferences) → General → User Language → Türkçe,")
    log("затем перезапусти Fusion.")


if __name__ == "__main__":
    main()
