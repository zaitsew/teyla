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

    /// A stroke's bounds, grown to take in one more point of it on the picture.
    static func grow(_ stroke: CGRect, with point: CGPoint) -> CGRect {
        let left = min(stroke.minX, point.x), top = min(stroke.minY, point.y)
        return CGRect(x: left, y: top, width: max(stroke.maxX, point.x) - left, height: max(stroke.maxY, point.y) - top)
    }

    /// The area a stroke on the picture drew, in window points: everything the finger passed through,
    /// so a closed circle counts as well as a drag from corner to corner. Nil when the stroke is small
    /// enough to be a tap.
    static func region(stroke: CGRect, scale: CGFloat, window: CGSize) -> CGRect? {
        guard max(stroke.width, stroke.height) >= minimumDrag else { return nil }
        let a = toWindow(CGPoint(x: stroke.minX, y: stroke.minY), scale: scale, window: window)
        let b = toWindow(CGPoint(x: stroke.maxX, y: stroke.maxY), scale: scale, window: window)
        let rect = CGRect(x: a.x, y: a.y, width: b.x - a.x, height: b.y - a.y)
        return rect.width > 0 || rect.height > 0 ? rect : nil
    }
}
