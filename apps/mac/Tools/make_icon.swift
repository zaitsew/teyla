#!/usr/bin/env swift
// Draws the Teyla app icon from brand/icon.svg (64 px and up) and brand/icon-small.svg (16, 16@2x
// and 32 px), and writes every size into
// Teyla/Assets.xcassets/AppIcon.appiconset, plus the Claude Code plugin icon.
//
//     python3 brand/build.py && swift apps/mac/Tools/make_icon.swift
//
// The artwork is the Cursor mark on the brand's indigo body (brand/build.py, brand/tokens.json).
// Each size is rendered from the vector file at its own pixel size, so the small ones stay crisp.
import AppKit

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let repo = root.deletingLastPathComponent().deletingLastPathComponent()
let iconset = root.appendingPathComponent("Teyla/Assets.xcassets/AppIcon.appiconset")
let pluginIcon = repo.appendingPathComponent("plugin/.claude-plugin/icon.png")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

let source = repo.appendingPathComponent("brand/icon.svg")
let smallSource = repo.appendingPathComponent("brand/icon-small.svg")
guard let artwork = NSImage(contentsOf: source), let smallArtwork = NSImage(contentsOf: smallSource) else {
    fatalError("Cannot read \(source.path) or \(smallSource.path): run python3 brand/build.py first")
}

/// Renders one master into a square bitmap. The full master (a 1024 canvas, the 824 body at 100) gets the soft
/// drop shadow macOS icons carry; the small-size master (16, 32 and 16@2x px) is pixel-snapped and has none.
func png(pixels: Int, small: Bool) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    let context = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    let ctx = context.cgContext
    let rect = NSRect(x: 0, y: 0, width: pixels, height: pixels)
    if small {
        smallArtwork.draw(in: rect)
    } else {
        ctx.scaleBy(x: CGFloat(pixels) / 1024, y: CGFloat(pixels) / 1024)
        ctx.setShadow(offset: CGSize(width: 0, height: -12), blur: 28, color: CGColor(gray: 0, alpha: 0.35))
        artwork.draw(in: NSRect(x: 0, y: 0, width: 1024, height: 1024))
    }
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

// (points, scale) pairs of the macOS AppIcon set.
let slots: [(Int, Int)] = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2)]
var images: [[String: String]] = []
for (points, scale) in slots {
    let name = "icon_\(points)x\(points)" + (scale == 2 ? "@2x" : "") + ".png"
    // 16, 16@2x and 32 come from the small-size master; 32@2x (64 px) and up from the full one.
    let pixels = points * scale
    try png(pixels: pixels, small: pixels <= 32).write(to: iconset.appendingPathComponent(name))
    images.append(["idiom": "mac", "size": "\(points)x\(points)", "scale": "\(scale)x", "filename": name])
}
let contents: [String: Any] = ["images": images, "info": ["version": 1, "author": "xcode"]]
try JSONSerialization.data(withJSONObject: contents, options: [.prettyPrinted, .sortedKeys])
    .write(to: iconset.appendingPathComponent("Contents.json"))
let catalog: [String: Any] = ["info": ["version": 1, "author": "xcode"]]
try JSONSerialization.data(withJSONObject: catalog, options: [.prettyPrinted, .sortedKeys])
    .write(to: root.appendingPathComponent("Teyla/Assets.xcassets/Contents.json"))
try png(pixels: 1024, small: false).write(to: pluginIcon)
print("Wrote \(slots.count) icons to \(iconset.path) and \(pluginIcon.path)")
