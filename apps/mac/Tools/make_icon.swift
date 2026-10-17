#!/usr/bin/env swift
// Draws the Teyla app icon and writes every size into Teyla/Assets.xcassets/AppIcon.appiconset.
//
//     swift apps/mac/Tools/make_icon.swift
//
// The mark: a white speech bubble with one calm dot, on a blue field. No text. Each size is
// drawn from the vector description at its own pixel size, so the small ones stay crisp.
import AppKit

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let iconset = root.appendingPathComponent("Teyla/Assets.xcassets/AppIcon.appiconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

/// The artwork is described on a 1024 point canvas; macOS icons leave a margin of 100 around the body.
func draw(_ ctx: CGContext) {
    let space = CGColorSpaceCreateDeviceRGB()
    let body = CGRect(x: 100, y: 100, width: 824, height: 824)
    let bodyPath = CGPath(roundedRect: body, cornerWidth: 185, cornerHeight: 185, transform: nil)

    // Body, with a soft drop shadow.
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -12), blur: 28, color: CGColor(gray: 0, alpha: 0.35))
    ctx.addPath(bodyPath)
    ctx.setFillColor(CGColor(red: 0.18, green: 0.36, blue: 0.78, alpha: 1))
    ctx.fillPath()
    ctx.restoreGState()

    // Blue gradient, light at the top.
    ctx.saveGState()
    ctx.addPath(bodyPath)
    ctx.clip()
    let colors = [CGColor(red: 0.36, green: 0.55, blue: 0.95, alpha: 1),
                  CGColor(red: 0.16, green: 0.31, blue: 0.72, alpha: 1)] as CFArray
    let gradient = CGGradient(colorsSpace: space, colors: colors, locations: [0, 1])!
    ctx.drawLinearGradient(gradient, start: CGPoint(x: 512, y: 924), end: CGPoint(x: 512, y: 100), options: [])
    ctx.restoreGState()

    // The bubble: a rounded rectangle with a small tail at the lower left.
    let bubble = CGRect(x: 236, y: 372, width: 552, height: 392)
    let path = CGMutablePath()
    path.addRoundedRect(in: bubble, cornerWidth: 120, cornerHeight: 120)
    path.move(to: CGPoint(x: 330, y: 392))
    path.addLine(to: CGPoint(x: 300, y: 262))
    path.addLine(to: CGPoint(x: 452, y: 380))
    path.closeSubpath()
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -8), blur: 16, color: CGColor(gray: 0, alpha: 0.18))
    ctx.addPath(path)
    ctx.setFillColor(CGColor(gray: 1, alpha: 0.97))
    ctx.fillPath()
    ctx.restoreGState()

    // One dot in the middle of the bubble.
    ctx.setFillColor(CGColor(red: 0.20, green: 0.38, blue: 0.82, alpha: 1))
    ctx.fillEllipse(in: CGRect(x: 512 - 58, y: 568 - 58, width: 116, height: 116))
}

func png(pixels: Int) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    let context = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.cgContext.scaleBy(x: CGFloat(pixels) / 1024, y: CGFloat(pixels) / 1024)
    draw(context.cgContext)
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

// (points, scale) pairs of the macOS AppIcon set.
let slots: [(Int, Int)] = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2)]
var images: [[String: String]] = []
for (points, scale) in slots {
    let name = "icon_\(points)x\(points)" + (scale == 2 ? "@2x" : "") + ".png"
    try png(pixels: points * scale).write(to: iconset.appendingPathComponent(name))
    images.append(["idiom": "mac", "size": "\(points)x\(points)", "scale": "\(scale)x", "filename": name])
}
let contents: [String: Any] = ["images": images, "info": ["version": 1, "author": "xcode"]]
try JSONSerialization.data(withJSONObject: contents, options: [.prettyPrinted, .sortedKeys])
    .write(to: iconset.appendingPathComponent("Contents.json"))
let catalog: [String: Any] = ["info": ["version": 1, "author": "xcode"]]
try JSONSerialization.data(withJSONObject: catalog, options: [.prettyPrinted, .sortedKeys])
    .write(to: root.appendingPathComponent("Teyla/Assets.xcassets/Contents.json"))
print("Wrote \(slots.count) icons to \(iconset.path)")
