package teyla.review

import android.text.method.PasswordTransformationMethod
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.compose.ui.InternalComposeUiApi
import androidx.compose.ui.node.RootForTest
import androidx.compose.ui.semantics.SemanticsNode
import androidx.compose.ui.semantics.SemanticsProperties

/**
 * Fields that are masked in every picture without `reviewPrivate()`, like the web package's password, card and one-time-code
 * inputs: a password or number-password input type, a password / card / one-time-code autofill hint, and (in Compose)
 * a text field whose semantics say `password`. The rules are plain functions, so the JVM tests cover them. The two scans
 * below read a live window and run on the main thread.
 */

// The values of android.text.InputType, copied so the rules run in a JVM test without the Android framework.
private const val CLASS_MASK = 0x0000000f
private const val VARIATION_MASK = 0x00000ff0
private const val CLASS_TEXT = 0x1
private const val CLASS_NUMBER = 0x2
private const val TEXT_PASSWORD = 0x80
private const val TEXT_VISIBLE_PASSWORD = 0x90
private const val TEXT_WEB_PASSWORD = 0xe0
private const val NUMBER_PASSWORD = 0x10

/** The values of the `View.AUTOFILL_HINT_*` constants that name a secret. */
internal val SENSITIVE_AUTOFILL_HINTS = setOf(
    "password", "newPassword", "creditCardNumber", "creditCardSecurityCode", "creditCardExpirationDate",
    "creditCardExpirationMonth", "creditCardExpirationYear", "creditCardExpirationDay", "smsOTPCode",
)

internal fun isSensitiveInputType(inputType: Int): Boolean {
    val variation = inputType and VARIATION_MASK
    return when (inputType and CLASS_MASK) {
        CLASS_TEXT -> variation == TEXT_PASSWORD || variation == TEXT_VISIBLE_PASSWORD || variation == TEXT_WEB_PASSWORD
        CLASS_NUMBER -> variation == NUMBER_PASSWORD
        else -> false
    }
}

internal fun isSensitiveField(inputType: Int, autofillHints: Array<String>?, hidesText: Boolean = false): Boolean =
    hidesText || isSensitiveInputType(inputType) || (autofillHints?.any { it in SENSITIVE_AUTOFILL_HINTS } == true)

internal object SensitiveViews {
    /** The window frames, in px, of every visible sensitive field under [root]: classic views and Compose text fields. */
    fun frames(root: View): List<Frame> {
        val out = ArrayList<Frame>()
        walk(root, out)
        return out
    }

    private fun walk(view: View, out: MutableList<Frame>) {
        if (view.visibility != View.VISIBLE || view.alpha < 0.01f) return
        if (view is TextView) {
            val hints = if (android.os.Build.VERSION.SDK_INT >= 26) view.autofillHints else null
            val hides = view.transformationMethod is PasswordTransformationMethod
            if (isSensitiveField(view.inputType, hints, hides) && view.width > 0 && view.height > 0) {
                val at = IntArray(2)
                view.getLocationInWindow(at)
                out.add(Frame(at[0].toDouble(), at[1].toDouble(), view.width.toDouble(), view.height.toDouble()))
            }
        }
        composeFrames(view, out)
        if (view is ViewGroup) for (i in 0 until view.childCount) walk(view.getChildAt(i), out)
    }

    /** A Compose text field with `password()` semantics (`PasswordVisualTransformation`, a password keyboard). */
    @OptIn(InternalComposeUiApi::class)
    private fun composeFrames(view: View, out: MutableList<Frame>) {
        val owner = try { (view as? RootForTest)?.semanticsOwner } catch (e: Throwable) { null } ?: return
        fun visit(node: SemanticsNode) {
            if (SemanticsProperties.Password in node.config) {
                val b = node.boundsInWindow
                out.add(Frame(b.left.toDouble(), b.top.toDouble(), b.width.toDouble(), b.height.toDouble()))
            }
            node.children.forEach(::visit)
        }
        try { visit(owner.unmergedRootSemanticsNode) } catch (e: Exception) { out.add(Frame(Double.NaN, 0.0, 0.0, 0.0)) }
    }
}
