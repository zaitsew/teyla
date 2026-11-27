"""Recognition data for `teyla design-hint`: the words that mark a prompt as a design request
(drawings, mockups, concepts, redesigns for review) and the words that say the owner also wants
the thing built. English, Russian and Spanish. Non-English entries are data a detector needs;
the comments are English.
"""

# A word that alone makes a prompt a design request. Matched case-insensitively on word starts.
DESIGN_STRONG = (
    r"mock[- ]?ups?", r"wireframes?", r"re-?designs?", r"design concepts?", r"screen concepts?",
    r"concepts? (?:for|of) (?:the |a |an )?(?:screen|app|ui|ios|android|web|page|flow)",
    r"design variants?", r"design frames?", r"high-fidelity", r"hi-fi",
    # Russian: draw (imperative), redraw, layout/mockup, redesign, concept
    r"нарису\w+", r"отрису\w+", r"перерису\w+", r"макет\w*", r"редизайн\w*", r"концепт\w*",
    # Spanish: draw, sketch, mockup, redesign, concept
    r"dibuja\w*", r"boceto\w*", r"maquet\w+", r"rediseñ\w+", r"concepto\w* de (?:pantalla|diseño|interfaz)",
)

# "draw" or "sketch" counts only beside a UI noun within a few words ("draw a full iOS version"),
# so a code request like "draw the chart in Canvas" is left alone.
DRAW_VERBS = (r"draw", r"sketch", r"illustrate", r"design", r"отрисуй\w*", r"нарисуй\w*", r"dibuja\w*")
UI_NOUNS = (r"screens?", r"ui", r"ux", r"ios", r"android", r"app", r"version", r"layout", r"interface",
            r"onboarding", r"home", r"экран\w*", r"интерфейс\w*", r"версию", r"pantallas?", r"interfaz", r"versión")

# Words that say the owner also wants the work implemented. Checked only when a design request matched.
IMPLEMENT = (
    r"implement\w*", r"ship(?:ping)?", r"testflight", r"swiftui", r"build (?:it|this|the app|the screens?|a prototype)",
    r"code (?:it|this|them) up", r"make it real", r"put (?:it|this) into (?:the )?app",
    # Russian: implement, build it, start development, ship, put into the app
    r"реализуй\w*", r"имплементируй\w*", r"внедри\w*", r"запусти в разработку", r"собери приложение",
    r"в разработку", r"выкати\w*",
    # Spanish: implement, program, ship
    r"implementa\w*", r"programa (?:la|el|esto)", r"súbelo", r"publica\w*",
)

# A negation just before an implement word turns it off ("don't build", "no code", "не делай код").
NEGATION = (r"don'?t", r"do not", r"no", r"not", r"without", r"never", r"не", r"нет", r"без", r"sin", r"nunca")

# Phrases that contain a design word without meaning a design request; removed before matching.
NOT_DESIGN = (r"proof[- ]of[- ]concept", r"\bpoc\b")
