#if TEYLA_REVIEW && canImport(UIKit)
import AVFoundation
import UIKit

enum DeviceProbe {
    static func keyWindow() -> UIWindow? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let active = scenes.first { $0.activationState == .foregroundActive } ?? scenes.first
        return active?.windows.first { $0.isKeyWindow } ?? active?.windows.first
    }

    static func topViewController(from root: UIViewController?) -> UIViewController? {
        var top = root
        while let next = top?.presentedViewController { top = next }
        if let nav = top as? UINavigationController, let visible = nav.visibleViewController { return topViewController(from: visible) }
        if let tab = top as? UITabBarController, let selected = tab.selectedViewController { return topViewController(from: selected) }
        return top
    }

    /// The frozen picture: the key window as it is, at its own scale.
    static func screenshot(of window: UIWindow) -> (png: Data, pixelWidth: Int, pixelHeight: Int, scale: Double)? {
        let format = UIGraphicsImageRendererFormat.preferred()
        format.opaque = true
        let renderer = UIGraphicsImageRenderer(bounds: window.bounds, format: format)
        let image = renderer.image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: false) }
        guard let png = image.pngData() else { return nil }
        let scale = Double(format.scale)
        return (png, Int((window.bounds.width * format.scale).rounded()), Int((window.bounds.height * format.scale).rounded()), scale)
    }

    /// The identifier and label under a point, from the UIKit views. SwiftUI keeps most elements out
    /// of UIKit, so this is the fallback when no anchor is under the tap.
    static func accessibility(at point: CGPoint, in window: UIWindow) -> (identifier: String?, label: String?) {
        var view = window.hitTest(point, with: nil)
        var identifier: String?
        var label: String?
        while let current = view {
            if identifier == nil, let id = current.accessibilityIdentifier, !id.isEmpty { identifier = id }
            if label == nil, let text = current.accessibilityLabel, !text.isEmpty { label = text }
            if identifier != nil, label != nil { break }
            view = current.superview
        }
        return (identifier, label)
    }

    static func environment(window: UIWindow) -> EnvironmentInfo {
        let device = UIDevice.current
        let locale = Locale.current
        return EnvironmentInfo(
            os: "\(device.systemName) \(device.systemVersion)", model: modelIdentifier(),
            locale: locale.identifier, language: locale.language.languageCode?.identifier,
            appearance: window.traitCollection.userInterfaceStyle == .dark ? "dark" : "light",
            dynamicType: dynamicTypeName(window.traitCollection.preferredContentSizeCategory),
            screen: ScreenSize(width: Double(window.bounds.width), height: Double(window.bounds.height), scale: Double(window.traitCollection.displayScale)))
    }

    static func deviceClass() -> String {
        AppProbe.sanitizeDevice(UIDevice.current.userInterfaceIdiom == .pad ? "iPad" : "iPhone")
    }

    static func modelIdentifier() -> String {
        var info = utsname()
        uname(&info)
        let text = withUnsafePointer(to: &info.machine) {
            $0.withMemoryRebound(to: CChar.self, capacity: Int(_SYS_NAMELEN)) { String(cString: $0) }
        }
        return text.isEmpty ? "unknown" : text
    }

    static func dynamicTypeName(_ c: UIContentSizeCategory) -> String {
        switch c {
        case .extraSmall: return "xSmall"
        case .small: return "small"
        case .medium: return "medium"
        case .large: return "large"
        case .extraLarge: return "xLarge"
        case .extraExtraLarge: return "xxLarge"
        case .extraExtraExtraLarge: return "xxxLarge"
        case .accessibilityMedium: return "accessibilityMedium"
        case .accessibilityLarge: return "accessibilityLarge"
        case .accessibilityExtraLarge: return "accessibilityXLarge"
        case .accessibilityExtraExtraLarge: return "accessibilityXXLarge"
        case .accessibilityExtraExtraExtraLarge: return "accessibilityXXXLarge"
        default: return "unspecified"
        }
    }
}

/// The real AVAudioSession behind the guard's protocol.
struct SystemAudioSession: AudioSessionControlling {
    private var session: AVAudioSession { AVAudioSession.sharedInstance() }
    var categoryName: String { session.category.rawValue }
    var modeName: String { session.mode.rawValue }
    var optionsRaw: UInt { session.categoryOptions.rawValue }

    func restore(category: String, mode: String, options: UInt) throws {
        try session.setCategory(AVAudioSession.Category(rawValue: category), mode: AVAudioSession.Mode(rawValue: mode),
                                options: AVAudioSession.CategoryOptions(rawValue: options))
    }

    func setActive(_ active: Bool) throws {
        try session.setActive(active, options: active ? [] : [.notifyOthersOnDeactivation])
    }
}
#endif
