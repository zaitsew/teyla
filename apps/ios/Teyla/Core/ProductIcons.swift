import Foundation
import UIKit

/// Product icons from `portfolio.products[].icon_jpeg`, decoded once. A redraw of Home asks again for every card;
/// the answer comes from here and the base64 is not decoded twice. A changed string (a new icon) decodes again.
/// The phone twin of the Mac's `ProductIcons`: same rule, `UIImage` instead of `NSImage`.
@MainActor
enum ProductIcons {
    private final class Entry {
        let source: String
        let image: UIImage?

        init(source: String, image: UIImage?) {
            self.source = source
            self.image = image
        }
    }

    private static let cache = NSCache<NSString, Entry>()
    /// How many times a base64 string was decoded; the tests read it to prove that a redraw does not decode.
    private(set) static var decodeCount = 0

    /// nil when the product has no icon or the data is not an image: the card then draws a monogram.
    static func image(id: String, base64: String) -> UIImage? {
        guard !base64.isEmpty else { return nil }
        let key = id as NSString
        if let hit = cache.object(forKey: key), hit.source == base64 { return hit.image }
        decodeCount += 1
        let image = Data(base64Encoded: base64, options: .ignoreUnknownCharacters).flatMap { UIImage(data: $0) }
        cache.setObject(Entry(source: base64, image: image), forKey: key)
        return image
    }

    static func reset() {
        cache.removeAllObjects()
        decodeCount = 0
    }
}
