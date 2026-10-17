"""Language data for the text detectors: English and Russian word lists and regex fragments.

Everything here is data a feature needs to recognise what a person typed, not documentation.
Russian is supported next to English because the people who use Teyla write to their agents in
both; each section below has an English part and a Russian part, and the modules that match
(`adapters`, `detect`, `rules_lifecycle`, `rules`) join them. To support another language, add a
section here and extend the joins; nothing else holds language data.

Regex fragments are alternatives for `|`-joining, to be compiled case-insensitively.
"""
from __future__ import annotations

# --- corrections: the human pushing back on work already produced --------------------------------
# A heuristic tuned for precision over recall: each branch needs either an unambiguous word
# ("wrong", "revert") or a shape that is pushback and not an instruction ("don't X at all" is a
# correction, "don't forget to deploy" is not).

CORRECTION_EN = (
    r"(?:^|[.!?;\n]\s*)(?:no|nope)\s*[,.!—–-]",                                    # "No, I mean…" as a reply
    r"\b(?:wrong|incorrect|not like (?:that|this)|not what i (?:asked|wanted|meant|said)|(?:don't|do not) do (?:that|this|it))\b",
    r"\b(?:revert|undo|roll ?back)\b",
    r"\bi (?:said|told you|already (?:said|told|asked)|meant|asked (?:you )?(?:to|for|not))\b",
    r"\bi (?:didn't|did not|haven't|have not|never) (?:ask|asked|say|said|want|wanted)\b",
    r"\bwhy (?:did|are|have|would|were) you\b",
    r"(?<!do )(?<!did )(?<!can )\byou (?:should have|shouldn't have|forgot|missed|broke|ignored|keep|kept|still|again|didn't|did not)\b",
    r"\byou (?:use|used|do|did|add|added|make|made|run|ran|spend|spent) (?:too|so) (?:much|many)\b",
    r"\b(?:don't|do not|stop|never)\b[^.!?\n]{0,60}\b(?:at all|anymore|any more|ever again)\b",
    r"(?:^|[.!?;\n]\s*)(?:stop|never) (?:using|doing|adding|creating|asking|use|do|add|create|ask|run|push|merge|touch|change)\b",
    r"\bi (?:don't|do not) like\b",
    r"\b(?:doesn't|don't|does not|do not|isn't|is not) work(?:ing)?\b|\b(?:still )?broken\b",
    r"\b(?:again|still)\b[^.!?\n]{0,20}(?:\bnot\b|n't\b|\bwrong\b|\bfail|\bbroken\b)",
)
CORRECTION_RU = (
    r"(?:^|[.!?;\n]\s*)нет\s*[,.!—–-]",
    r"не так\b|(?:это|совсем) не то\b|неправильно|неверно|ошибся|ошиблась|я же (?:говорил|сказал|просил|писал)",
    r"я (?:сказал|говорил|просил)|не надо|не нужно было|верни|откати|зачем ты|сделай сам",
    r"опять[^.!?\n]{0,40}(?:\bне\b|ничего|ошиб|слома)|ты (?:снова|опять)",
    r"ты не (?:заметил|сделал|понял|учёл|учел|прочитал|проверил|то)|(?<!не )\bзря\b|перестань",
)
CORRECTION_PATTERN = "|".join(CORRECTION_EN + CORRECTION_RU)

# --- retries: re-sending after an API error, not a correction and not a new turn -----------------
# "proceed", "go on" and "keep going" are left out on purpose: after a plan they are a decision.

RETRY_EN = ("try again", "retry", "try it again", "again", "continue")
RETRY_RU = ("продолжай", "продолжи", "ещё раз", "еще раз", "повтори", "попробуй (?:ещё|еще) раз")
RETRY_POLITE = ("please", "пожалуйста")
RETRY_PATTERN = (r"^(?:please[, ]+)?(?:" + "|".join(RETRY_EN + RETRY_RU) + r")(?:[\s,.!…]+(?:"
                 + "|".join(RETRY_POLITE) + r"))?[\s.!…]*$")
# A retry word that opens a longer turn ("Try again - the connector is back").
RETRY_HEAD_EN = ("try again", "retry", "again", "continue")
RETRY_HEAD_RU = ("ещё раз", "еще раз", "повтори")
RETRY_HEAD_PATTERN = r"^(?:please[, ]+)?(?:" + "|".join(RETRY_HEAD_EN + RETRY_HEAD_RU) + r")\b"

# --- permission asks: an agent asking leave to do the obvious next step (detect.py) --------------

PERMISSION_EN = (
    r"\b(?:do you )?want me to\b|\bwould you like me to\b|\b(?:shall|should) (?:i|we)\b",
    r"\b(?:ok|okay|ready) to (?:proceed|go|continue|start)\b|\blet me know if you(?:'d| would)? (?:like|want) me to\b",
    r"(?:^|[.!?]\s+|\n)\s*(?:proceed|go|apply|continue|ship it|go ahead)\?",
)
PERMISSION_RU = (
    r"\bхочешь\b|\bхотите\b|\bделать\?|\bделаем\?|\bпродолж(?:ить|аю|аем)\?|\bзапуска(?:ю|ем|ть)\?|\bприменить\?",
    r"\bмне (?:продолжить|сделать|начать|запустить)\b|\bсделать\?",
)
PERMISSION_PATTERN = "|".join(PERMISSION_EN + PERMISSION_RU)

# A real choice, not a nudge: alternatives, "which", a numbered or lettered menu.
CHOICE_EN = (r"\bor\b|\bwhich\b", r"(?:^|\n)\s*(?:\d+[.)]|\(?[a-c]\))\s")
CHOICE_RU = (r"\bили\b|\bкакой\b|\bкакую\b|\bкакое\b|\bчто (?:берём|выбираешь)\b",)
CHOICE_PATTERN = "|".join(CHOICE_EN + CHOICE_RU)

# Steps the policy reserves for the human: keys, payments, merges, deploys, deletes, downloads.
BLOCKER_EN = (
    r"api[ _-]?key|password|passphrase|token|credential|secret|sign[ -]?in|log[ -]?in|2fa|payment|pay\b|purchase|billing",
    r"\bmerge\b|\bproduction\b|\bprod\b|\bdeploy|\bdelete|\bremove|\bdrop\b|force[- ]push|\bdownload|\bpublish|\bsend\b|\bemail",
    r"CLAUDE\.md|POLICY\.md",
)
BLOCKER_RU = (r"ключ|пароль|оплат|удал|смерж|мерж|прод\b|деплой|задепло",)
BLOCKER_PATTERN = "|".join(BLOCKER_EN + BLOCKER_RU)

# The whole reply must be a yes: words from these lists and punctuation, nothing else.
AFFIRMATIVE_EN = ("yes yep yeah yup sure ok okay k proceed go ahead do it please agreed agree lgtm ship run "
                  "continue sounds good")
AFFIRMATIVE_RU = "да давай делай ок окей конечно ага продолжай согласен запускай го пожалуйста вперёд вперед"
AFFIRMATIVE_WORDS = frozenset((AFFIRMATIVE_EN + " " + AFFIRMATIVE_RU).split())
# Words that may pad a yes but do not make a reply one on their own.
FILLER_WORDS = frozenset("ahead it please good пожалуйста".split())

# --- rules: words a correction is phrased in, not what it is about (rules_lifecycle.py) ---------

STOPWORDS_RU = frozenset({
    "не", "нет", "это", "так", "как", "что", "надо", "нужно", "опять", "снова", "уже", "тоже",
    "для", "если", "или", "еще", "ещё", "все", "всё", "был", "была", "было", "нам", "тут"})

# Character classes for splitting text into words, Latin plus Cyrillic.
WORD_CHARS_LOWER = "a-zа-яё0-9"
WORD_CHARS = "a-zA-Zа-яА-Я0-9"

# --- intent cover: does a plan serve what the owner wrote (intent_cover.py) ---------------------
# Words that carry no meaning for matching a source sentence to a plan sentence.

COVER_STOP_EN = frozenset("""
the and for are but not you your all any can had her was one our out has have his how its may new now old
see two way who did get him she too use that this with from they will would there their what when where
which while about after again also because been before being both could does doing down each even ever
into just like make many more most much must need only other over same should some such than then them
these those through under until very want were here said say says still well within without
""".split())
COVER_STOP_RU = frozenset("""
это что как так для или еще ещё все всё был была были было быть нам вам нас вас тут там уже тоже если
когда чтобы потому только очень можно нужно надо есть нет она они его ему ней них при без над под про
между после перед через также либо чем кто где туда сюда этот эта эти того этой этом которые который
которая которое свой своих мне меня тебе тебя ему мой мои моих наш наши себя себе
""".split())

# Endings stripped from a Russian word, longest first, to compare "делать" with "делаю" and "плана" with "планы".
COVER_RU_SUFFIXES = tuple(sorted(set("""
ами ями ого его ому ему ыми ими ией ией ать ять ить еть оть уть ают яют ует уют ают ает яет
ают ишь ешь ете ите ала яла ила ела али яли или ели ает ует ает ется ится ются ятся
ами ях ах ов ев ей ою ею ую юю ая яя ое ее ые ие ых их ым им ом ем ой ый ий ые
ам ям ом ем ою ею ть ся сь ла ло ли на ны ну ты ты ть ет ут ют ит ат ят
а я у ю ы и е о ь й
""".split()), key=len, reverse=True))

# Abbreviations whose full stop does not end a sentence.
COVER_ABBREV = frozenset("""
e.g i.e etc vs approx incl no fig cf al
т.е т.д т.п т.к т.н напр см др пр г гг руб тыс млн шт англ проч
""".split())

# A sentence that opens with one of these and says nothing else is chatter, not a requirement.
COVER_CHATTER_LEAD = frozenset("""
ok okay yes yeah yep sure proceed continue thanks thank great nice good cool perfect fine go agreed right
да ок окей давай продолжай спасибо отлично хорошо круто поехали запускай делай согласен ладно супер
""".split())
# Words that make a sentence a requirement, a goal, a constraint, a complaint or an example, so it stays.
COVER_CUE = frozenset("""
must should need needs needed want wants wanted never always dont cannot cant instead without only ensure
problem issue bug wrong bad weak noise lost lose losing goal idea example because important require required
requirement avoid prefer want hate stop keep every each all
нужно надо хочу хотел хотела хотим должен должна должно должны чтобы проблема ошибка баг плохо слабое
шум теряет теряется теряются теряла цель идея например важно нельзя всегда никогда без только пример
лучше хуже сложно непонятно мешает требуется обязательно избегать вместо
""".split())
# Questions about the agent's own state or progress; they ask for a status, not for a feature.
COVER_AGENT_STATE = (
    r"\b(?:are you|did you|have you|were you|is it (?:done|finished|ready|running|stuck|working)|"
    r"is (?:the )?(?:sprint|build|run|lane|agent|session) (?:done|finished|ready|running|stuck|still)|"
    r"how (?:is it going|long|far)|what(?:'s| is) (?:the )?(?:status|state|progress)|where are you|"
    r"what are you (?:doing|working)|still (?:working|running|alive))\b",
    r"\b(?:ты (?:уже|еще|ещё|тут|жив|закончил|закончила|работаешь|сделал|сделала|все|всё)|"
    r"как (?:дела|успехи|идет|идёт|продвигается)|что (?:сейчас|там) (?:делаешь|происходит)|"
    r"(?:закончил|закончила|готов|готово|завис)\b.*\?|расскажи (?:мне )?что (?:сделано|сделал|готово)|что (?:сделано|готово))",
)
# A heading, or a line that opens with these phrases and a colon, lists what the plan leaves out.
COVER_OUT_OF_SCOPE = (
    r"out[\s-]+of[\s-]+scope", r"non[\s-]?goals?", r"not (?:doing|in scope|now|yet|included)", r"deferred",
    r"won'?t (?:do|build|ship)", r"left out", r"later\b", r"not planned", r"descoped?",
    r"за рамками", r"вне рамок", r"не делаем", r"не входит", r"отложено", r"позже", r"не в этом",
)
