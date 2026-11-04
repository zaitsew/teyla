import CoreGraphics

/// What a capture may say about the view under a tap, when that view is `.reviewPrivate()`. The
/// picture hides the view; these rules keep its metadata out of `capture.json` too. No UIKit, so the
/// tests run on the Mac.
///
/// `frames` are the rectangles painted black (`ReviewMasking.rects`), in window points.
enum ReviewRedaction {
    /// True when the private views are still where the picture painted them, within a point. Any
    /// other answer means a live look at the window could read a view the frozen masks miss.
    static func masksUnchanged(frozen: [CGRect], live: [CGRect]) -> Bool {
        guard frozen.count == live.count else { return false }
        let order: (CGRect, CGRect) -> Bool = { ($0.minY, $0.minX) < ($1.minY, $1.minX) }
        return zip(frozen.sorted(by: order), live.sorted(by: order)).allSatisfy { a, b in
            abs(a.minX - b.minX) <= 1 && abs(a.minY - b.minY) <= 1 && abs(a.width - b.width) <= 1 && abs(a.height - b.height) <= 1
        }
    }

    /// True when the tapped point, or any part of the circled area, is inside a painted rectangle.
    static func touchesPrivate(point: CGPoint?, region: CGRect?, frames: [CGRect]) -> Bool {
        frames.contains { frame in
            if let point, frame.contains(point) { return true }
            if let region, frame.intersects(region) { return true }
            return false
        }
    }

    /// What the tap resolved to: the anchor under it, the accessibility identifier and the label.
    /// A tap in a private region keeps none of them, so the capture has no `element`, no
    /// `tap.accessibility_identifier` and no `tap.accessibility_label` (and no `source` file and line).
    static func pointed(
        hit: Anchor?, identifier: String?, label: String?, point: CGPoint?, region: CGRect?, frames: [CGRect]
    ) -> (hit: Anchor?, identifier: String?, label: String?) {
        touchesPrivate(point: point, region: region, frames: frames) ? (nil, nil, nil) : (hit, identifier, label)
    }

    /// The anchors written to the capture: one that overlaps a private rectangle loses its `strings`
    /// (the keys of the text it shows). Its id, role, bounds and source are developer-chosen names and
    /// geometry, not what the screen showed.
    static func anchors(_ anchors: [Anchor], frames: [CGRect]) -> [Anchor] {
        anchors.map { anchor in
            guard !anchor.strings.isEmpty, frames.contains(where: { $0.intersects(anchor.bounds) }) else { return anchor }
            var copy = anchor
            copy.strings = []
            return copy
        }
    }
}
