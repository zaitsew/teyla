package teyla.review

/** The first-send notice and the check that sits before Send. */
internal const val NOTICE_KEY = "teyla.review.noticeAccepted"

internal interface KeyValue {
    fun getBoolean(key: String): Boolean
    fun putBoolean(key: String, value: Boolean)
}

/** True once the tester pressed OK on the notice, on this install. */
internal fun isAccepted(kv: KeyValue?): Boolean = try { kv?.getBoolean(NOTICE_KEY) == true } catch (e: Exception) { false }

internal fun accept(kv: KeyValue?) {
    try { kv?.putBoolean(NOTICE_KEY, true) } catch (e: Exception) { /* the notice shows again next time */ }
}

/** The notice appears before a send that can leave the device, until the tester has accepted it once. */
internal fun isNeeded(sendsToServer: Boolean, kv: KeyValue?): Boolean = sendsToServer && !isAccepted(kv)

/** Whether Send is enabled: a comment, no save under way, and the health box ticked when the product requires it. */
internal fun canSend(comment: String, sending: Boolean, requiresHealthConsent: Boolean, healthConsentGiven: Boolean): Boolean =
    !sending && comment.trim().isNotEmpty() && (!requiresHealthConsent || healthConsentGiven)
