"""Language data for `teyla copy judge`: the words the code-side checks look for, per language.

This file holds Russian text because the checks must recognise it (like `lexicon.py`); it is listed in
`.leak-allow`. Nothing here is product copy. A list is a heuristic and says so: a verb that is missing
makes a button fail with a reason a person can read and override, never a silent pass.

    OOPS      an interjection that makes an error a joke (Apple: an error is not a joke)
    PLEASE    "please" (standard R11)
    WE        first person plural in an error (standard R12; Apple: the system did it, not a "we")
    YOUR      a possessive before a noun at the start of a label (standard R14)
    GENERIC   button labels that name no action (standard R10)
    VERBS     the first word of a button: a verb (Apple: a verb on every button)
"""
from __future__ import annotations

import re

LANGS = ("en", "es", "ru")

LOCALE = {"en": "English (United States)", "es": "Spanish as written in Spain (es-ES)", "ru": "Russian"}

OOPS = {
    "en": r"\b(?:oops|whoops|woops|whoopsie|uh[- ]?oh|oopsie)\b",
    "es": r"\b(?:ups|uy|ay)\b|\bvaya[,!.]",
    "ru": r"\b(?:упс|упсь|ой|ох|ай)\b",
}

PLEASE = {
    "en": r"\bplease\b",
    "es": r"\bpor favor\b|\bpor fa\b",
    "ru": r"\bпожалуйста\b|\bпожалуйст\w*",
}

WE = {
    "en": r"\bwe\b|\bwe['’](?:re|ve|ll|d)\b|\bour\b|\bus\b",
    "es": (r"\bnosotros\b|\bnosotras\b|\bnuestr[oa]s?\b|\bnos\b|"
           r"\b(?:pudimos|podemos|hemos|estamos|lamentamos|sentimos|encontramos|logramos|tuvimos|"
           r"guardamos|cargamos|recibimos|conseguimos|detectamos|intentamos)\b"),
    "ru": r"\bмы\b|\bнаш\w*|\bнам\b|\bнас\b",
}

YOUR = {
    "en": r"^your\b",
    "es": r"^(?:tu|tus|su|sus)\b",
    "ru": r"^(?:ваш|твой|твоя|твое|твоё|твои|твою|твоих)\w*",
}

GENERIC = {
    "en": {"ok", "okay", "submit", "click here", "yes", "no"},
    "es": {"ok", "vale", "enviar formulario", "haz clic aquí", "sí", "si", "no"},
    "ru": {"ок", "окей", "хорошо", "да", "нет", "нажмите здесь"},
}

_EN_VERBS = """
accept add allow answer apply archive ask attach begin block book bookmark browse buy call cancel capture change
check choose claim clean clear close collect compare complete confirm connect contact continue copy create decline
delete deny describe dictate disable discard dismiss do download drop duplicate edit enable end enroll enter erase
explore export filter find finish flag follow forget generate get give go grant hide hold ignore import install invite
join keep learn leave let link listen load lock log make manage mark merge move mute name note notify open order
pause pay pick pin plan play post press preview print publish pull push quit rate read rebuild record redo refresh
register reject reload remind remove rename reorder repeat replace reply report request reserve reset respond restore
resume retry return review revert rotate run save scan schedule scroll search see select sell send set share show
shuffle sign skip snooze sort speak split star start stop subscribe swap switch sync take talk tap tell try turn undo
unlock unmute update upgrade upload use verify view wait watch write
""".split()

_ES_IMPERATIVES = """
añade guarda crea abre cierra elige selecciona envía comparte empieza continúa continua cancela borra elimina edita
busca mira prueba activa desactiva vuelve reintenta inténtalo intenta toca pulsa descubre explora usa conecta
sincroniza acepta rechaza permite confirma descarga graba escucha habla reproduce pausa detén para sigue salta omite
ve entra inicia registra copia pega mueve renombra restaura deshaz rehaz actualiza comienza termina finaliza completa
marca desmarca comprueba revisa ordena filtra invita ayuda contacta llama reserva compra paga cambia ajusta configura
personaliza ignora olvida recuerda anota apunta carga cuenta dicta escribe lee muestra oculta publica quita suscríbete
""".split()

_RU_IMPERATIVES = """
добавь сохрани создай открой закрой выбери отправь поделись начни продолжи отмени удали измени найди посмотри
попробуй включи выключи вернись повтори нажми коснись скажи говори слушай запиши продолжай пропусти войди
зарегистрируйся скопируй вставь перемести переименуй восстанови обнови заверши отметь проверь настрой разреши
запрети подтверди скачай загрузи прочитай пригласи свяжись купи оплати оставь забудь запомни поставь смотри
выйди узнай покажи скрой очисти сбрось ответь подожди остановись давай продиктуй напиши прими откажись
""".split()

VERBS = {
    "en": set(_EN_VERBS),
    "es": set(_ES_IMPERATIVES),
    "ru": set(_RU_IMPERATIVES),
}

# An infinitive is the usual button form in Spanish and Russian ("Guardar", a Russian "Save" in the infinitive).
INFINITIVE = {
    "en": None,
    "es": re.compile(r"^\w{2,}(?:ar|er|ir|ár|ér|ír)(?:se|lo|la|le)?$"),
    "ru": re.compile(r"^\w{2,}(?:ть|ти|чь)(?:ся|сь)?$"),
}


def is_verb(word: str, lang: str) -> bool:
    w = word.lower().strip("¡¿")
    if w in VERBS.get(lang, ()):
        return True
    rx = INFINITIVE.get(lang)
    return bool(rx and rx.match(w))


# What `teyla voice chart` puts in the `banned` list of a new chart: the stock phrases the standard rules out.
BANNED_DEFAULT = {
    "en": ["oops", "whoops", "uh-oh", "something went wrong", "please wait"],
    "es": ["ups", "algo salió mal", "por favor espera"],
    "ru": ["упс", "что-то пошло не так", "пожалуйста, подождите"],
}

# Notes a new chart carries per language (English text: the chart's own sentences are the owner's to write).
LANGUAGE_NOTES = {
    "en": ["Differs in: contractions, humor, formality, spelling variant (US).",
           "Reference: plain-language guidance and ASD-STE100 for short sentences."],
    "es": ["Spain (es-ES), not Latin America: pick tu or usted once and keep it; opening marks kept.",
           "Reference: the RAE/ASALE Guia panhispanica de lenguaje claro."],
    "ru": ["Pick ty or vy once and keep it; facts first, no pressure; foreign terms only when the glossary has them.",
           "Reference: info-style and the Glavred checker for filler and stock phrases."],
}
