#if TEYLA_REVIEW && canImport(UIKit)
import UIKit

/// The text fields that are masked in every picture without the product asking, like the web package's password,
/// card and one-time-code inputs: secure entry (a SwiftUI `SecureField` is a UITextField with it on) and the
/// password, one-time-code and card content types. Their frames join the `.reviewPrivate()` ones, so the picture
/// paints them black and the capture keeps no element, identifier or label for a tap on them.
enum SensitiveFields {
    static let contentTypes: [UITextContentType] = [
        .password, .newPassword, .oneTimeCode, .creditCardNumber, .creditCardSecurityCode, .creditCardExpiration,
        .creditCardExpirationMonth, .creditCardExpirationYear, .creditCardName,
    ]

    static func isSensitive(secureEntry: Bool, contentType: UITextContentType?) -> Bool {
        if secureEntry { return true }
        guard let contentType else { return false }
        return contentTypes.contains(contentType)
    }

    /// The window frames, in points, of every visible sensitive field under the window.
    static func frames(in window: UIWindow) -> [CGRect] {
        var found: [CGRect] = []
        func walk(_ view: UIView) {
            guard !view.isHidden, view.alpha > 0.01 else { return }
            let sensitive: Bool
            if let field = view as? UITextField {
                sensitive = isSensitive(secureEntry: field.isSecureTextEntry, contentType: field.textContentType)
            } else if let text = view as? UITextView {
                sensitive = isSensitive(secureEntry: text.isSecureTextEntry, contentType: text.textContentType)
            } else {
                sensitive = false
            }
            if sensitive, view.window != nil { found.append(view.convert(view.bounds, to: nil)) }
            view.subviews.forEach(walk)
        }
        walk(window)
        return found
    }
}
#endif
