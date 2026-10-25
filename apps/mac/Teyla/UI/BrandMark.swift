import SwiftUI

/// The Teyla mark (brand/mark.svg): a T and a block, the block amber. The two colours follow the appearance.
/// The amber is a logo-only colour, brighter in light mode than the "needs you" text colour (brand/tokens.json,
/// color.mark), so it lives here and not among the roles in Tokens.swift.
enum BrandColor {
    static let markAmber = Color(light: 0xC9740A, dark: 0xF2B04B)
}

struct BrandMark: View {
    var size: CGFloat = Space.markSize

    var body: some View {
        // The mark is drawn on a 64-unit grid; `u` is one unit.
        let u = size / 64
        ZStack(alignment: .topLeading) {
            bar(x: 9, y: 12, width: 32, height: 10, color: Palette.primary, u: u)
            bar(x: 27, y: 12, width: 10, height: 40, color: Palette.primary, u: u)
            bar(x: 45, y: 12, width: 10, height: 17, color: BrandColor.markAmber, u: u)
        }
        .frame(width: size, height: size, alignment: .topLeading)
        .accessibilityLabel("Teyla")
    }

    private func bar(x: CGFloat, y: CGFloat, width: CGFloat, height: CGFloat, color: Color, u: CGFloat) -> some View {
        RoundedRectangle(cornerRadius: 2.5 * u)
            .fill(color)
            .frame(width: width * u, height: height * u)
            .offset(x: x * u, y: y * u)
    }
}

/// The mark and the wordmark (brand/lockup.svg), from the asset catalog, which carries the dark variant.
struct BrandLockup: View {
    var height: CGFloat = Space.lockupHeight

    var body: some View {
        Image("Lockup")
            .resizable()
            .scaledToFit()
            .frame(height: height)
            .accessibilityLabel("Teyla")
    }
}
