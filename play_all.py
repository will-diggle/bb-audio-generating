"""The spoken parts of Play all (Will, 3 Nov 2026), in the brief's language.

Each edition (language, level, length) gets an intro: the greeting, the day, a line introducing the
headlines, that edition's Global News headlines and the title "Global News", over news music that
fades out as the first article starts. Everything but the day and the headlines is read once and
saved. There is one for each time of day, and each has a version with no title, for a reader
whose brief doesn't start with Global News. Each language also gets one short title per topic,
played before that topic's articles. See "Play all" in the README for the files and how to use them.
"""
from __future__ import annotations

from datetime import datetime

TIMES = ("morning", "afternoon", "evening")

# Bump when these words or the music in R2 change, so every intro is made again
INTRO_VERSION = "2"

GREETINGS = {
    "en": ("Good morning", "Good afternoon", "Good evening"),
    "de": ("Guten Morgen", "Guten Tag", "Guten Abend"),
    "fr": ("Bonjour", "Bonjour", "Bonsoir"),
    "es": ("Buenos días", "Buenas tardes", "Buenas noches"),
    "it": ("Buongiorno", "Buon pomeriggio", "Buonasera"),
    "pt": ("Bom dia", "Boa tarde", "Boa noite"),
    "sv": ("God morgon", "God eftermiddag", "God kväll"),
}

# {weekday}, {day}, {month}. Days are written out, so each language's voice says them properly.
TODAY = {
    "en": "Today is {weekday} the {day} of {month}.",
    "de": "Heute ist {weekday}, der {day} {month}.",
    "fr": "Nous sommes le {weekday} {day} {month}.",
    "es": "Hoy es {weekday}, {day} de {month}.",
    "it": "Oggi è {weekday} {day} {month}.",
    "pt": "Hoje é {weekday}, {day} de {month}.",
    "sv": "Idag är det {weekday} den {day} {month}.",
}

HEADLINES = {
    "en": "Here are today's Bilinguist Brief headlines.",
    "de": "Hier sind die heutigen Schlagzeilen von Bilinguist Brief.",
    "fr": "Voici les titres du jour de Bilinguist Brief.",
    "es": "Estos son los titulares de hoy de Bilinguist Brief.",
    "it": "Ecco i titoli di oggi di Bilinguist Brief.",
    "pt": "Estas são as manchetes de hoje do Bilinguist Brief.",
    "sv": "Här är dagens rubriker från Bilinguist Brief.",
}

WEEKDAYS = {  # Monday first
    "en": "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split(),
    "de": "Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag".split(),
    "fr": "lundi mardi mercredi jeudi vendredi samedi dimanche".split(),
    "es": "lunes martes miércoles jueves viernes sábado domingo".split(),
    "it": "lunedì martedì mercoledì giovedì venerdì sabato domenica".split(),
    "pt": "segunda-feira terça-feira quarta-feira quinta-feira sexta-feira sábado domingo".split(),
    "sv": "måndag tisdag onsdag torsdag fredag lördag söndag".split(),
}

MONTHS = {
    "en": "January February March April May June July August September October November December".split(),
    "de": "Januar Februar März April Mai Juni Juli August September Oktober November Dezember".split(),
    "fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split(),
    "es": "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(),
    "it": "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split(),
    "pt": "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro".split(),
    "sv": "januari februari mars april maj juni juli augusti september oktober november december".split(),
}

DAYS = {  # the 1st to the 31st, as each sentence above says them
    "en": ("first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
           "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth twenty-first "
           "twenty-second twenty-third twenty-fourth twenty-fifth twenty-sixth twenty-seventh twenty-eighth "
           "twenty-ninth thirtieth thirty-first").split(),
    "de": ("erste zweite dritte vierte fünfte sechste siebte achte neunte zehnte elfte zwölfte dreizehnte "
           "vierzehnte fünfzehnte sechzehnte siebzehnte achtzehnte neunzehnte zwanzigste einundzwanzigste "
           "zweiundzwanzigste dreiundzwanzigste vierundzwanzigste fünfundzwanzigste sechsundzwanzigste "
           "siebenundzwanzigste achtundzwanzigste neunundzwanzigste dreißigste einunddreißigste").split(),
    "fr": ("premier deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize "
           "dix-sept dix-huit dix-neuf vingt vingt-et-un vingt-deux vingt-trois vingt-quatre vingt-cinq "
           "vingt-six vingt-sept vingt-huit vingt-neuf trente trente-et-un").split(),
    "es": ("uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciséis "
           "diecisiete dieciocho diecinueve veinte veintiuno veintidós veintitrés veinticuatro veinticinco "
           "veintiséis veintisiete veintiocho veintinueve treinta treinta_y_uno").split(),
    "it": ("primo due tre quattro cinque sei sette otto nove dieci undici dodici tredici quattordici quindici "
           "sedici diciassette diciotto diciannove venti ventuno ventidue ventitré ventiquattro venticinque "
           "ventisei ventisette ventotto ventinove trenta trentuno").split(),
    "pt": ("primeiro dois três quatro cinco seis sete oito nove dez onze doze treze catorze quinze dezesseis "
           "dezessete dezoito dezenove vinte vinte_e_um vinte_e_dois vinte_e_três vinte_e_quatro vinte_e_cinco "
           "vinte_e_seis vinte_e_sete vinte_e_oito vinte_e_nove trinta trinta_e_um").split(),
    "sv": ("första andra tredje fjärde femte sjätte sjunde åttonde nionde tionde elfte tolfte trettonde "
           "fjortonde femtonde sextonde sjuttonde artonde nittonde tjugonde tjugoförsta tjugoandra tjugotredje "
           "tjugofjärde tjugofemte tjugosjätte tjugosjunde tjugoåttonde tjugonionde trettionde "
           "trettioförsta").split(),
}

# The brief's genre -> the file's name and what's said. The words follow the app's section labels.
TOPICS = {"GLOBAL NEWS": "global-news", "UK": "uk", "EU": "eu", "US": "us", "BUSINESS & ECONOMY": "business"}
TITLES = {
    "en": {"GLOBAL NEWS": "Global News", "UK": "United Kingdom", "EU": "European Union", "US": "United States",
           "BUSINESS & ECONOMY": "Business and Economy"},
    "de": {"GLOBAL NEWS": "Weltnachrichten", "UK": "Großbritannien", "EU": "Europäische Union",
           "US": "Vereinigte Staaten", "BUSINESS & ECONOMY": "Wirtschaft"},
    "fr": {"GLOBAL NEWS": "Actualités mondiales", "UK": "Royaume-Uni", "EU": "Union européenne", "US": "États-Unis",
           "BUSINESS & ECONOMY": "Économie"},
    "es": {"GLOBAL NEWS": "Noticias mundiales", "UK": "Reino Unido", "EU": "Unión Europea", "US": "Estados Unidos",
           "BUSINESS & ECONOMY": "Economía"},
    "it": {"GLOBAL NEWS": "Notizie mondiali", "UK": "Regno Unito", "EU": "Unione Europea", "US": "Stati Uniti",
           "BUSINESS & ECONOMY": "Economia"},
    "pt": {"GLOBAL NEWS": "Notícias mundiais", "UK": "Reino Unido", "EU": "União Europeia", "US": "Estados Unidos",
           "BUSINESS & ECONOMY": "Economia"},
    "sv": {"GLOBAL NEWS": "Världsnyheter", "UK": "Storbritannien", "EU": "Europeiska unionen", "US": "USA",
           "BUSINESS & ECONOMY": "Ekonomi"},
}


def greeting_line(lang: str, time: str) -> str:
    return f"{GREETINGS[lang][TIMES.index(time)]}."


def day_line(lang: str, date: str) -> str:
    d = datetime.strptime(date, "%Y-%m-%d")
    return TODAY[lang].format(weekday=WEEKDAYS[lang][d.weekday()], day=DAYS[lang][d.day - 1].replace("_", " "),
                              month=MONTHS[lang][d.month - 1])


def saved_lines(lang: str) -> list[str]:
    """The lines every intro in a language shares, whatever the day (Will, 3 Nov 2026: read once
    and saved, not read again for each edition)."""
    return [greeting_line(lang, t) for t in TIMES] + [HEADLINES[lang], TITLES[lang]["GLOBAL NEWS"]]


def as_sentence(headline: str) -> str:
    headline = headline.strip()
    return headline if headline[-1:] in ".!?" else f"{headline}."
