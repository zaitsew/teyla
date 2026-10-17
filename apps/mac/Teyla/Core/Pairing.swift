import AppKit
import CoreImage
import CoreImage.CIFilterBuiltins
import Foundation

/// The pairing string that `teyla relay pair` prints: `teyla-pair:v1:<base64url key, no padding>`.
/// The key is 32 bytes, which is 43 base64url characters. The window shows it as a QR code.
enum Pairing {
    static let prefix = "teyla-pair:v1:"

    static func isValid(_ text: String) -> Bool {
        text.range(of: #"^teyla-pair:v1:[A-Za-z0-9_-]{43}$"#, options: .regularExpression) != nil
    }

    /// Finds the pairing string in `teyla relay pair --json` output: any string value of a JSON
    /// object (the key name is not part of the contract), else any token of plain text.
    static func extract(from output: Data) -> String? {
        if let object = try? JSONSerialization.jsonObject(with: output) {
            if let found = strings(in: object).first(where: isValid) { return found }
        }
        let text = String(decoding: output, as: UTF8.self)
        for token in text.split(whereSeparator: { $0.isWhitespace || $0 == "\"" || $0 == "," }) {
            if isValid(String(token)) { return String(token) }
        }
        return nil
    }

    private static func strings(in value: Any) -> [String] {
        if let text = value as? String { return [text] }
        if let dict = value as? [String: Any] { return dict.values.flatMap(strings) }
        if let list = value as? [Any] { return list.flatMap(strings) }
        return []
    }

    /// A crisp QR code: modules are scaled with nearest-neighbour, with a quiet zone around them.
    static func qrImage(for text: String, points: CGFloat = 220) -> NSImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(text.utf8)
        filter.correctionLevel = "M"
        guard let code = filter.outputImage else { return nil }
        let modules = code.extent.width
        let quiet: CGFloat = 4
        let side = modules + 2 * quiet
        let scale = max(1, (points * 2 / side).rounded(.down))   // 2x so it stays sharp on Retina
        let white = CIImage(color: .white).cropped(to: CGRect(x: 0, y: 0, width: side, height: side))
        let padded = code.transformed(by: CGAffineTransform(translationX: quiet, y: quiet)).composited(over: white)
        let scaled = padded.samplingNearest().transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        let context = CIContext(options: [.useSoftwareRenderer: true])
        guard let cg = context.createCGImage(scaled, from: scaled.extent) else { return nil }
        return NSImage(cgImage: cg, size: NSSize(width: CGFloat(cg.width) / 2, height: CGFloat(cg.height) / 2))
    }
}
