"""Tests for spoken.py: numbers written out the way a newsreader says them.

    python3 test_spoken.py
"""
import unittest
from unittest import mock

import spoken as S


class Dates(unittest.TestCase):
    def test_english_says_the_third_of_november(self):
        self.assertEqual(S.say("On 3 November 2026.", "en"), "On the third of November, twenty twenty-six.")
        self.assertEqual(S.say("On 3rd November.", "en"), "On the third of November.")
        self.assertEqual(S.say("The 1st March deadline.", "en"), "The first of March deadline.")
        self.assertEqual(S.say("From 21st to 23rd October.", "en"), "From the twenty-first to the twenty-third of October.")
        self.assertEqual(S.say("From 3-5 November.", "en"), "From the third to the fifth of November.")
        self.assertEqual(S.say("On 3rd and 4th November.", "en"), "On the third and fourth of November.")
        self.assertEqual(S.say("November 3rd, 2026.", "en"), "November the third, twenty twenty-six.")

    def test_german_dates_take_their_ending_from_the_word_before(self):
        self.assertEqual(S.say("Am 3. November 2026.", "de"), "Am dritten November zweitausendsechsundzwanzig.")
        self.assertEqual(S.say("Vom 21. bis 23. Oktober.", "de"), "Vom einundzwanzigsten bis dreiundzwanzigsten Oktober.")
        self.assertEqual(S.say("Seit 2. November.", "de"), "Seit zweitem November.")
        self.assertEqual(S.say("Der 3. November war kalt.", "de"), "Der dritte November war kalt.")
        self.assertEqual(S.say("Montag, 3. November.", "de"), "Montag, dritter November.")
        self.assertEqual(S.say("Am Montag, 3. November.", "de"), "Am Montag, dritten November.")

    def test_swedish_says_tredje(self):
        self.assertEqual(S.say("Den 3 november 2026.", "sv"), "Den tredje november tvåtusentjugosex.")
        self.assertEqual(S.say("Den 21–23 oktober.".replace("–", "-"), "sv"), "Den tjugoförsta till tjugotredje oktober.")

    def test_french_italian_and_portuguese_say_only_the_first_as_an_ordinal(self):
        self.assertEqual(S.say("Le 1er novembre.", "fr"), "Le premier novembre.")
        self.assertEqual(S.say("Du 1er au 3 novembre.", "fr"), "Du premier au trois novembre.")
        self.assertEqual(S.say("Il 1° novembre.", "it"), "Il primo novembre.")
        self.assertEqual(S.say("Em 1º de novembro de 2026.", "pt"), "Em primeiro de novembro de dois mil e vinte e seis.")
        self.assertEqual(S.say("Em 3 de novembro.", "pt"), "Em três de novembro.")

    def test_spanish_says_uno_as_its_bracket_does(self):
        self.assertEqual(S.say("El 1 de noviembre.", "es"), "El uno de noviembre.")
        self.assertEqual(S.say("Del 21 al 23 de octubre.", "es"), "Del veintiuno al veintitrés de octubre.")

    def test_a_number_over_31_before_a_month_is_not_a_day(self):
        self.assertEqual(S.say("About 45 November voters.", "en"), "About forty-five November voters.")


class Numbers(unittest.TestCase):
    def test_big_numbers_in_each_language_s_own_writing(self):
        self.assertEqual(S.say("123,450 people", "en"), "one hundred and twenty-three thousand four hundred and fifty people")
        self.assertEqual(S.say("123.450 Menschen", "de"), "einhundertdreiundzwanzigtausendvierhundertfünfzig Menschen")
        self.assertEqual(S.say("123 450 personnes", "fr"), "cent vingt-trois mille quatre cent cinquante personnes")
        self.assertEqual(S.say("123 450 människor", "sv"), "etthundratjugotretusen fyrahundrafemtio människor")

    def test_a_year_is_said_as_a_year(self):
        self.assertEqual(S.say("In 1999 and 2026.", "en"), "In nineteen ninety-nine and twenty twenty-six.")
        self.assertEqual(S.say("År 1999.", "sv"), "År nittonhundranittionio.")
        self.assertEqual(S.say("In the 1990s.", "en"), "In the nineteen nineties.")
        self.assertEqual(S.say("In den 1990er Jahren.", "de"), "In den neunzehnhundertneunziger Jahren.")

    def test_decimals_and_percentages(self):
        self.assertEqual(S.say("Up 2.5%.", "en"), "Up two point five per cent.")
        self.assertEqual(S.say("Plus 2,5 %.", "de"), "Plus zwei Komma fünf Prozent.")
        self.assertEqual(S.say("Bei 2.775,90 Punkten.", "de"), "Bei zweitausendsiebenhundertfünfundsiebzig Komma neun null Punkten.")
        self.assertEqual(S.say("Subió un 2,5 %.", "es"), "Subió un dos coma cinco por ciento.")

    def test_money(self):
        self.assertEqual(S.say("It cost $88.12 and £4.50.", "en"),
                         "It cost eighty-eight dollars and twelve cents and four pounds and fifty pence.")
        self.assertEqual(S.say("A £5bn deal and £32,500.", "en"),
                         "A five billion pound deal and thirty-two thousand five hundred pounds.")
        self.assertEqual(S.say("$1.2 trillion", "en"), "one point two trillion dollars")
        self.assertEqual(S.say("1 Million Euro und 12,50 €", "de"), "eine Million Euro und zwölf Euro fünfzig")
        self.assertEqual(S.say("3 milliards €", "fr"), "trois milliards d'euros")
        self.assertEqual(S.say("21 millones de euros", "es"), "veintiún millones de euros")

    def test_ranges_ordinals_times_and_temperatures(self):
        self.assertEqual(S.say("They had 53-47.", "en"), "They had fifty-three to forty-seven.")
        self.assertEqual(S.say("California's 22nd district", "en"), "California's twenty-second district")
        self.assertEqual(S.say("Um 10.30 Uhr", "de"), "Um zehn Uhr dreißig")
        self.assertEqual(S.say("Il est 9 h 30.", "fr"), "Il est neuf heures trente.")
        self.assertEqual(S.say("It hit 25°C, then 1°C.", "en"), "It hit twenty-five degrees Celsius, then one degree Celsius.")
        self.assertEqual(S.say("Il 1° posto, 25° oggi.", "it"), "Il primo posto, venticinque gradi oggi.")

    def test_names_with_numbers_in_them_are_left_alone(self):
        self.assertEqual(S.say("The G7 met over COVID-19 and 5G.", "en"), "The G7 met over COVID-nineteen and 5G.")
        self.assertEqual(S.say("A Learjet 60 crashed.", "en"), "A Learjet sixty crashed.")


class Gender(unittest.TestCase):
    def test_a_number_takes_its_noun_s_gender_from_the_bracket(self):
        self.assertEqual(S.say("41 decisiones y 219 escaños", "es",
                               "41 (cuarenta y una) decisiones y 219 (doscientos diecinueve) escaños"),
                         "cuarenta y una decisiones y doscientos diecinueve escaños")
        self.assertEqual(S.say("219 cadeiras e 2 pessoas", "pt", "219 (duzentas e dezenove) cadeiras e 2 (duas) pessoas"),
                         "duzentas e dezenove cadeiras e duas pessoas")
        self.assertEqual(S.say("41 mesures", "fr", "41 (quarante et une) mesures"), "quarante et une mesures")

    def test_with_no_bracket_the_voice_keeps_the_digits(self):
        self.assertEqual(S.say("41 decisiones", "es"), "41 decisiones")
        self.assertEqual(S.say("Es kam 1 Frau.", "de", "Es kam 1 (eins) Frau."), "Es kam 1 Frau.")   # German never borrows

    def test_a_number_that_doesn_t_count_a_noun_needs_no_bracket(self):
        self.assertEqual(S.say("21 y 22 de octubre", "es"), "veintiuno y veintidós de octubre")
        self.assertEqual(S.say("3 votos", "pt"), "três votos")

    def test_the_writer_s_own_words_are_never_changed(self):
        self.assertEqual(S.say("Un livre coûte 12,50 €.", "fr"), "Un livre coûte douze euros cinquante.")


class Safety(unittest.TestCase):
    def test_text_with_no_numbers_or_an_unknown_language_is_untouched(self):
        self.assertEqual(S.say("No numbers here.", "en"), "No numbers here.")
        self.assertEqual(S.say("3 kasım", "tr"), "3 kasım")

    def test_a_step_that_fails_leaves_the_text_as_it_was(self):
        def boom(text, lang):
            raise ValueError("boom")
        with mock.patch.object(S, "_STEPS", (S._dates, boom, S._plain)):
            self.assertEqual(S.say("It cost £5 on 3 November.", "en"), "It cost £five on the third of November.")


if __name__ == "__main__":
    unittest.main()
