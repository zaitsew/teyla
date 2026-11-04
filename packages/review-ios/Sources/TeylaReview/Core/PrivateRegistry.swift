import CoreGraphics
import Foundation

/// The views marked `.reviewPrivate()` that are on screen now. Same shape as `AnchorRegistry`: a view
/// registers under its own token, and its frame is read when the picture is taken, so a scrolled
/// list masks the rows where they are now.
final class PrivateRegistry: @unchecked Sendable {
    static let shared = PrivateRegistry()

    private let lock = NSLock()
    private var entries: [UUID: () -> CGRect?] = [:]      // nil: the view is gone

    func register(token: UUID, bounds: @escaping () -> CGRect?) {
        lock.lock(); defer { lock.unlock() }
        entries[token] = bounds
    }

    func remove(token: UUID) {
        lock.lock(); defer { lock.unlock() }
        entries[token] = nil
    }

    func reset() {
        lock.lock(); defer { lock.unlock() }
        entries = [:]
    }

    /// Every frame with area, in window points. A view that is gone is dropped from the registry.
    func snapshot() -> [CGRect] {
        lock.lock()
        let list = Array(entries)
        lock.unlock()
        var out: [CGRect] = []
        var gone: [UUID] = []
        for (token, bounds) in list {
            guard let rect = bounds() else { gone.append(token); continue }
            if rect.width > 0, rect.height > 0 { out.append(rect) }
        }
        if !gone.isEmpty {
            lock.lock()
            for token in gone { entries[token] = nil }
            lock.unlock()
        }
        return out
    }
}

/// Where the black boxes go. No UIKit, so the tests run on the Mac.
enum ReviewMasking {
    /// A margin around a private view, in points: antialiasing and a shadow must not leave an edge
    /// of the text visible.
    static let padding: CGFloat = 2

    /// The rectangles to paint, in window points: each frame grown by `padding`, snapped outward to
    /// whole pixels of the picture, cut to the window, and dropped when nothing is left of it.
    static func rects(for frames: [CGRect], in window: CGRect, scale: CGFloat) -> [CGRect] {
        guard scale > 0, window.width > 0, window.height > 0 else { return [] }
        return frames.compactMap { frame in
            guard !frame.isNull, !frame.isInfinite, frame.width > 0, frame.height > 0 else { return nil }
            let grown = frame.insetBy(dx: -padding, dy: -padding)
            let minX = (grown.minX * scale).rounded(.down) / scale, minY = (grown.minY * scale).rounded(.down) / scale
            let maxX = (grown.maxX * scale).rounded(.up) / scale, maxY = (grown.maxY * scale).rounded(.up) / scale
            let snapped = CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY)
            let clipped = snapped.intersection(window)
            return clipped.isNull || clipped.width <= 0 || clipped.height <= 0 ? nil : clipped
        }
    }
}
