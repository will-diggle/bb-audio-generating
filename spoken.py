"""Numbers written out the way a newsreader says them, in the text the voice reads.

Supertonic has no number reader: each digit reaches the model as a bare character and it guesses
("On 3 November" came out as "three November", and German and Swedish dates lost their ordinals;
Will, 7 Nov 2026). So every number in the voice's text is written out first: dates ("the third of
November", "am dritten November", "den tredje november"), years, money, percentages, decimals and
big numbers. Only the voice reads this text: the article on screen keeps its digits. A language not
listed here is read as written.

A number whose word follows the gender of its noun ("41 decisiones" is "cuarenta y una") takes the
word from the article's own number bracket, which the pipeline chose with spaCy. With no bracket
to go by, it's left for the voice, as before.

The date rules match the pipeline's bilinguist_dates.py, which writes the brackets.

    say("On 3rd November 2026, 123,450 people came.", "en")
    -> "On the third of November, twenty twenty-six, one hundred and twenty-three thousand four
       hundred and fifty people came."
"""
from __future__ import annotations

import re

from num2words import num2words

LANGS = ("en", "de", "fr", "es", "it", "pt", "sv")
_N2W = {"pt": "pt_BR"}  # the app teaches Brazilian Portuguese

MONTHS = {
    "en": "January February March April May June July August September October November December",
    "de": "Januar Februar März April Mai Juni Juli August September Oktober November Dezember",
    "fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
    "es": "enero febrero marzo abril mayo junio julio agosto septiembre setiembre octubre noviembre diciembre",
    "it": "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre",
    "pt": "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro",
    "sv": "januari februari mars april maj juni juli augusti september oktober november december",
}
# How a day is marked as an ordinal in writing: 3rd, 3., 1er, 1.º, 1°, 1º, 3:e
_MARK = {"en": r"(?:st|nd|rd|th)?", "de": r"\.?", "fr": r"(?:er)?", "es": r"(?:\.?º)?",
         "it": r"[°º]?", "pt": r"[º°]?", "sv": r"(?::[ae])?"}
# What joins the days of one date: 3-5 November, 3 and 4 November, vom 3. bis 5. November
_JOIN_WORDS = {"en": "to and or", "de": "bis und oder", "fr": "au et ou", "es": "al a y o",
               "it": "al a e o", "pt": "a e ou", "sv": "till och eller"}
_TO = {"en": "to", "de": "bis", "fr": "à", "es": "a", "it": "a", "pt": "a", "sv": "till"}
_POINT = {"en": "point", "de": "Komma", "fr": "virgule", "es": "coma", "it": "virgola", "pt": "vírgula",
          "sv": "komma"}
_PER_CENT = {"en": "per cent", "de": "Prozent", "fr": "pour cent", "es": "por ciento", "it": "per cento",
             "pt": "por cento", "sv": "procent"}
# Thousands and decimal separators as each language writes them: 123,450.5 / 123.450,5 / 123 450,5
_GROUP = {"en": ",", "de": r"\.", "fr": " ", "es": r"[. ]", "it": r"\.", "pt": r"\.", "sv": " "}
_DECIMAL = {"en": r"\."}
# Currency: (one, many), and for English the hundredth (one, many)
_MONEY = {
    "en": {"£": ("pound", "pounds", "penny", "pence"), "$": ("dollar", "dollars", "cent", "cents"),
           "€": ("euro", "euros", "cent", "cents")},
    "de": {"£": ("Pfund", "Pfund"), "$": ("Dollar", "Dollar"), "€": ("Euro", "Euro")},
    "fr": {"£": ("livre", "livres"), "$": ("dollar", "dollars"), "€": ("euro", "euros")},
    "es": {"£": ("libra", "libras"), "$": ("dólar", "dólares"), "€": ("euro", "euros")},
    "it": {"£": ("sterlina", "sterline"), "$": ("dollaro", "dollari"), "€": ("euro", "euro")},
    "pt": {"£": ("libra", "libras"), "$": ("dólar", "dólares"), "€": ("euro", "euros")},
    "sv": {"£": ("pund", "pund"), "$": ("dollar", "dollar"), "€": ("euro", "euro")},
}
# Words after a number that give its size, as written: "£5bn", "€3 Mrd.", "2 millions"
_SIZE = {
    "en": {"thousand": "thousand", "million": "million", "billion": "billion", "trillion": "trillion",
           "bn": "billion", "m": "million", "k": "thousand"},
    "de": {w: w for w in ("Million", "Millionen", "Milliarde", "Milliarden", "Billion", "Billionen")}
          | {"Mio.": "Millionen", "Mrd.": "Milliarden"},
    "fr": {w: w for w in ("million", "millions", "milliard", "milliards")},
    "es": {w: w for w in ("millón", "millones", "mil millones", "billón", "billones")},
    "it": {w: w for w in ("milione", "milioni", "miliardo", "miliardi")},
    "pt": {w: w for w in ("milhão", "milhões", "bilhão", "bilhões", "trilhão", "trilhões")},
    "sv": {w: w for w in ("miljon", "miljoner", "miljard", "miljarder")},
}
# "3 millions d'euros", "3 millones de euros", "3 milioni di euro"
_OF = {"fr": "de", "es": "de", "it": "di", "pt": "de"}
# A price's cents: "zwölf Euro fünfzig", "doce euros con cincuenta"
_AND_CENTS = {"de": "", "fr": "", "es": "con", "it": "e", "pt": "e", "sv": "och"}
_DEGREES = {"en": ("degree", "degrees"), "de": ("Grad", "Grad"), "fr": ("degré", "degrés"),
            "es": ("grado", "grados"), "it": ("grado", "gradi"), "pt": ("grau", "graus"), "sv": ("grad", "grader")}
# The words for one before these: "eine Million", "un millón", "en procent"
_ONE = {
    "de": {"Million": "eine", "Milliarde": "eine", "Billion": "eine", "Prozent": "ein", "Euro": "ein",
           "Dollar": "ein", "Pfund": "ein", "Grad": "ein"},
    "es": {"millón": "un", "billón": "un", "euro": "un", "dólar": "un", "libra": "una", "grado": "un"},
    "it": {"milione": "un", "miliardo": "un", "euro": "un", "dollaro": "un", "sterlina": "una", "grado": "un"},
    "fr": {"livre": "une"},
    "pt": {"libra": "uma"},
    "sv": {"miljon": "en", "miljard": "en", "procent": "en", "euro": "en", "dollar": "en", "grad": "en"},
}
# Feminine currencies: "doscientas libras", "duas libras", "vingt et une livres"
_FEMININE = {"es": {"libra", "libras"}, "pt": {"libra", "libras"}, "fr": {"livre", "livres"},
             "it": {"sterlina", "sterline"}}

# German endings by the word before the date: "am dritten", "seit drittem", "der dritte", and
# "dritter" on its own ("Montag, 3. November")
_DE_EN = {"am", "vom", "zum", "beim", "im", "dem", "den", "des", "bis", "für", "gegen", "um", "durch"}
_DE_EM = {"seit", "ab", "nach", "vor", "von", "mit", "bei", "aus", "zwischen"}
_DE_E = {"der", "die", "das"}
_DE_DAYS = {"Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag", "Sonnabend"}

# Small words after a number that never decide its gender: "21 y 22", "1 de cada 3"
_NOT_NOUNS = set("de del da do das dos y e et ou o a al au à às en em por para con com sur su di och "
                 "eller till und oder bis".split())


def _words(value, lang: str, to: str = "cardinal") -> str:
    words = num2words(value, lang=_N2W.get(lang, lang), to=to).replace(",", "")
    return words.replace("etttusen", "ettusen") if lang == "sv" else words  # num2words' typo


def year(y: int, lang: str) -> str:
    if lang == "sv":  # num2words has no Swedish years: 1999 is "nittonhundranittionio"
        if 1100 <= y < 2000:
            return f"{_words(y // 100, lang)}hundra{_words(y % 100, lang) if y % 100 else ''}"
        return _words(y, lang)
    return _words(y, lang, "year")


def ordinal(n: int, lang: str, feminine: bool = False) -> str:
    words = _words(n, lang, "ordinal")
    if feminine:
        words = "première" if lang == "fr" and n == 1 else re.sub(r"o\b", "a", words)
    return words


def feminine(words: str, lang: str) -> str:
    """A number's words before a feminine noun (the pipeline's numwords.agree does the same)."""
    if lang == "es":
        return re.sub(r"(veinti)?uno$", lambda m: (m[1] or "") + "una", re.sub(r"ientos\b", "ientas", words))
    if lang == "pt":
        return re.sub(r"entos\b", "entas", re.sub(r"\bum\b", "uma", re.sub(r"\bdois\b", "duas", words)))
    if lang == "fr":
        return re.sub(r"\bun$", "une", words)
    if lang == "it":
        return re.sub(r"^uno$", "una", words)
    return words


def counted(words: str, value: int, nxt: str, lang: str) -> str:
    """A number's words before a word it counts that this module knows: "eine Million", "veintiún
    millones", "duas libras"."""
    if value == 1 and nxt in _ONE.get(lang, {}):
        return _ONE[lang][nxt]
    if nxt in _FEMININE.get(lang, ()):
        return feminine(words, lang)
    if lang == "es" and nxt in ("mil", "millón", "millones", "billón", "billones", "euros", "dólares"):
        return re.sub(r"veintiuno$", "veintiún", re.sub(r"\buno$", "un", words))
    return words


def _number(whole: str, frac: str | None, lang: str) -> str:
    """"123450" and "5": one hundred and twenty-three thousand four hundred and fifty point five.
    English and German read decimals digit by digit, the others as a number ("virgule douze")."""
    said = _words(int(whole), lang)
    if not frac:
        return said
    if lang in ("en", "de") or len(frac) > 2 or (len(frac) == 2 and frac[0] == "0"):
        tail = " ".join(_words(int(d), lang) for d in frac)
    else:
        tail = _words(int(frac), lang)
    return f"{said} {_POINT[lang]} {tail}"


def _num(lang: str) -> str:
    """A written number: its whole part, with any thousands separators, then any decimals."""
    point = _DECIMAL.get(lang, r",|\.(?=\d{1,2}(?!\d))" if "." in _GROUP[lang] else ",")
    return rf"(\d{{1,3}}(?:{_GROUP[lang]}\d{{3}})+(?!\d)|\d+)(?:(?:{point})(\d+))?"


def _digits(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def _months(lang: str) -> str:
    names = MONTHS[lang].split()
    return "|".join(names if lang in ("en", "de") else names + [m.capitalize() for m in names])


def _join(lang: str) -> str:
    return rf"\s*(?:-|,|\b(?:{'|'.join(_JOIN_WORDS[lang].split())})\b)\s*"


def german_ending(before: str) -> str:
    words = re.findall(r"\w+,?", before)[-3:]
    prev = words[-1] if words else ""
    if prev.rstrip(",") in _DE_DAYS:  # "am Montag, 3. November": the weekday's preposition
        prev = words[-2] if len(words) > 1 else ""
    if not prev or prev.endswith(","):
        return "r"
    prev = prev.lower()
    return "n" if prev in _DE_EN else "m" if prev in _DE_EM else "" if prev in _DE_E else "r"


def _dates(text: str, lang: str) -> str:
    day = rf"\d{{1,2}}{_MARK[lang]}"
    of = lang in ("es", "pt")
    the = r"(?:\b(?P<the>[Tt]he)\s+)?" if lang == "en" else ""
    yr = r",?\s+" if lang == "en" else r"\s+de\s+" if of else r"\s+"
    pattern = re.compile(rf"{the}(?<![\w.,£$€-])(?P<days>{day}(?:{_join(lang)}{day})*)" + (r"\s+de" if of else "")
                         + rf"\s+(?P<month>{_months(lang)})\b(?:{yr}(?P<year>\d{{4}}))?(?!\d)")

    def said(m: re.Match) -> str:
        parts = re.split(f"({_join(lang)})", m["days"])
        values = [int(re.match(r"\d+", d)[0]) for d in parts[0::2]]
        joins = [j.strip() for j in parts[1::2]]
        if not all(1 <= v <= 31 for v in values):
            return m[0]
        ending = german_ending(text[:m.start()]) if lang == "de" else ""

        def day_word(i: int) -> str:
            v = values[i]
            if lang == "en":
                the = (m["the"] or "the") if i == 0 else "the" if joins[i - 1] in ("-", "to") else ""
                return f"{the} {ordinal(v, lang)}".lstrip()
            if lang in ("de", "sv"):
                return ordinal(v, lang) + ending
            return ordinal(v, lang) if v == 1 and lang in ("fr", "it", "pt") else _words(v, lang)
        out = day_word(0)
        for i, j in enumerate(joins, 1):
            out += ", " if j == "," else f" {_TO[lang] if j == '-' else j} "
            out += day_word(i)
        out += (" of " if lang == "en" else " de " if of else " ") + m["month"]
        if m["year"]:
            out += (", " if lang == "en" else " de " if of else " ") + year(int(m["year"]), lang)
        return out

    text = pattern.sub(said, text)
    if lang == "en":  # November 3rd, 2026: "November the third, twenty twenty-six"
        text = re.sub(rf"\b({_months(lang)})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}})\b)?(?![\d,.]\d|:)",
                      lambda m: f"{m[1]} the {ordinal(int(m[2]), lang)}" + (f", {year(int(m[3]), lang)}" if m[3] else "")
                      if 1 <= int(m[2]) <= 31 else m[0], text)
    return text


def _gendered(text: str, lang: str, shown: str | None) -> str:
    """A number whose word depends on its noun's gender ("41 decisiones": "cuarenta y una") takes
    the word from its bracket in the article as shown, or stays as it is."""
    def depends(v: int) -> bool:
        units, tens = v % 10, v % 100
        if lang == "pt":
            return (units in (1, 2) and tens not in (11, 12)) or 200 <= v % 1000
        if lang == "es":
            return (units == 1 and tens != 11) or 200 <= v % 1000
        if lang == "fr":
            return units == 1 and tens != 11
        return tens == 1  # de, it, sv: "eine", "una", "en"
    if lang == "en":
        return text
    glosses = [] if lang == "de" else [(_digits(m[1]), m[2]) for m in re.finditer(r"(\d(?:[\d.,]|\s(?=\d{3}(?!\d)))*)\.?\s\(([^()\d]+)\)", shown or "")]
    words, k = {}, 0
    numbers = list(re.finditer(rf"(?<![\w.,]){_num(lang)}", text))
    for m in numbers:
        if k < len(glosses) and _digits(m[0]) == glosses[k][0]:
            words[m.start()] = glosses[k][1]
            k += 1
    sizes = {s.lower() for s in _SIZE[lang]} | {n.lower() for pair in _MONEY[lang].values() for n in pair}
    out, last = [], 0
    for m in numbers:
        after = re.match(r"\s([^\W\d]+)", text[m.end():])
        if m[2] or not after or not depends(int(_digits(m[1]))):
            continue
        nxt = after[1]
        if nxt.lower() in _NOT_NOUNS or nxt.lower() in sizes or re.fullmatch(_months(lang), nxt):
            continue
        out += [text[last:m.start()], words.get(m.start(), "\0" + m[0])]
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def _money(text: str, lang: str) -> str:
    names, sizes = _MONEY[lang], _SIZE[lang]
    size = "|".join(re.escape(s) for s in sorted(sizes, key=len, reverse=True))
    num = _num(lang)

    def said(sign: str, whole: str, frac: str | None, big: str | None, before: str) -> str:
        one, many = names[sign][:2]
        if lang == "en" and re.search(r"\b[Aa]n?\s$", before):   # "a £5bn deal", "a $10 fee"
            many = one
        if big:
            n = _number(_digits(whole), frac, lang)
            words = f"{counted(n, int(_digits(whole)), sizes[big], lang) if not frac else n} {sizes[big]}"
            if lang in _OF:
                return f"{words} d'{many}" if lang == "fr" and many[0] in "aeiou" else f"{words} {_OF[lang]} {many}"
            return f"{words} {many}"
        n = int(_digits(whole))
        if frac and lang == "en" and len(frac) == 2:
            cents = int(frac)
            small_one, small_many = names[sign][2:]
            main = f"{_words(n, lang)} {one if n == 1 else many}"
            return main + (f" and {_words(cents, lang)} {small_one if cents == 1 else small_many}" if cents else "")
        if frac and len(frac) == 2:
            cents = f" {_AND_CENTS[lang]} " if _AND_CENTS[lang] else " "
            return f"{counted(_words(n, lang), n, many, lang)} {many}" + (cents + _words(int(frac), lang) if int(frac) else "")
        if frac:
            return f"{_number(_digits(whole), frac, lang)} {many}"
        return f"{counted(_words(n, lang), n, one if n == 1 else many, lang)} {one if n == 1 else many}"

    text = re.sub(rf"([£$€])\s?{num}(?:\s?({size})(?!\w))?",
                  lambda m: said(m[1], m[2], m[3], m[4], m.string[:m.start()]), text)
    return re.sub(rf"(?<![\w.,]){num}\s?(?:({size})\s?)?([£$€])",
                  lambda m: said(m[4], m[1], m[2], m[3], m.string[:m.start()]), text)


def _degrees(text: str, lang: str) -> str:
    """25°C, 25 °C, -3°: "twenty-five degrees Celsius"."""
    def said(m: re.Match) -> str:
        n, unit = _digits(m[1]), _DEGREES[lang][0 if m[1] == "1" and not m[2] else 1]
        words = _number(n, m[2], lang) if m[2] else counted(_words(int(n), lang), int(n), unit, lang)
        return f"{words} {unit}" + {"C": " Celsius", "F": " Fahrenheit"}.get(m[3] or "", "")
    return re.sub(rf"(?<![\w.,]){_num(lang)}\s?°\s?([CF])?(?!\w)", said, text)


def _ordinals(text: str, lang: str) -> str:
    """Ordinals that aren't dates: 22nd, 2e, 2.º/2.ª, 1°, 2º/2ª, 2:a. Italian "°" is only an
    ordinal on 1 ("1° posto"): elsewhere it's degrees."""
    marks = {"en": r"(st|nd|rd|th)\b", "fr": r"(er|re|e|ème)\b", "es": r"\.?([ºª])", "it": r"([ºª])",
             "pt": r"([ºª])", "sv": r":([ae])\b"}
    if lang not in marks:
        return text
    text = re.sub(rf"(?<![\w.,])(\d+){marks[lang]}",
                  lambda m: ordinal(int(m[1]), lang, feminine=m[2] in ("ª", "re")), text)
    return re.sub(r"(?<![\w.,])1°(?=\s+[^\W\d])", ordinal(1, lang), text) if lang in ("it", "pt") else text


def _decades(text: str, lang: str) -> str:
    if lang == "en":  # the 1990s: "the nineteen nineties"
        return re.sub(r"(?<![\w.,])(\d{3}0)s\b", lambda m: re.sub(r"y$", "ie", year(int(m[1]), lang)) + "s", text)
    if lang == "de":  # die 1990er: "die neunzehnhundertneunziger"
        return re.sub(r"(?<![\w.,])(\d{3}0)er\b", lambda m: year(int(m[1]), lang) + "er", text)
    return text


def _times(text: str, lang: str) -> str:
    """German "10.30 Uhr", French "9 h 30", Portuguese "10h30", English "9pm" and "AD43", which the
    plain numbers below would read apart or leave alone."""
    if lang == "en":
        text = re.sub(r"(?<![\w.,])(\d{1,2})(?:[:.](\d{2}))?\s?(am|pm)\b",
                      lambda m: _words(int(m[1]), lang) + (f" {_number(m[2], None, lang) if m[2][0] != '0' else 'oh ' + _words(int(m[2]), lang)}"
                                                           if m[2] and int(m[2]) else "") + f" {m[3][0]}.m" + ("" if m.string[m.end():m.end() + 1] == "." else "."), text)
        return re.sub(r"\bAD\s?(\d{1,4})\b", lambda m: "AD " + (year(int(m[1]), lang) if len(m[1]) == 4 else _words(int(m[1]), lang)), text)
    if lang == "pt":
        return re.sub(r"(?<![\w.,])(\d{1,2})h(\d{2})?(?!\w)",
                      lambda m: feminine(_words(int(m[1]), lang), lang) + (" hora" if m[1] == "1" else " horas")
                      + (f" e {_words(int(m[2]), lang)}" if m[2] and int(m[2]) else ""), text)
    if lang == "de":
        return re.sub(r"(?<![\w.,])(\d{1,2})[.:](\d{2})\s?Uhr\b",
                      lambda m: f"{_words(int(m[1]), lang)} Uhr" + (f" {_words(int(m[2]), lang)}" if int(m[2]) else ""), text)
    if lang == "fr":
        return re.sub(r"(?<![\w.,])(\d{1,2})\s?h\s?(\d{2})?(?!\w)",
                      lambda m: feminine(_words(int(m[1]), lang), lang) + (" heure" if m[1] == "1" else " heures")
                      + (f" {_words(int(m[2]), lang)}" if m[2] and int(m[2]) else ""), text)
    return text


def _plain(text: str, lang: str) -> str:
    num = _num(lang)
    text = re.sub(rf"(?<![\w.,]){num}\s?%", lambda m: f"{_number(_digits(m[1]), m[2], lang)} {_PER_CENT[lang]}", text)
    # 53-47, 2020-2025: "fifty-three to forty-seven"
    text = re.sub(rf"(?<![\w.,-])({num})\s?-\s?(?=\d)", lambda m: f"{m[1]} {_TO[lang]} ", text)

    def said(m: re.Match) -> str:
        whole, frac = m[1], m[2]
        if not frac and whole.isdigit() and len(whole) == 4 and 1100 <= int(whole) <= 2099:
            return year(int(whole), lang)
        words = _number(_digits(whole), frac, lang)
        nxt = re.match(r"\s(\w+)", m.string[m.end():])
        return counted(words, int(_digits(whole)), nxt[1], lang) if nxt and not frac else words
    return re.sub(rf"(?<![\w.,\0]){num}(?!\w)", said, text)


_STEPS = (_dates, _money, _decades, _ordinals, _degrees, _times, _plain)


def say(text: str, lang: str, shown: str | None = None) -> str:
    """The text with every number written out, as the voice should read it. `shown` is the same
    text as the article shows it, with its number brackets. A step that fails leaves the text as
    it was: a number read as a digit is better than an article with no audio."""
    if lang not in LANGS or not re.search(r"\d", text):
        return text
    for step in (lambda t, lang: _gendered(t, lang, shown), *_STEPS):
        try:
            text = step(text, lang)
        except Exception:  # noqa: BLE001
            pass
    return text.replace("\0", "")
