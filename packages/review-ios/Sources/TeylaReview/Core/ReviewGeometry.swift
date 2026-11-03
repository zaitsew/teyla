import CoreGraphics

/// Between the shrunken picture on the screen and the window it shows. A capture always holds
/// window points, so a tap on the picture must be divided by the scale before it is used. No UIKit,
/// so the tests run on the Mac.
enum ReviewGeometry {
    /// A drag shorter than this, in points on the screen, is a tap and not an area.
    static let minimumDrag: CGFloat = 12

    /// The scale that fits the whole window into `available`, keeping its proportions. Never above 1.
    static func fit(_ window: CGSize, in available: CGSize) -> CGFloat {
        guard window.width > 0, window.height > 0 else { return 1 }
        return max(0, min(1, min(available.width / window.width, available.height / window.height)))
    }

    /// A point on the picture, in window points, kept inside the window.
    static func toWindow(_ point: CGPoint, scale: CGFloat, window: CGSize) -> CGPoint {
        guard scale > 0 else { return .zero }
        return CGPoint(x: min(max(0, point.x / scale), window.width), y: min(max(0, point.y / scale), window.height))
    }

    /// The area a drag on the picture drew, in window points. Nil when the drag is short enough to be a tap.
    static func region(from start: CGPoint, to end: CGPoint, scale: CGFloat, window: CGSize) -> CGRect? {
        guard max(abs(end.x - start.x), abs(end.y - start.y)) >= minimumDrag else { return nil }
        let a = toWindow(start, scale: scale, window: window)
        let b = toWindow(end, scale: scale, window: window)
        let rect = CGRect(x: min(a.x, b.x), y: min(a.y, b.y), width: abs(a.x - b.x), height: abs(a.y - b.y))
        return rect.width > 0 || rect.height > 0 ? rect : nil
    }
}
