import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Pixel work on a captured window that needs neither UIKit nor AppKit, so the tests run on the Mac:
/// painting the private areas black, finding a picture that came out empty, and encoding the PNG.
/// Rectangles are in window points with the origin at the top left, the way a capture states them.
enum ReviewBitmap {
    /// RGBA, 8 bits per channel, premultiplied alpha, rows from the top of the picture to the bottom.
    struct Pixels {
        var width: Int
        var height: Int
        var bytes: [UInt8]

        func rgba(x: Int, y: Int) -> (r: UInt8, g: UInt8, b: UInt8, a: UInt8) {
            let i = (y * width + x) * 4
            return (bytes[i], bytes[i + 1], bytes[i + 2], bytes[i + 3])
        }
    }

    private static let colorSpace = CGColorSpace(name: CGColorSpace.sRGB) ?? CGColorSpaceCreateDeviceRGB()
    private static let layout = CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue

    private static func context(width: Int, height: Int) -> CGContext? {
        guard width > 0, height > 0 else { return nil }
        return CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                         space: colorSpace, bitmapInfo: layout)
    }

    /// The picture with every rectangle painted solid black. A rectangle is grown outward to whole
    /// pixels. One that is not a finite number (a view that could not say where it is) hides the
    /// whole picture: a mask that cannot be placed fails towards hiding, never towards showing.
    /// `background` is drawn first, so a window with a see-through titlebar or sidebar does not leave
    /// transparent holes in the PNG.
    static func blackOut(_ image: CGImage, rects: [CGRect], scale: CGFloat, background: CGColor? = nil) -> CGImage? {
        guard let ctx = context(width: image.width, height: image.height), scale > 0 else { return nil }
        let full = CGRect(x: 0, y: 0, width: image.width, height: image.height)
        if let background {
            ctx.setFillColor(background)
            ctx.fill(full)
        }
        ctx.draw(image, in: full)
        ctx.setFillColor(CGColor(red: 0, green: 0, blue: 0, alpha: 1))
        for rect in rects {
            guard Self.isFinite(rect) else { ctx.fill(full); continue }
            let left = (rect.minX * scale).rounded(.down), right = (rect.maxX * scale).rounded(.up)
            let top = (rect.minY * scale).rounded(.down), bottom = (rect.maxY * scale).rounded(.up)
            // Core Graphics counts rows from the bottom; the capture counts them from the top.
            let box = CGRect(x: left, y: full.height - bottom, width: right - left, height: bottom - top)
            ctx.fill(box.intersection(full))
        }
        return ctx.makeImage()
    }

    /// CGRect.null (which Core Graphics also reads an infinite origin as) is a view that lost its place.
    private static func isFinite(_ r: CGRect) -> Bool {
        !r.isNull && !r.isInfinite && r.origin.x.isFinite && r.origin.y.isFinite && r.size.width.isFinite && r.size.height.isFinite
    }

    static func pixels(of image: CGImage) -> Pixels? {
        guard let ctx = context(width: image.width, height: image.height) else { return nil }
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        guard let data = ctx.data else { return nil }
        let count = image.width * image.height * 4
        return Pixels(width: image.width, height: image.height,
                      bytes: Array(UnsafeBufferPointer(start: data.bindMemory(to: UInt8.self, capacity: count), count: count)))
    }

    /// The share of sampled pixels in `rect` (window points) that are one colour: the most common
    /// colour, with each channel rounded to steps of 8, counted over a grid of at most 48 by 48
    /// samples. A transparent pixel is one colour whatever its other channels say. 1 means nothing was
    /// drawn there; a picture of a real map or scene has many colours and scores far below the limit.
    static func emptyFraction(_ pixels: Pixels, rect: CGRect, scale: CGFloat) -> Double {
        let x0 = max(0, Int((rect.minX * scale).rounded(.down))), x1 = min(pixels.width, Int((rect.maxX * scale).rounded(.up)))
        let y0 = max(0, Int((rect.minY * scale).rounded(.down))), y1 = min(pixels.height, Int((rect.maxY * scale).rounded(.up)))
        guard x1 > x0, y1 > y0 else { return 0 }
        let columns = min(48, x1 - x0), rows = min(48, y1 - y0)
        var counts: [UInt32: Int] = [:]
        for row in 0..<rows {
            for column in 0..<columns {
                let x = x0 + (x1 - x0 - 1) * column / max(columns - 1, 1)
                let y = y0 + (y1 - y0 - 1) * row / max(rows - 1, 1)
                let p = pixels.rgba(x: x, y: y)
                let key: UInt32 = p.a == 0 ? 0xFFFF_FFFF : UInt32(p.r >> 3) << 16 | UInt32(p.g >> 3) << 8 | UInt32(p.b >> 3)
                counts[key, default: 0] += 1
            }
        }
        return Double(counts.values.max() ?? 0) / Double(columns * rows)
    }

    /// At or above this share of empty samples a region counts as blank.
    static let blankLimit = 0.995

    static func isBlank(_ pixels: Pixels, rect: CGRect, scale: CGFloat) -> Bool {
        emptyFraction(pixels, rect: rect, scale: scale) >= blankLimit
    }

    /// True when almost every sampled pixel of the region is fully transparent: the window itself
    /// came out empty, which a window with any drawn content never does.
    static func isTransparent(_ pixels: Pixels, rect: CGRect, scale: CGFloat) -> Bool {
        let x0 = max(0, Int((rect.minX * scale).rounded(.down))), x1 = min(pixels.width, Int((rect.maxX * scale).rounded(.up)))
        let y0 = max(0, Int((rect.minY * scale).rounded(.down))), y1 = min(pixels.height, Int((rect.maxY * scale).rounded(.up)))
        guard x1 > x0, y1 > y0 else { return false }
        let columns = min(48, x1 - x0), rows = min(48, y1 - y0)
        var clear = 0
        for row in 0..<rows {
            for column in 0..<columns {
                let x = x0 + (x1 - x0 - 1) * column / max(columns - 1, 1)
                let y = y0 + (y1 - y0 - 1) * row / max(rows - 1, 1)
                if pixels.rgba(x: x, y: y).a == 0 { clear += 1 }
            }
        }
        return Double(clear) / Double(columns * rows) >= blankLimit
    }

    static func pngData(_ image: CGImage) -> Data? {
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, UTType.png.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(destination, image, nil)
        return CGImageDestinationFinalize(destination) ? data as Data : nil
    }
}
