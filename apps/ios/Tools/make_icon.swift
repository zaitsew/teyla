#!/usr/bin/env swift
// Draws the Teyla iPhone app icon: the brand's mark (brand/icon.svg) on the indigo gradient, filling the
// whole 1024 px square. iOS rounds the corners itself, and the App Store refuses an icon with an alpha
// channel, so this writes an opaque PNG.
//
//     swift apps/ios/Tools/make_icon.swift
//
// Colours come from brand/tokens.json ("mark"): icon-top, icon-bottom, on-icon, accent-on-icon. The glyph is
// the same three rounded bars as brand/icon.svg, on the same 64-unit grid.
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let iconset = root.appendingPathComponent("Teyla/Assets.xcassets/AppIcon.appiconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

func color(_ hex: UInt32) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
}

let size = 1024
let space = CGColorSpace(name: CGColorSpace.sRGB)!
guard let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0, space: space,
                          bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { fatalError("no context") }

// SVG coordinates: origin top left.
ctx.translateBy(x: 0, y: CGFloat(size))
ctx.scaleBy(x: 1, y: -1)

let gradient = CGGradient(colorsSpace: space, colors: [color(0x4A5BC0), color(0x2E3C92)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(gradient, start: .zero, end: CGPoint(x: 0, y: CGFloat(size)), options: [])

// The glyph occupies x 9...55 and y 12...52 of a 64-unit grid. Centre it at 512, 512 and scale it so it is as
// large on the full square as it is on the 824 px body of the macOS icon.
let scale: CGFloat = 9 * 1024 / 824
let tx = 512 - 32 * scale
let ty = 512 - 32 * scale
func bar(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat, _ fill: UInt32) {
    let rect = CGRect(x: tx + x * scale, y: ty + y * scale, width: w * scale, height: h * scale)
    ctx.setFillColor(color(fill))
    ctx.addPath(CGPath(roundedRect: rect, cornerWidth: 2.5 * scale, cornerHeight: 2.5 * scale, transform: nil))
    ctx.fillPath()
}
bar(9, 12, 32, 10, 0xFFFFFF)
bar(27, 12, 10, 40, 0xFFFFFF)
bar(45, 12, 10, 17, 0xF2B04B)

let out = iconset.appendingPathComponent("icon-1024.png")
guard let image = ctx.makeImage(),
      let destination = CGImageDestinationCreateWithURL(out as CFURL, UTType.png.identifier as CFString, 1, nil)
else { fatalError("cannot write \(out.path)") }
CGImageDestinationAddImage(destination, image, nil)
guard CGImageDestinationFinalize(destination) else { fatalError("cannot finalize \(out.path)") }

let contents: [String: Any] = [
    "images": [["filename": "icon-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"]],
    "info": ["author": "xcode", "version": 1],
]
try JSONSerialization.data(withJSONObject: contents, options: [.prettyPrinted, .sortedKeys])
    .write(to: iconset.appendingPathComponent("Contents.json"))
print("Wrote \(out.path)")
