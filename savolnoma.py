"""
Yagona savolnoma yaratish.
Usage:
  python savolnoma.py --limit 1       # birinchi user bilan test
  python savolnoma.py                 # barchasi, confirm bilan
  python savolnoma.py --run-without   # confirm yo'q, successdan keyin 15s kutadi
  python savolnoma.py --dry-run       # ko'rish, create yo'q
"""
import sys, json, random, argparse, time, struct, base64
from datetime import datetime
from pathlib import Path

try:
    import requests, msgpack
except ImportError:
    print("pip install requests msgpack")
    sys.exit(1)


BASE_URL = "https://mahalla.ijro.uz/api"
COOKIE   = "route=b5853f2ca5e32178d1b95b3f63906e24|6893784451ec46a48e5aab668b34d4bc"

TOKEN        = None
REGION_ID    = None
DISTRICT_ID  = None
MAHALLA_ID   = None
DASHBOARD_URL    = None
DASHBOARD_SECRET = None


def _decode_jwt(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"TOKEN decode xatolik: {e}")
        sys.exit(1)


def init_token(token: str):
    global TOKEN, REGION_ID, DISTRICT_ID, MAHALLA_ID
    global CACHE_FILE, ADDED_USERS_FILE, FAILED_USERS_FILE
    TOKEN = token.strip()
    jwt = _decode_jwt(TOKEN)
    REGION_ID   = jwt["region_id"]
    DISTRICT_ID = jwt["district_id"]
    MAHALLA_ID  = jwt["mahalla_id"]
    # Har bir mahalla o'z fayllarida ishlaydi — shared fayl muammosi yo'q
    CACHE_FILE        = Path(f"citizens_cache_{MAHALLA_ID}.json")
    ADDED_USERS_FILE  = Path(f"added_users_{MAHALLA_ID}.json")
    FAILED_USERS_FILE = Path(f"failed_users_{MAHALLA_ID}.json")
    mahalla_name = jwt.get('mahalla_json', {}).get('name_uz', MAHALLA_ID)
    print(f"[TOKEN] {jwt.get('full_name')} | mahalla: {mahalla_name}")
    meta = {
        "mahalla_id":   MAHALLA_ID,
        "mahalla_name": mahalla_name,
        "worker_name":  jwt.get("full_name", ""),
        "district_id":  DISTRICT_ID,
        "region_id":    REGION_ID,
    }
    Path(f"mahalla_meta_{MAHALLA_ID}.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    push_to_dashboard("meta", meta)

# ── Barcha createlar uchun bir xil javoblar (15-23) ───────────────────────────
# MUHIM: extra_features_info va problems_info ARRAY (browser shunday yuboradi).
# Plain int yuborilsa server 400 MH000 qaytaradi.
# Kodlar frontend bundle (1651.*.js) enumlaridan aniqlangan.
FIXED = {
    "medical_examination_period": 2,    # 15. _1_YIL (1 yilgacha)
    "social_status":              6,    # 16. Yo'q
    "daftar_state":               5,    # 17. RESTERDA_TURMAYDI (reestrda turmaydi)
    "disability_status":          2,    # 18. YOQ
    "disability_group":        None,
    "residency_type":             1,    # 21. OZ_UYI (o'z uyida)
    "extra_features_info":      [10],   # 22. YOQ  (ARRAY, extraFeaturesInfos.YOQ=10)
    "problems_info":            [36],   # 23. YOQ  (ARRAY, problemInfos.YOQ=36)
}

CACHE_FILE        = None  # init_token() dan keyin set bo'ladi
ADDED_USERS_FILE  = None
FAILED_USERS_FILE = None
CREATE_RETRIES = 3
RETRY_DELAY_STEP_SECONDS = 10
RUN_WITHOUT_DELAY_SECONDS = (3, 6)  # (min, max) — har fuqaroda alohida random
CURRENT_YEAR = 2026

UZ_PHONE_PREFIXES = (
    "33",  # Humans
    "50",  # Ucell
    "55",  # Uzmobile
    "77",  # Humans
    "88",  # Mobiuz
    "90",  # Beeline
    "91",  # Beeline
    "93",  # Ucell
    "94",  # Ucell
    "95",  # Uzmobile
    "97",  # Mobiuz
    "98",  # Perfectum
    "99",  # Uzmobile
)

# memberInfos enum: 1=Ota-ona 2=Opa-singil 3=Farzandlar 4=Aka-uka
#                   5=Turmush o'rtoq 6=Boshqa 7=O'zi ishlaydi 8=Hech kim
MEMBERS_SELF     = [7]   # O'zi ishlaydi (18-57 yosh)
MEMBERS_PARENTS  = [1]   # Ota-ona ishlaydi (< 18 yosh)
MEMBERS_CHILDREN = [3]   # Farzandlar ishlaydi (> 58 yosh)

# Q20 — kasb-hunar ro'yxati (random tanlanadi)
PROFESSIONS = [
    "O'qituvchi", "Shifokor", "Hamshira", "Muhandis", "Dasturchi", "Hisobchi",
    "Iqtisodchi", "Huquqshunos", "Bank xodimi", "Sotuvchi", "Menejer",
    "Quruvchi", "Duradgor", "Payvandchi", "Elektrik", "Santexnik", "Bo'yoqchi",
    "Haydovchi", "Avtomexanik", "Tikuvchi", "Sartarosh", "Oshpaz", "Novvoy",
    "Qassob", "Dehqon", "Fermer", "Bog'bon", "Chorvador", "Asalarichi",
    "Baliqchi", "Politsiyachi", "Harbiy xizmatchi", "O't o'chiruvchi",
    "Kutubxonachi", "Jurnalist", "Tarjimon", "Dizayner", "Fotograf",
    "Rassom", "Musiqachi", "Aktyor", "Sport murabbiyi", "Farmatsevt",
    "Veterinar", "Stomatolog", "Psixolog", "Ijtimoiy xodim", "Tarbiyachi",
    "Logoped", "Laborant", "Geolog", "Arxitektor", "Topograf", "Agronom",
    "Texnolog", "Operator", "Dispetcher", "Kassir", "Ombor mudiri",
    "Ta'minotchi", "Marketolog", "Reklama mutaxassisi", "HR menejer",
    "Sotuv menejeri", "Loyiha menejeri", "Sifat nazoratchisi", "Auditor",
    "Notarius", "Sug'urta agenti", "Rieltor", "Turoperator", "Ekskursovod",
    "Styuardessa", "Temir yo'lchi", "Konchi", "Metallurg", "Kimyogar",
    "Fizik", "Matematik", "Biolog", "Ekolog", "Meteorolog", "Astronom",
    "Arxeolog", "Tarixchi", "Faylasuf", "Sotsiolog", "Pedagog", "Murabbiy",
    "Choyxonachi", "Qandolatchi", "Kavushdo'z", "Zargar", "Kulol",
    "To'quvchi", "Gilamdo'z", "Naqqosh", "Kashtachi", "Temirchi",
    "Mehnat faoliyati yo'q",
]

# specialty — oliy ma'lumotli bo'lganda kiritiladigan mutaxassislik (erkin matn)
SPECIALTIES = [
    "Pedagogika", "Tibbiyot", "Iqtisodiyot", "Huquqshunoslik", "Muhandislik",
    "Axborot texnologiyalari", "Filologiya", "Tarix", "Matematika", "Fizika",
    "Kimyo", "Biologiya", "Arxitektura", "Qurilish", "Energetika",
    "Agronomiya", "Veterinariya", "Jurnalistika", "Psixologiya", "Sotsiologiya",
    "Menejment", "Marketing", "Buxgalteriya hisobi", "Bank ishi", "Moliya",
    "Xalqaro munosabatlar", "Lingvistika", "San'atshunoslik", "Dizayn",
    "Ekologiya", "Geografiya", "Geologiya", "Mexanika", "Elektronika",
    "Telekommunikatsiya", "Transport", "Logistika", "Turizm", "Sport",
    "Farmatsevtika", "Stomatologiya", "Davlat boshqaruvi",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

import random

def generate_uz_phone() -> str:
    prefix = random.choice(UZ_PHONE_PREFIXES)
    number = random.randint(0, 9999999)

    return f"{prefix}{number:07d}"


def normalize_phone(phone):
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(digits) == 12 and digits.startswith("998"):
        digits = digits[3:]
    if len(digits) != 9:
        return None
    if digits == "000000000":
        return None
    if digits[:2] not in UZ_PHONE_PREFIXES:
        return None
    return digits


def resolve_phone(citizen, fm):
    candidates = []
    if isinstance(fm, dict):
        candidates.append(fm.get("phone_number"))
    if isinstance(citizen, dict):
        candidates.append(citizen.get("phone_number"))
    for candidate in candidates:
        phone = normalize_phone(candidate)
        if phone:
            return phone
    return generate_uz_phone()

def parse_birth_year(birth_date):
    if birth_date is None:
        return None
    # ExtType(code=13): nested msgpack float milliseconds
    if isinstance(birth_date, msgpack.ext.ExtType):
        try:
            val = msgpack.unpackb(birth_date.data, raw=False)
            if isinstance(val, (int, float)):
                ts = val / 1000 if abs(val) > 1e10 else val
                return datetime.fromtimestamp(ts).year
        except Exception:
            pass
    # String: "DD.MM.YYYY" or "YYYY-MM-DD"
    if isinstance(birth_date, str):
        try:
            if '.' in birth_date:
                return int(birth_date.rsplit('.', 1)[-1])
            return int(birth_date[:4])
        except Exception:
            pass
    return None


def get_age(birth_year):
    if not birth_year:
        return None
    try:
        age = CURRENT_YEAR - int(birth_year)
    except (TypeError, ValueError):
        return None
    return age if age >= 0 else None


def normalize_citizen(c):
    """ExtType birth_date'ni JSON-safe birth_year int'ga aylantiradi (cache uchun)."""
    if isinstance(c, dict) and "birth_year" not in c:
        c["birth_year"] = parse_birth_year(c.get("birth_date"))
        c.pop("birth_date", None)  # ExtType JSON'ga sig'maydi
    return c


def education_from_age(age):
    # eduTypes: 1=O'rta 2=O'rta-maxsus 3=Oliy 4=Oliy-tugallanmagan 5=Ma'lumotsiz
    if age is None:
        return None
    if age < 18:
        return 1   # O'rta (tugallanmagan)
    if age < 26:
        return random.choice([2, 3])  # O'rta-maxsus yoki Oliy
    if age < 50:
        return random.choice([2, 2, 3])  # ko'pincha O'rta-maxsus, ba'zan Oliy
    return 1       # O'rta


def members_from_age(age):
    if age is None:
        return MEMBERS_SELF
    if age < 18:
        return MEMBERS_PARENTS   # ota-ona ishlaydi
    if age > 58:
        return MEMBERS_CHILDREN  # farzandlar ishlaydi
    return MEMBERS_SELF          # o'zi ishlaydi


def employment_from_age(age):
    # FmEmploymentStatusEnum: 1=Ta'limda rasmiy 2=Davlat rasmiy 3=Xususiy rasmiy
    #                         4=Norasmiy band 7=Pensiya
    if age is None:
        return 4
    if age < 18:
        return 1   # Ta'limda rasmiy band (o'quvchi)
    if age >= 58:
        return 7   # Pensiya (nafaqada)
    # Ishchi yosh: davlat/xususiy/norasmiy — norasmiy ko'proq uchraydi
    return random.choice([2, 3, 4, 4, 4])


def is_female(full_name):
    """Otasining ismi qo'shimchasidan jinsni aniqlaydi.
    Ayol: QIZI yoki ruscha ...VNA. Erkak: O‘G‘LI yoki ruscha ...VICH."""
    n = (full_name or "").upper().strip()
    if "QIZI" in n or n.endswith("VNA") or n.endswith("ВНА"):
        return True
    if ("O‘G‘LI" in n or "O'G'LI" in n or "OGLI" in n or "O`G`LI" in n
            or n.endswith("VICH") or n.endswith("ВИЧ")):
        return False
    return None  # noma'lum


def children_from_age(age, female):
    # childrenInfos: 1=Bor 2=Yo'q 3=Ona homilador
    if age is None or age < 18:
        return [2]  # Yo'q
    # Ona homilador: faqat ayol, 18-40 yosh, kichik ehtimol
    if female and 18 <= age <= 40 and random.random() < 0.08:
        return [3]
    if age < 23:
        p = 0.15
    elif age < 30:
        p = 0.55
    elif age < 50:
        p = 0.85
    else:
        p = 0.70
    return [1] if random.random() < p else [2]


def property_from_age(age):
    # propertyInfos: 1=Uy-joy 2=Yer 3=Transport 4=Boshqa 5=Mavjud emas
    # 20 yoshdan kichik -> mavjud emas. Aks holda max 2 ta tasodifiy.
    if age is None or age < 20:
        return [5]
    n = random.choice([1, 1, 2])  # ko'pincha 1 ta, ba'zan 2 ta
    chosen = set()
    if random.random() < 0.7:
        chosen.add(1)  # uy-joy keng tarqalgan
    while len(chosen) < n:
        chosen.add(random.choice([1, 2, 3, 4]))
    return sorted(chosen)


def specialty_for(edu_type):
    # Oliy (3) yoki oliy-tugallanmagan (4) bo'lsa mutaxassislik kiritiladi
    if edu_type in (3, 4):
        return random.choice(SPECIALTIES)
    return None


def push_to_dashboard(record_type, record):
    if not DASHBOARD_URL:
        return
    headers = {}
    if DASHBOARD_SECRET:
        headers["X-Secret"] = DASHBOARD_SECRET
    try:
        requests.post(
            f"{DASHBOARD_URL}/api/push",
            json={"type": record_type, "mahalla_id": MAHALLA_ID, "record": record},
            headers=headers,
            timeout=5,
        )
    except Exception:
        pass


def ask(msg, default=None):
    """Input with optional default."""
    hint = f" [{default}]" if default is not None else ""
    val = input(f"  {msg}{hint}: ").strip()
    return val if val else (str(default) if default is not None else "")


def read_json_list(path):
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def write_json_list(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def citizen_ids(data):
    if not isinstance(data, dict):
        return None, None
    citizen = data.get("citizen") if isinstance(data.get("citizen"), dict) else {}
    return (
        data.get("citizen_id") or citizen.get("citizen_id"),
        data.get("family_member_id") or citizen.get("family_member_id"),
    )


def build_added_index(records):
    index = {"citizen_ids": set(), "family_member_ids": set()}
    for record in records:
        citizen_id, family_member_id = citizen_ids(record)
        if citizen_id:
            index["citizen_ids"].add(citizen_id)
        if family_member_id:
            index["family_member_ids"].add(family_member_id)
    return index


def is_added_user(citizen, index):
    citizen_id, family_member_id = citizen_ids(citizen)
    return bool(
        (citizen_id and citizen_id in index["citizen_ids"])
        or (family_member_id and family_member_id in index["family_member_ids"])
    )


def same_citizen(left, right):
    left_citizen_id, left_family_member_id = citizen_ids(left)
    right_citizen_id, right_family_member_id = citizen_ids(right)
    return bool(
        (left_citizen_id and left_citizen_id == right_citizen_id)
        or (left_family_member_id and left_family_member_id == right_family_member_id)
    )


def remove_citizen_from_cache_file(cache_file, citizen):
    citizens = read_json_list(cache_file)
    if not citizens:
        return False
    remaining = [item for item in citizens if not same_citizen(item, citizen)]
    if len(remaining) == len(citizens):
        return False
    write_json_list(cache_file, remaining)
    return True


def remove_citizen_from_file(path, citizen):
    rows = read_json_list(path)
    if not rows:
        return False
    remaining = [item for item in rows if not same_citizen(item, citizen)]
    if len(remaining) == len(rows):
        return False
    write_json_list(path, remaining)
    return True


def append_user_record(path, citizen, status, payload=None, response=None, error=None, attempts=None):
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "name": citizen.get("full_name", "NOMA'LUM"),
        "citizen_id": citizen.get("citizen_id"),
        "family_member_id": citizen.get("family_member_id"),
        "status": status,
        "attempts": attempts,
        "citizen": citizen,
    }
    if payload is not None:
        record["payload"] = payload
    if response is not None:
        record["response"] = response
    if error is not None:
        record["error"] = error

    rows = read_json_list(path)
    rows.append(record)
    write_json_list(path, rows)
    push_type = "added" if path == ADDED_USERS_FILE else "failed"
    push_to_dashboard(push_type, record)
    return record


# ── API ───────────────────────────────────────────────────────────────────────

# Bitta Session: route cookie'ni server Set-Cookie orqali avtomatik yangilaydi.
_SESSION = None


def get_session():
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        s.headers.update({
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/octet-stream",
            "x-year": "2026",
            "Origin": "https://mahalla.ijro.uz",
            "Referer": (
                "https://mahalla.ijro.uz/family-member/survey/statistics"
                f"?district_id={DISTRICT_ID}&status=2"
                f"&region_id={REGION_ID}&mahalla_id={MAHALLA_ID}"
            ),
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36"
            ),
        })
        # Boshlang'ich route cookie (keyin server avtomatik yangilaydi)
        if "=" in COOKIE:
            name, _, value = COOKIE.partition("=")
            s.cookies.set(name.strip(), value.strip(), domain="mahalla.ijro.uz")
        _SESSION = s
    return _SESSION


def _decode(content):
    """msgpack javobni dekod qiladi (ExtraData bo'lsa ham birinchi obyektni oladi)."""
    if not content:
        return None
    try:
        return msgpack.unpackb(content, raw=False, strict_map_key=False)
    except msgpack.ExtraData as e:
        return e.unpacked
    except Exception:
        up = msgpack.Unpacker(raw=False, strict_map_key=False)
        up.feed(content)
        for obj in up:
            return obj
    return None


_HTTP_400 = object()  # 400 permanent error sentinel


def post(endpoint, payload, retries=3):
    url = f"{BASE_URL}/{endpoint}"
    body = msgpack.packb(payload, use_bin_type=True)
    sess = get_session()
    for attempt in range(1, retries + 1):
        try:
            r = sess.post(url, data=body, verify=True, timeout=30)
            if r.status_code in (200, 201):
                return _decode(r.content)
            err = _decode(r.content) or r.text[:200]
            print(f"    HTTP {r.status_code}: {err}")
            if r.status_code == 400:
                print(f"    400 raw: {r.content!r}")
                return _HTTP_400  # permanent — caller should not retry
            if r.status_code == 401:
                print("    401: TOKEN muddati tugagan bo'lishi mumkin. Yangi token kerak.")
                return None
            if attempt < retries:
                print(f"    Retry {attempt}/{retries-1}...")
                time.sleep(2 ** attempt)
        except requests.RequestException as e:
            print(f"    Network: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    return None


def is_real_success(result):
    if not result or result is _HTTP_400:
        return False
    if isinstance(result, dict):
        return result.get("success") is True
    return True


def create_with_retry(payload, ask_after_auto=True):
    attempts = 0
    while True:
        attempts += 1
        result = post("unified-questionnaire/create", payload, retries=1)
        if is_real_success(result):
            return result, attempts
        # HTTP 400 — payload xatolik, retry foyda yo'q
        if result is _HTTP_400:
            print("  HTTP 400: payload xatolik — retry foyda yo'q.")
            return None, attempts
        if attempts <= CREATE_RETRIES:
            delay = attempts * RETRY_DELAY_STEP_SECONDS
            print(f"  Create xatolik. Retry {attempts}/{CREATE_RETRIES}: {delay}s kutish...")
            time.sleep(delay)
            continue

        if not ask_after_auto:
            return None, attempts

        retry = input("  Yana retry qilinsinmi? (y/n): ").strip().lower()
        if retry != "y":
            return None, attempts

        delay = attempts * RETRY_DELAY_STEP_SECONDS
        print(f"  Qo'shimcha retry: {delay}s kutish...")
        time.sleep(delay)


# ── Payload builder ───────────────────────────────────────────────────────────

def build_payload(citizen, fm, integrations):
    fmid = citizen.get("family_member_id", "")

    # Birth year + age (cache'da birth_year, aks holda ExtType birth_date)
    birth_year = citizen.get("birth_year")
    if birth_year is None and isinstance(fm, dict):
        birth_year = parse_birth_year(fm.get("birth_date"))
    if birth_year is None:
        birth_year = parse_birth_year(citizen.get("birth_date"))
    age = get_age(birth_year)

    phone = resolve_phone(citizen, fm)

    female = is_female(citizen.get("full_name"))
    jins = "ayol" if female else ("erkak" if female is False else "?")
    print(f"\n  Tug'ilgan yil: {birth_year or '?'}  |  Yosh: {age or '?'}  |  Jins: {jins}")

    # --- 8. Ta'lim turi ---
    edu_resp = {}
    raw_edu = integrations.get("education")
    if isinstance(raw_edu, dict):
        edu_resp = raw_edu.get("response", raw_edu) or {}
    edu_type = edu_resp.get("education_type") if isinstance(edu_resp, dict) else None
    if edu_type is None:
        edu_type = education_from_age(age)
    if edu_type is None:
        edu_type = 2  # O'rta-maxsus (yosh noma'lum bo'lsa default)
    print(f"  8. education_type = {edu_type}")

    # --- 8.1. Mutaxassislik (oliy ma'lumotli bo'lsa) ---
    specialty = specialty_for(edu_type)
    if specialty:
        print(f"  8.1. specialty = {specialty}")

    # --- 14. Oilaviy holat (ZAGS dan) ---
    marriage_status = None
    raw_zags = integrations.get("zags")
    if isinstance(raw_zags, dict):
        zags_resp = raw_zags.get("response", raw_zags) or {}
        if isinstance(zags_resp, dict):
            marriage_status = zags_resp.get("marriage_status")
    if marriage_status is None:
        # Taxminiy: 22+ → turmush qurgan=1, aks holda=2
        marriage_status = 1 if (age and age >= 22) else 2
    print(f"  14. marriage_status = {marriage_status}")

    # --- 10.1. Oilada kimlar ishlaydi (yoshga qarab) ---
    members = members_from_age(age)
    print(f"  10.1. members_info = {members}")

    # --- 13. Bandlik holati ---
    emp_status = None
    raw_mehnat = integrations.get("mehnat")
    if isinstance(raw_mehnat, dict):
        meh_resp = raw_mehnat.get("response", raw_mehnat) or {}
        if isinstance(meh_resp, dict):
            emp_status = meh_resp.get("employment_status")
    if emp_status is None:
        emp_status = employment_from_age(age)
    print(f"  13. employment_status = {emp_status}")

    # --- 11. Mol-mulk (yoshga qarab, max 2 ta; <20 -> mavjud emas) ---
    property_info = property_from_age(age)
    print(f"  11. property_info = {property_info}")

    # --- 12. Qaramog'ida farzand (yosh + jinsga qarab random) ---
    children_info = children_from_age(age, female)
    print(f"  12. children_info = {children_info}")

    # --- 20. Kasb (100 ta ro'yxatdan random) ---
    profession = random.choice(PROFESSIONS)
    print(f"  20. profession = {profession}")

    # --- 10.2. Oila daromadi (5-20 mln random) ---
    family_income = random.randint(5_000_000, 20_000_000)
    print(f"  10.2. family_income = {family_income:,}")

    payload = {
        "family_member_id":     fmid,
        "education_type":       edu_type,
        "specialty":            specialty,
        "family_income":        family_income,
        "members_info":         members,
        "property_info":        property_info,    # 11.
        "children_info":        children_info,    # 12.
        "employment_status":    emp_status,
        "sub_employment_status": None,
        "phone_number":         phone,
        "marriage_status":      marriage_status,
        **FIXED,
        "profession":           profession,
        "execution_level":      None,
        "controller_user_id":   None,
        "deadline":             None,
    }
    return payload


# ── Dashboard / Cleanup helpers ───────────────────────────────────────────────

def fetch_dashboard_stats():
    """Dashboard'dan Ўрганиладиган (target) va Ўрганилган (surveyed) sonini oladi."""
    resp = post("unified-questionnaire/dashboard", {
        "region_id":   REGION_ID,
        "district_id": DISTRICT_ID,
        "mahalla_id":  MAHALLA_ID,
        "is_cache":    False,
    })
    if not resp:
        return None
    r = (resp.get("response") or {}) if isinstance(resp, dict) else {}
    if not isinstance(r, dict):
        return None
    def _to_int(v):
        """API goh str, goh int, goh None qaytaradi — xavfsiz int (xato bo'lsa 0)."""
        if isinstance(v, bool):
            return 0
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            v = v.strip()
            try:
                return int(float(v)) if v else 0
            except ValueError:
                return 0
        return 0

    target   = _to_int(r.get("total_18_or_above_age_family_member_count"))
    surveyed = _to_int(r.get("total"))
    pc = r.get("problems_count") or {}
    if not isinstance(pc, dict):
        pc = {}
    return {
        "target":        target,
        "surveyed":      surveyed,
        "unresearched":  target - surveyed,
        "has_problem":   _to_int(r.get("total_has_problem")),
        "no_problem":    _to_int(r.get("total_has_no_problem")),
        "accepted":      _to_int(pc.get("accepted")),
        "rejected":      _to_int(pc.get("rejected")),
        "not_completed": _to_int(pc.get("not_completed")),
        "pending":       _to_int(pc.get("pending")),
    }


def fetch_submitted_citizen_ids():
    """Serverda savolnomasi bor fuqarolarning citizen_id va family_member_id to'plamini qaytaradi."""
    index = {"citizen_ids": set(), "family_member_ids": set()}
    offset = 0
    page_limit = 200
    while True:
        resp = post("unified-questionnaire/list", {
            "region_id":   REGION_ID,
            "district_id": DISTRICT_ID,
            "mahalla_id":  MAHALLA_ID,
            "limit":       page_limit,
            "offset":      offset,
        })
        if not resp:
            break
        page = (resp.get("response") or {}).get("data", []) if isinstance(resp, dict) else []
        if not isinstance(page, list):
            break
        for item in page:
            cid  = item.get("citizen_id")
            fmid = item.get("family_member_id")
            if cid:
                index["citizen_ids"].add(cid)
            if fmid:
                index["family_member_ids"].add(fmid)
        if len(page) < page_limit:
            break
        offset += page_limit
    return index


def fetch_all_questionnaires():
    """Serverdan kiritilgan barcha savolnomalarni sahifalab oladi."""
    records = []
    offset = 0
    page_limit = 200
    while True:
        resp = post("unified-questionnaire/list", {
            "region_id":   REGION_ID,
            "district_id": DISTRICT_ID,
            "mahalla_id":  MAHALLA_ID,
            "limit":       page_limit,
            "offset":      offset,
        })
        if not resp:
            break
        page = (resp.get("response") or {}).get("data", []) if isinstance(resp, dict) else []
        if not isinstance(page, list):
            break
        records.extend(page)
        print(f"    offset={offset}: {len(page)} ta savolnoma")
        if len(page) < page_limit:
            break
        offset += page_limit
    return records


def _do_delete_extras(extras, to_delete, auto):
    """extras ro'yxatidan to_delete tani o'chiradi (3s oraliq)."""
    if not auto:
        yn = input(f"  {to_delete} ta o'chirilsinmi? (y/n): ").strip().lower()
        if yn != "y":
            print("  Bekor qilindi.")
            return
    deleted = errors = 0
    for name, rec in extras[:to_delete]:
        qid = rec.get("id")
        result = post("unified-questionnaire/delete", {"id": qid}, retries=1)
        if result and isinstance(result, dict) and result.get("success"):
            print(f"    O'chirildi: {name} (id={qid})")
            deleted += 1
        else:
            print(f"    XATOLIK: {name} (id={qid}): {result}")
            errors += 1
        time.sleep(3)
    print(f"\n  Natija: {deleted} ta o'chirildi, {errors} ta xatolik.")


def _collect_extras():
    """Serverdan barcha duplikatlarni yig'ib qaytaradi: (name, rec) ro'yxati."""
    from collections import defaultdict
    print("  Serverdan barcha savolnomalar yuklanmoqda...")
    records = fetch_all_questionnaires()
    if not records:
        print("  Savolnomalar topilmadi.")
        return [], {}
    by_citizen = defaultdict(list)
    for rec in records:
        cid = rec.get("citizen_id")
        qid = rec.get("id")
        if cid and qid:
            by_citizen[cid].append(rec)
    duplicates = {cid: recs for cid, recs in by_citizen.items() if len(recs) > 1}
    extras = []
    for cid, recs in duplicates.items():
        name = recs[0].get("full_name", cid)
        for rec in recs[1:]:
            extras.append((name, rec))
    return extras, duplicates


def cleanup_duplicates(auto=False):
    """Barcha takrorlangan savolnomalarni o'chiradi (limit yo'q)."""
    print("\n[CLEANUP] Barcha duplikatlar o'chiriladi...")
    extras, duplicates = _collect_extras()
    if not extras:
        print("  Takrorlanish yo'q." if duplicates is not None else "")
        return
    print(f"  {len(duplicates)} ta fuqaro, {len(extras)} ta ortiqcha:")
    for cid, recs in duplicates.items():
        name = recs[0].get("full_name", cid)
        print(f"    {name}: {len(recs)} ta → 1 ta qoladi")
    print(f"\n  O'chiriladigan: {len(extras)} ta")
    _do_delete_extras(extras, len(extras), auto)


def fix_overflow(auto=False):
    """Dashboard manfiy bo'lsa, aynan abs(unresearched) tani o'chiradi."""
    print("\n[FIX-OVERFLOW] Dashboard statistikasi olinmoqda...")
    dash = fetch_dashboard_stats()
    if not dash:
        print("  Dashboard olinmadi.")
        return
    target       = dash["target"]
    surveyed     = dash["surveyed"]
    unresearched = dash["unresearched"]
    print(f"  Ўрганиладиган: {target} | Ўрганилган: {surveyed} | Ўрганилмаган: {unresearched}")
    if unresearched >= 0:
        print(f"  Mahalla normal holatda — o'chirish kerak emas.")
        return
    must_delete = abs(unresearched)
    print(f"  {must_delete} ta o'chiriladi (manfiy sonni nolga keltirish uchun).")

    extras, duplicates = _collect_extras()
    if not extras:
        print("  Duplikat topilmadi — o'chirish imkoni yo'q.")
        return
    total_extra = len(extras)
    to_delete   = min(total_extra, must_delete)
    print(f"  Mavjud ortiqcha: {total_extra} ta | O'chiriladigan: {to_delete} ta")
    if must_delete > total_extra:
        print(f"  DIQQAT: {must_delete} ta kerak lekin faqat {total_extra} ta duplikat bor!")
    _do_delete_extras(extras, to_delete, auto)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", type=str, default=None,
                        help="Bearer JWT token")
    parser.add_argument("--limit", type=int, default=None,
                        help="Nechta fuqaro (default: barchasi)")
    parser.add_argument("--start", type=int, default=0,
                        help="Qaysi indexdan boshlash (default: 0). Parallel scriptlar uchun.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Payload ko'rsat, create yubormaslik")
    parser.add_argument("--refresh", action="store_true",
                        help="Cache'ni e'tiborsiz qoldirib qaytadan yuklab olish")
    parser.add_argument("--run-without", action="store_true",
                        help="Tasdiqsiz ishlatish, successdan keyin 15s kutish")
    parser.add_argument("--cleanup-duplicates", action="store_true",
                        help="Barcha takrorlangan savolnomalarni o'chirish")
    parser.add_argument("--fix-overflow", action="store_true",
                        help="Dashboard manfiy bo'lsa, aynan abs(unresearched) tani o'chirish")
    parser.add_argument("--auto-cleanup", action="store_true",
                        help="--cleanup-duplicates/--fix-overflow bilan: tasdiqlashsiz o'chirish")
    parser.add_argument("--statistics", action="store_true",
                        help="Dashboard statistikasini ko'rish (so'nggi yangilangan)")
    parser.add_argument("--count-underage", action="store_true",
                        help="API'dan fresh data tortib 18 yoshdan kichik fuqarolar sonini chiqarish")
    parser.add_argument("--dashboard", type=str, default=None,
                        help="Dashboard URL (masalan: http://192.168.1.5:5000)")
    parser.add_argument("--dashboard-secret", type=str, default=None,
                        help="Dashboard push uchun shared secret")
    args = parser.parse_args()

    global DASHBOARD_URL, DASHBOARD_SECRET
    if args.dashboard:
        DASHBOARD_URL = args.dashboard.rstrip("/")
    if args.dashboard_secret:
        DASHBOARD_SECRET = args.dashboard_secret
    if DASHBOARD_URL:
        print(f"[DASHBOARD] {DASHBOARD_URL}" + (" (himoyalangan)" if DASHBOARD_SECRET else " (ochiq)"))

    if args.token:
        init_token(args.token)
    else:
        print("Bearer token kiriting (paste qilib Enter bosing):")
        raw = sys.stdin.readline().strip()
        if not raw:
            print("Token bo'sh bo'lishi mumkin emas.")
            sys.exit(1)
        init_token(raw)

    cache_file = CACHE_FILE

    # 1. Cookie
    print("[1] Cookie olish...")
    post("regions/mahalla-list", {
        "district_id": DISTRICT_ID,
        "region_id": REGION_ID,
        "limit": 1,
    }, retries=1)

    # Statistics rejimi
    if args.statistics:
        dash = fetch_dashboard_stats()
        if not dash:
            print("  Dashboard ma'lumotlari olinmadi.")
            return
        t   = dash["target"]
        s   = dash["surveyed"]
        u   = dash["unresearched"]
        pct = round(s / t * 100, 1) if t > 0 else 0
        w   = 52
        print(f"\n{'='*w}")
        print(f"  Ўрганиладиган аҳоли:      {t}")
        print(f"  Ўрганилган аҳоли:         {s}")
        print(f"  Ўрганилмаган аҳоли:       {u}")
        print(f"  {'-'*(w-2)}")
        print(f"  Muammosi yo'q:            {dash['no_problem']}")
        print(f"  Muammosi bor:             {dash['has_problem']}")
        print(f"  {'-'*(w-2)}")
        print(f"  Savolnoma holatlari:")
        print(f"    Qabul qilingan:         {dash['accepted']}")
        print(f"    Rad etilgan:            {dash['rejected']}")
        print(f"    Tugallanmagan:          {dash['not_completed']}")
        print(f"    Kutilayotgan (pending): {dash['pending']}")
        print(f"  {'-'*(w-2)}")
        print(f"  Bajarilish:               {pct}%")
        print(f"{'='*w}")

        # ── O'tkazilgan (surveyed) ro'yxati: takroriy vs unique ──
        print("\n  O'tkazilganlar ro'yxati yuklanmoqda (takror tahlili)...")
        from collections import Counter
        records = fetch_all_questionnaires()
        cnt = Counter(rec.get("citizen_id") for rec in records if rec.get("citizen_id"))
        no_cid        = sum(1 for rec in records if not rec.get("citizen_id"))
        total_entries = sum(cnt.values()) + no_cid     # jami savolnoma yozuvi
        unique        = len(cnt)                        # noyob fuqaro
        dup_citizens  = sum(1 for c in cnt.values() if c > 1)   # >1 marta uchragan fuqaro
        dup_entries   = sum(c - 1 for c in cnt.values() if c > 1)  # ortiqcha (takror) yozuv

        print(f"\n{'='*w}")
        print(f"  O'TKAZILGAN (savolnoma yozuvlari)")
        print(f"  {'-'*(w-2)}")
        print(f"  Jami yozuv:               {total_entries}")
        print(f"  Noyob (unique) fuqaro:    {unique}")
        print(f"  Takroriy fuqaro (>1):     {dup_citizens}")
        print(f"  Ortiqcha takror yozuv:    {dup_entries}")
        if no_cid:
            print(f"  citizen_id yo'q yozuv:    {no_cid}")
        print(f"  {'-'*(w-2)}")
        print(f"  O'TKAZILMAGAN:            {u}")
        print(f"{'='*w}")
        if dup_citizens:
            print(f"\n  Eng ko'p takrorlangan (top 10):")
            for cid, c in cnt.most_common(10):
                if c > 1:
                    print(f"    {cid}: {c} marta")
        return

    # Cleanup/fix rejimi: barcha boshqa ishlardan avval
    if args.cleanup_duplicates:
        cleanup_duplicates(auto=args.auto_cleanup)
        return
    if args.fix_overflow:
        fix_overflow(auto=args.auto_cleanup)
        return

    # Count-underage rejimi: API'dan fresh data tortib 18 yoshdan kichiklar sonini chiqarish
    if args.count_underage:
        print("[COUNT-UNDERAGE] API'dan barcha fuqarolar yuklanmoqda (fresh)...")
        all_citizens = []
        offset = 0
        page_limit = 200
        while True:
            resp = post("unified-questionnaire/list", {
                "region_id":        REGION_ID,
                "district_id":      DISTRICT_ID,
                "mahalla_id":       MAHALLA_ID,
                "sorovnoma_holati": 2,
                "limit":            page_limit,
                "offset":           offset,
            })
            if not resp:
                print("  Xatolik: ro'yxat olinmadi")
                break
            page = resp.get("response", {}).get("data", [])
            all_citizens.extend(normalize_citizen(c) for c in page)
            print(f"  Offset {offset}: {len(page)} ta")
            if len(page) < page_limit:
                break
            offset += page_limit

        total = len(all_citizens)
        underage = []
        unknown_age = []
        for c in all_citizens:
            age = get_age(c.get("birth_year"))
            if age is None:
                unknown_age.append(c)
            elif age < 18:
                underage.append((c.get("full_name", "NOMA'LUM"), age, c.get("birth_year")))

        w = 52
        print(f"\n{'='*w}")
        print(f"  Jami o'tkazilmagan fuqarolar:  {total}")
        print(f"  18 yoshdan KICHIK:             {len(underage)}")
        print(f"  Yoshi noma'lum:                {len(unknown_age)}")
        print(f"  18 va undan katta:             {total - len(underage) - len(unknown_age)}")
        print(f"{'='*w}")
        if underage:
            print(f"\n  18 yoshdan kichiklar ro'yxati:")
            for name, age, by in sorted(underage, key=lambda x: x[1]):
                print(f"    {name:40s}  tug'ilgan: {by}  yosh: {age}")
        return

    unresearched = None

    # 3. O'tkazilmaganlar — cache bor bo'lsa o'qiymiz, aks holda API'dan
    if cache_file.exists() and not args.refresh:
        citizens = read_json_list(cache_file)
        print(f"[3] Cache'dan o'qildi: {len(citizens)} ta ({cache_file})")
    else:
        print("[3] O'tkazilmaganlar API'dan olinmoqda...")
        citizens = []
        offset = 0
        page_limit = 200
        while True:
            resp = post("unified-questionnaire/list", {
                "region_id":        REGION_ID,
                "district_id":      DISTRICT_ID,
                "mahalla_id":       MAHALLA_ID,
                "sorovnoma_holati": 2,
                "limit":            page_limit,
                "offset":           offset,
            })
            if not resp:
                print("  Xatolik: ro'yxat olinmadi")
                sys.exit(1)
            page = resp.get("response", {}).get("data", [])
            citizens.extend(normalize_citizen(c) for c in page)
            print(f"  Offset {offset}: {len(page)} ta")
            if len(page) < page_limit:
                break
            offset += page_limit
        write_json_list(cache_file, citizens)
        print(f"  Cache'ga saqlandi: {cache_file}")

    print(f"  JAMI: {len(citizens)} ta o'tkazilmagan")
    added_records = read_json_list(ADDED_USERS_FILE)
    added_index = build_added_index(added_records)
    print(f"  Qo'shilganlar fayli: {len(added_records)} ta ({ADDED_USERS_FILE})")

    # Server-side dedup: mahallada allaqachon savolnomasi bor citizen_idlarni yuklab added_index ga qo'shish
    print("  Server dedup tekshirilmoqda...")
    server_idx = fetch_submitted_citizen_ids()
    added_index["citizen_ids"].update(server_idx["citizen_ids"])
    added_index["family_member_ids"].update(server_idx["family_member_ids"])
    print(f"  Server: {len(server_idx['citizen_ids'])} ta fuqaro allaqachon kiritilgan")

    if args.start:
        citizens = citizens[args.start:]
        print(f"  --start={args.start}: {args.start}-indexdan boshlanadi")
    if args.limit:
        citizens = citizens[:args.limit]
        print(f"  --limit={args.limit}: {len(citizens)} ta bilan ishlash")
    if args.run_without:
        print("  --run-without: tasdiqsiz create, successdan keyin 15s kutish")

    # Dashboard cheklovi: o'rganilmagan sonidan oshmaslik
    if unresearched is not None:
        pending = [c for c in citizens if not is_added_user(c, added_index)]
        print(f"  Yangi (hali qo'shilmagan): {len(pending)} ta")
        if len(pending) > unresearched:
            print(f"\n  OGOHLANTIRISH: {len(pending)} ta yangi fuqaro bor,")
            print(f"  lekin dashboard bo'yicha faqat {unresearched} ta o'rganilmagan.")
            print(f"  Savolnoma {unresearched} ta bilan chegaralanadi.")
            citizens = pending[:unresearched]

    results = []
    created = errors = skipped = 0

    for i, citizen in enumerate(citizens):
        full_name = citizen.get("full_name", "NOMA'LUM")
        cid = citizen.get("citizen_id", "")
        fmid = citizen.get("family_member_id", "")

        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(citizens)}] {full_name}")
        print(f"  citizen_id: {cid}")
        print(f"  family_member_id: {fmid}")

        if is_added_user(citizen, added_index):
            print(f"  Oldin qo'shilgan, o'tkazildi: {full_name}")
            if remove_citizen_from_cache_file(cache_file, citizen):
                print(f"  Cache'dan olib tashlandi: {full_name}")
            skipped += 1
            results.append({
                "name": full_name,
                "citizen_id": cid,
                "family_member_id": fmid,
                "status": "already_added",
            })
            continue

        # 18 yoshdan kichiklar uchun savolnoma to'ldirilmaydi
        citizen_age = get_age(citizen.get("birth_year"))
        if citizen_age is not None and citizen_age < 18:
            print(f"  18 yoshdan kichik ({citizen_age} yosh) — o'tkazildi: {full_name}")
            skipped += 1
            results.append({
                "name": full_name,
                "citizen_id": cid,
                "family_member_id": fmid,
                "status": "skipped_underage",
            })
            continue

        # Family member details
        fm_raw = post("family-member/get-details", {"citizen_id": cid}) or {}
        fm = fm_raw.get("response", fm_raw) if isinstance(fm_raw, dict) else {}

        # Integrations (faqat keraklilari)
        print("  Integrations...")
        integrations = {}
        for name, endpoint, payload in [
            ("education", "integration/education-by-pinfl",
             {"citizen_id": cid}),
            ("zags", "integration/check-zags",
             {"citizen_id": cid, "should_refresh": False}),
            ("mehnat", "integration/mehnat-by-pinfl",
             {"citizen_id": cid, "should_refresh": False}),
        ]:
            r = post(endpoint, payload)
            integrations[name] = r or {}
            status = "ok" if r else "yo'q"
            print(f"    {name}: {status}")

        # Payload
        try:
            payload = build_payload(citizen, fm, integrations)
        except Exception as e:
            print(f"  Payload xatolik: {e}")
            errors += 1
            append_user_record(FAILED_USERS_FILE, citizen, "payload_error", error=str(e))
            results.append({"name": full_name, "status": "payload_error", "error": str(e)})
            continue

        print("\n  YAKUNIY PAYLOAD:")
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

        if args.dry_run:
            print("\n  [DRY-RUN] Create yo'q.")
            results.append({"name": full_name, "status": "dry-run", "payload": payload})
            continue

        if not args.run_without:
            confirm = input("\n  Yuborilsinmi? (y=ha / n=o'tkazib / q=to'xtatish): ").strip().lower()
            if confirm == 'q':
                print("  To'xtatildi.")
                break
            if confirm != 'y':
                skipped += 1
                results.append({"name": full_name, "status": "skipped"})
                continue

        print("  Yuborilmoqda...")
        result, attempts = create_with_retry(payload, ask_after_auto=not args.run_without)
        if result:
            print(f"  \033[42m\033[97m SAVOLNOMA YARATILDI: {full_name} \033[0m")
            created += 1
            append_user_record(
                ADDED_USERS_FILE,
                citizen,
                "ok",
                payload=payload,
                response=result,
                attempts=attempts,
            )
            added_index["citizen_ids"].add(cid)
            added_index["family_member_ids"].add(fmid)
            remove_citizen_from_file(FAILED_USERS_FILE, citizen)
            if remove_citizen_from_cache_file(cache_file, citizen):
                print(f"  Cache'dan olib tashlandi: {full_name}")
            results.append({
                "name": full_name,
                "citizen_id": cid,
                "family_member_id": fmid,
                "status": "ok",
                "attempts": attempts,
                "response": result,
            })
            if args.run_without:
                delay = random.randint(*RUN_WITHOUT_DELAY_SECONDS)
                print(f"  Keyingi userdan oldin {delay}s kutish...")
                time.sleep(delay)
            # Overshoot guard: dashboard unresearched sonidan oshib ketmaslik
            if unresearched is not None and unresearched > 0 and created >= unresearched:
                print(f"\n  LIMIT YETDI: {created}/{unresearched} ta to'ldirildi — to'xtatildi.")
                break
        else:
            print("  XATOLIK! Create muvaffaqiyatsiz.")
            errors += 1
            append_user_record(
                FAILED_USERS_FILE,
                citizen,
                "error",
                payload=payload,
                error="create_failed",
                attempts=attempts,
            )
            results.append({
                "name": full_name,
                "citizen_id": cid,
                "family_member_id": fmid,
                "status": "error",
                "attempts": attempts,
            })
            if args.run_without:
                delay = random.randint(*RUN_WITHOUT_DELAY_SECONDS)
                print(f"  Keyingi userdan oldin {delay}s kutish...")
                time.sleep(delay)

        if not args.run_without:
            time.sleep(0.5)

    # Saqlash
    out = Path(f"result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print(f"\n{'='*60}")
    print(f"YAKUNLANDI:")
    print(f"  Yaratildi: {created}")
    print(f"  Xatolik:   {errors}")
    print(f"  O'tkazildi: {skipped}")
    print(f"  Saqlandi:  {out}")
    print(f"  Qo'shilganlar: {ADDED_USERS_FILE}")
    print(f"  Failed: {FAILED_USERS_FILE}")


if __name__ == "__main__":
    main()
