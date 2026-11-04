"""Word lists for `teyla you` (you.py): language data the quote picker and the theme counter need, in English and
Russian. Listed under `cyrillic:` in .leak-allow. Lower case; a word is matched whole.
"""
from __future__ import annotations

# Verbs and phrases of intent: a line with these reads as a decision or a wish, not as a question or a log.
STRONG = frozenset("""
want need must never always stop start build ship fix kill cut keep make let decide choose create develop
launch publish simplify remove replace automate delegate focus prefer refuse insist
хочу нужно надо давай сделай делай запусти убери удали никогда всегда хватит начни закончи
выбери реши создай разработай опубликуй упрости замени автоматизируй делегируй важно главное
""".split())

# Topics of personal documents and money: a line about them is never a quote.
SENSITIVE = frozenset("""
passport visa tax taxes salary iban bank account contract insurance medical diagnosis doctor birth address
apartment rent mortgage loan debt invoice ssn license licence residence permit divorce wedding funeral
паспорт виза налог налоги зарплата банк счет счёт договор страховка диагноз врач адрес квартира аренда
ипотека кредит долг инн снилс вид жительство развод свадьба похороны
""".split())

# Street words: a number beside one of these is an address.
STREET = ("street", "st.", "avenue", "ave.", "road", "rd.", "lane", "boulevard", "blvd", "calle", "avenida", "strasse",
          "ул.", "улица", "пр-т", "проспект", "переулок", "кв.", "дом")

# Words that carry no theme, in addition to the stop lists `rules_lifecycle` already uses.
THEME_STOP = frozenset("""
about above after again also another because before being below between both could does doing during each every
first from have having here into just like make many more most much need only other over please same should
since some still such than that their them then there these they this those through under until using very want
well were what when where which while will with within without would your claude codex agent agents session
sessions prompt prompts thing things work works working
как так что это для или еще ещё все всё был была были было быть нам вам нас вас тут там когда чтобы потому
только очень можно нужно надо есть нет она они его ему при между после перед через также либо чем кто где
этот эта эти того этой этом которая которое свой мне меня тебе тебя мой наш себя себе сделай давай
""".split())
