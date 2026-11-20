package teyla.review

/**
 * What a report may not carry out of the app. The Swift, TypeScript and Python implementations (`ReviewScrub.swift`,
 * `scrub.ts`, `packages/review-channel/server.py`) run the same rules against the same test vectors
 * (`packages/review-channel/test-vectors/scrub.json`). Placeholders are never matched by a rule, so scrubbing twice
 * gives the same text.
 */
internal const val LABEL_CAP = 200

private val URL_PARAM = Regex("""([?&;][A-Za-z0-9_.\-]*(?:token|key|secret|password|passwd|pwd|auth|code|sig)[A-Za-z0-9_.\-]*=)[^&#\s]+""", RegexOption.IGNORE_CASE)
private val JWT = Regex("""(?<![A-Za-z0-9_\-])eyJ[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]*""")
private val BEARER = Regex("""(?<![A-Za-z0-9])Bearer[ \t]+[A-Za-z0-9._~+/=\-]{12,}""", RegexOption.IGNORE_CASE)
private val API_KEY = Regex(
    """(?<![A-Za-z0-9_\-])(?:(?:sk|pk|rk)[_\-][A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}""" +
        """|xox[abprs]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|AIza[A-Za-z0-9_\-]{30,})""",
)
private val EMAIL = Regex("""[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+""")
private val IBAN = Regex("""(?<![A-Za-z0-9])[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?(?![A-Za-z0-9])""")
private val CARD = Regex("""(?<![0-9])[0-9](?:[ \-]?[0-9]){12,18}(?![0-9])""")
private val PHONE = Regex("""(?<![A-Za-z0-9+])(?![0-9]{4}-[0-9]{2}-[0-9]{2})\+?[0-9(][0-9 .()\-]{6,}[0-9](?![A-Za-z0-9])""")

private fun digitsOf(text: String): String = text.filter { it in '0'..'9' }

private fun luhn(digits: String): Boolean {
    var total = 0
    for ((i, ch) in digits.reversed().withIndex()) {
        var n = ch - '0'
        if (i % 2 == 1) {
            n *= 2
            if (n > 9) n -= 9
        }
        total += n
    }
    return total % 10 == 0
}

/** E-mail addresses, phone numbers, card numbers, IBANs, bearer tokens, API keys, JWTs and the values of secret URL
 *  parameters, each replaced by a placeholder. */
internal fun scrub(text: String): String {
    var out = URL_PARAM.replace(text) { it.groupValues[1] + "[token]" }
    out = JWT.replace(out) { "[token]" }
    out = BEARER.replace(out) { "Bearer [token]" }
    out = API_KEY.replace(out) { "[token]" }
    out = EMAIL.replace(out) { "[email]" }
    out = IBAN.replace(out) { "[iban]" }
    out = CARD.replace(out) {
        val d = digitsOf(it.value)
        if (d.length in 13..19 && luhn(d)) "[card]" else it.value
    }
    return PHONE.replace(out) { phoneOrSplit(it.value) }
}

/** One number, or several separated by spaces: the longest run of space-separated groups that fits in
 *  15 digits is one number, repeatedly; a short tail joins the last run. */
private fun phoneOrSplit(m: String): String {
    val n = digitsOf(m).length
    val low = if (m.startsWith("+")) 8 else 9
    if (n in low..15) return "[phone]"
    if (n <= 15) return m
    val tokens = m.split(" ")
    val out = ArrayList<String>()
    var i = 0
    while (i < tokens.size) {
        val floor = if (tokens[i].startsWith("+")) 8 else 9
        var best = -1
        var total = 0
        for (j in i until tokens.size) {
            total += digitsOf(tokens[j]).length
            if (total > 15) break
            if (total >= floor) best = j
        }
        if (best >= 0) {
            out.add("[phone]")
            i = best + 1
        } else if (out.isNotEmpty() && out.last() == "[phone]") {
            i += 1
        } else {
            out.add(tokens[i])
            i += 1
        }
    }
    return out.joinToString(" ")
}

/** An accessibility label: scrubbed first, then at most 200 characters. */
internal fun scrubLabel(text: String): String = scrub(text).take(LABEL_CAP)
