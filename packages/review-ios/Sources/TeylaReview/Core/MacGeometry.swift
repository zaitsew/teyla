import CoreGraphics

/// AppKit puts the origin of a window at the bottom left; a capture puts it at the top left. These
/// conversions are plain arithmetic, so the tests run without AppKit.
enum MacGeometry {
    /// A rectangle in a view's own coordinates, in window points from the top left of `container`.
    /// A flipped view already counts from the top.
    static func topLeft(_ rect: CGRect, containerHeight: CGFloat, flipped: Bool) -> CGRect {
        flipped ? rect : CGRect(x: rect.minX, y: containerHeight - rect.maxY, width: rect.width, height: rect.height)
    }

    /// The same rule for a point.
    static func viewPoint(fromTopLeft point: CGPoint, containerHeight: CGFloat, flipped: Bool) -> CGPoint {
        flipped ? point : CGPoint(x: point.x, y: containerHeight - point.y)
    }

    /// A frame a view reports, as a mask. A view that cannot say where it is (a NaN or infinite
    /// number) gets the whole window, so it fails towards hiding.
    static func maskFrame(_ rect: CGRect, container: CGRect) -> CGRect {
        let finite = !rect.isNull && !rect.isInfinite && rect.origin.x.isFinite && rect.origin.y.isFinite
            && rect.size.width.isFinite && rect.size.height.isFinite
        return finite ? rect : container
    }

    /// A frame in screen coordinates (origin bottom left of the main display), in window points from
    /// the top left of the window's content, whose own screen rectangle is `content`.
    static func topLeft(inScreen rect: CGRect, content: CGRect) -> CGRect {
        CGRect(x: rect.minX - content.minX, y: content.maxY - rect.maxY, width: rect.width, height: rect.height)
    }
}

/// The review window is sized for the picture and the form beside it, and kept inside the screen.
enum MacLayout {
    static let formWidth: CGFloat = 320
    static let minimum = CGSize(width: 760, height: 520)

    static func windowSize(for content: CGSize, visible: CGSize) -> CGSize {
        let maxWidth = visible.width * 0.9, maxHeight = visible.height * 0.9
        let pictureWidth = max(1, maxWidth - formWidth - 24), pictureHeight = max(1, maxHeight - 24)
        let ratio = content.width > 0 && content.height > 0
            ? min(1, pictureWidth / content.width, pictureHeight / content.height) : 1
        let shown = CGSize(width: content.width * ratio, height: content.height * ratio)
        return CGSize(width: min(max(minimum.width, shown.width + formWidth + 24), maxWidth),
                      height: min(max(minimum.height, shown.height + 24), maxHeight))
    }
}
