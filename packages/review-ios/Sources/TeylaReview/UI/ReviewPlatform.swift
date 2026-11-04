#if TEYLA_REVIEW && (canImport(UIKit) || os(macOS))
import SwiftUI
#if canImport(UIKit)
import UIKit
#else
import AppKit
#endif

/// The few places where the overlay's SwiftUI differs between a phone and a Mac. The overlay itself
/// is one file for both.
enum ReviewPlatform {
    #if canImport(UIKit)
    typealias NativeImage = UIImage
    static var isPointer: Bool { false }
    static var panelBackground: Color { Color(uiColor: .secondarySystemBackground) }
    static var fieldBackground: Color { Color(uiColor: .systemBackground) }
    static let savedSymbol = "iphone"
    static func empty() -> NativeImage { UIImage() }
    static func image(png: Data, size: CGSize) -> NativeImage { UIImage(data: png) ?? UIImage() }
    static func success() { UINotificationFeedbackGenerator().notificationOccurred(.success) }
    #else
    typealias NativeImage = NSImage
    static var isPointer: Bool { true }
    static var panelBackground: Color { Color(nsColor: .windowBackgroundColor) }
    static var fieldBackground: Color { Color(nsColor: .textBackgroundColor) }
    static let savedSymbol = "laptopcomputer"
    static func empty() -> NativeImage { NSImage() }
    /// The picture's size in points is the window's, so the image reports the same size as the window
    /// and not its pixel count.
    static func image(png: Data, size: CGSize) -> NativeImage {
        guard let image = NSImage(data: png) else { return NSImage() }
        image.size = size
        return image
    }
    static func success() {}
    #endif
}

extension Image {
    init(reviewImage image: ReviewPlatform.NativeImage) {
        #if canImport(UIKit)
        self.init(uiImage: image)
        #else
        self.init(nsImage: image)
        #endif
    }
}

extension View {
    /// Escape closes review mode on the Mac. Does nothing on a phone.
    func reviewCancelShortcut() -> some View {
        #if os(macOS)
        return keyboardShortcut(.cancelAction)
        #else
        return self
        #endif
    }
}
#endif
