#if TEYLA_REVIEW && os(macOS)
import AppKit
import SwiftUI

/// The window a capture is being taken from. The frame probes of `.reviewPrivate()` and
/// `.reviewAnchor()` report their frames in this window's content only; a view in any other window
/// reports nothing. Set by the presenter around a capture.
@MainActor
enum MacCapture {
    static weak var window: NSWindow?
}

/// What the key window looked like when review mode opened. Window points count from the top left of
/// the window's content view, as in a capture.
struct MacShot {
    var png: Data
    var pixelWidth: Int
    var pixelHeight: Int
    var scale: Double
    var privateFrames: [CGRect]
    /// Metal, map, 3D or video views whose pixels came out blank.
    var blankAreas: [CGRect]
    /// The whole picture came out transparent.
    var windowBlank: Bool
}

@MainActor
enum MacProbe {
    static func keyWindow() -> NSWindow? {
        let usable: (NSWindow) -> Bool = { $0.isVisible && !$0.isMiniaturized && $0.contentView != nil }
        if let key = NSApp.keyWindow, usable(key) { return key }
        if let main = NSApp.mainWindow, usable(main) { return main }
        return NSApp.windows.first(where: usable)
    }

    // MARK: the picture

    /// Views that draw with the GPU or a media layer: `cacheDisplay` often cannot read them.
    static func isGPUView(_ view: NSView) -> Bool {
        if view.layer is CAMetalLayer { return true }
        let name = NSStringFromClass(type(of: view))
        return ["MKMapView", "MTKView", "SCNView", "SKView", "AVPlayerView", "ARView"].contains { name.contains($0) }
    }

    private static func gpuFrames(under root: NSView, in content: NSView) -> [CGRect] {
        var found: [CGRect] = []
        func walk(_ view: NSView) {
            guard !view.isHidden else { return }
            if isGPUView(view), view.bounds.width >= 20, view.bounds.height >= 20 {
                let inContent = view.convert(view.bounds, to: content)
                found.append(MacGeometry.topLeft(inContent, containerHeight: content.bounds.height, flipped: content.isFlipped))
            }
            view.subviews.forEach(walk)
        }
        walk(root)
        return found
    }

    /// The frozen picture: the window's content as `cacheDisplay` draws it, at the screen's backing
    /// scale, with every `.reviewPrivate()` view painted black. The form shows this same picture and
    /// it is the one that is saved and sent. Nil when AppKit cannot draw the window; then nothing opens.
    static func screenshot(of window: NSWindow) -> MacShot? {
        guard let content = window.contentView else { return nil }
        let bounds = content.bounds
        guard bounds.width >= 1, bounds.height >= 1,
              let rep = content.bitmapImageRepForCachingDisplay(in: bounds) else { return nil }
        content.cacheDisplay(in: bounds, to: rep)
        guard let raw = rep.cgImage else { return nil }
        let scale = Double(raw.width) / Double(bounds.width)

        var blank: [CGRect] = []
        var windowBlank = false
        if let pixels = ReviewBitmap.pixels(of: raw) {
            let size = CGRect(origin: .zero, size: bounds.size)
            windowBlank = ReviewBitmap.isTransparent(pixels, rect: size, scale: CGFloat(scale))
            blank = gpuFrames(under: content, in: content)
                .filter { ReviewBitmap.isBlank(pixels, rect: $0, scale: CGFloat(scale)) }
        }

        let window0 = CGRect(origin: .zero, size: bounds.size)
        let masks = ReviewMasking.rects(for: PrivateRegistry.shared.snapshot(), in: window0, scale: CGFloat(scale))
        var background = CGColor(red: 1, green: 1, blue: 1, alpha: 1)
        window.effectiveAppearance.performAsCurrentDrawingAppearance {
            if let srgb = NSColor.windowBackgroundColor.usingColorSpace(.sRGB) { background = srgb.cgColor }
        }
        guard let painted = ReviewBitmap.blackOut(raw, rects: masks, scale: CGFloat(scale), background: background),
              let png = ReviewBitmap.pngData(painted) else { return nil }
        return MacShot(png: png, pixelWidth: painted.width, pixelHeight: painted.height, scale: scale,
                       privateFrames: masks, blankAreas: blank, windowBlank: windowBlank)
    }

    // MARK: what is under a click

    /// The identifier and label under a point (window points from the top left of the content). The
    /// accessibility tree answers first, because SwiftUI keeps its elements there and not in the view
    /// tree; the AppKit views are the fallback. An element that overlaps a private rectangle lends
    /// neither identifier nor label, and neither does one whose frame cannot be told while a private
    /// rectangle exists: it fails towards hiding.
    static func accessibility(
        at point: CGPoint, in window: NSWindow, avoiding: [CGRect] = []
    ) -> (identifier: String?, label: String?) {
        guard let content = window.contentView else { return (nil, nil) }
        let viewPoint = MacGeometry.viewPoint(fromTopLeft: point, containerHeight: content.bounds.height, flipped: content.isFlipped)
        let contentOnScreen = window.convertToScreen(content.convert(content.bounds, to: nil))
        var identifier: String?
        var label: String?

        func take(_ element: NSObjectProtocol, frame: CGRect?) {
            guard avoiding.isEmpty || frame.map({ f in !avoiding.contains { $0.intersects(f) } }) == true else { return }
            guard let element = element as? NSAccessibilityProtocol else { return }
            if identifier == nil, let id = element.accessibilityIdentifier(), !id.isEmpty { identifier = id }
            if label == nil, let text = element.accessibilityLabel(), !text.isEmpty { label = text }
        }

        let screenPoint = window.convertPoint(toScreen: content.convert(viewPoint, to: nil))
        if var element = content.accessibilityHitTest(screenPoint) as? NSObject {
            var depth = 0
            while depth < 24, element !== content {
                let frame = (element as? NSAccessibilityProtocol).map { $0.accessibilityFrame() }
                    .flatMap { $0.isEmpty ? nil : MacGeometry.topLeft(inScreen: $0, content: contentOnScreen) }
                take(element, frame: frame)
                if identifier != nil, label != nil { break }
                guard let parent = (element as? NSAccessibilityProtocol)?.accessibilityParent() as? NSObject else { break }
                element = parent
                depth += 1
            }
        }
        guard identifier == nil || label == nil else { return (identifier, label) }

        var view = content.hitTest(content.convert(viewPoint, to: content.superview))
        while let current = view {
            let inContent = current.convert(current.bounds, to: content)
            let frame = MacGeometry.topLeft(inContent, containerHeight: content.bounds.height, flipped: content.isFlipped)
            if avoiding.isEmpty || !avoiding.contains(where: { $0.intersects(frame) }) {
                if identifier == nil { let id = current.accessibilityIdentifier(); if !id.isEmpty { identifier = id } }
                if label == nil, let text = current.accessibilityLabel(), !text.isEmpty { label = text }
                if identifier != nil, label != nil { break }
            }
            if current === content { break }
            view = current.superview
        }
        return (identifier, label)
    }

    // MARK: the machine

    static func environment(window: NSWindow) -> EnvironmentInfo {
        let version = ProcessInfo.processInfo.operatingSystemVersion
        let patch = version.patchVersion == 0 ? "" : ".\(version.patchVersion)"
        let locale = Locale.current
        let dark = window.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        let size = window.contentView?.bounds.size ?? .zero
        return EnvironmentInfo(
            os: "macOS \(version.majorVersion).\(version.minorVersion)\(patch)", model: modelIdentifier(),
            locale: locale.identifier, language: locale.language.languageCode?.identifier,
            appearance: dark ? "dark" : "light", dynamicType: "unspecified",
            screen: ScreenSize(width: max(1, Double(size.width)), height: max(1, Double(size.height)),
                               scale: max(1, Double(window.backingScaleFactor))))
    }

    static func deviceClass() -> String { AppProbe.sanitizeDevice("Mac") }

    static func modelIdentifier() -> String {
        var size = 0
        sysctlbyname("hw.model", nil, &size, nil, 0)
        guard size > 1 else { return "unknown" }
        var buffer = [CChar](repeating: 0, count: size)
        sysctlbyname("hw.model", &buffer, &size, nil, 0)
        let text = String(cString: buffer)
        return text.isEmpty ? "unknown" : String(text.prefix(64))
    }
}
#endif
