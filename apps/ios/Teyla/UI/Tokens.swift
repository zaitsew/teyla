import SwiftUI
import UIKit

// The design tokens for Teyla for iPhone: the names of the Mac's tokens, the values of a phone.
// Views use these names and never a literal size, colour or gap (templates/design/STANDARD.md, Part 2).
// The colours mirror brand/tokens.json; tests/test_brand.py fails when they differ.

/// Spacing on a 4-based scale. Views use a step as it is.
enum Space {
    static let xxs: CGFloat = 2
    static let xs: CGFloat = 4
    static let s: CGFloat = 8
    static let m: CGFloat = 12
    static let l: CGFloat = 16
    static let xl: CGFloat = 24
    static let xxl: CGFloat = 32
    /// The gutter of every page.
    static let page: CGFloat = 16
    static let hairline: CGFloat = 1
    /// A status dot.
    static let dot: CGFloat = 6
    /// The column a symbol takes beside a line of text, so the text after it aligns.
    static let glyph: CGFloat = 20
    /// The numbered circle of a setup step.
    static let stepBadge: CGFloat = 28
    /// Cards and prose stop here on an iPad, so a line stays readable.
    static let readingCard: CGFloat = 640
    /// The least height of anything a person presses.
    static let touchMin: CGFloat = 44
    /// Product icons on Home: hero card, "Being built" row, "Quiet" row.
    static let iconHero: CGFloat = 48
    static let iconCard: CGFloat = 34
    static let iconRow: CGFloat = 26
    /// The commits-per-week bars: height and width on a hero card, and on a row.
    static let sparkHeroHeight: CGFloat = 28
    static let sparkHeroBar: CGFloat = 5
    static let sparkCardHeight: CGFloat = 18
    static let sparkCardBar: CGFloat = 3
    /// A page stops here on an iPad.
    static let pageMax: CGFloat = 640
    /// A `StatTile` is at least this wide, so two fit a phone.
    static let statTileMin: CGFloat = 150
}

enum Radius {
    /// A button, a field, a switch segment: anything inside a card.
    static let control: CGFloat = 8
    static let card: CGFloat = 12
    static let panel: CGFloat = 16
    /// A product icon, by size: hero, card, row.
    static let iconHero: CGFloat = 11
    static let iconCard: CGFloat = 8
    static let iconRow: CGFloat = 6
    /// A bar of the commits chart.
    static let bar: CGFloat = 2
}

/// Type: exactly five levels, plus one style for big numbers, all following Dynamic Type. A view picks
/// a level and may change its weight; it never sets a size. `tests/test_app_design_tokens.py` fails on anything else.
enum Typo {
    /// One per page.
    static let pageTitle = Font.title.bold()
    /// A block on a page.
    static let section = Font.title3.weight(.semibold)
    /// The name of a card, a row or a product.
    static let cardTitle = Font.headline
    /// Reading text.
    static let body = Font.subheadline
    /// A label, a fact under a title, a figure's unit.
    static let caption = Font.footnote
    /// A big figure. Digits share one width, so columns align.
    static let number = Font.title.weight(.semibold).monospacedDigit()

    /// A command or a tool's output: `caption` in the monospaced face. Not a sixth level.
    static let code = Font.system(.footnote, design: .monospaced)
    /// The letter on a product with no icon scales with the tile, like the icon it stands in for.
    static func monogram(side: CGFloat) -> Font { Font.system(size: side * 0.44, weight: .bold) }
}

/// Symbols that stand alone. A symbol beside text takes the font of its text instead.
enum Glyph {
    /// The one large symbol of an empty or error screen.
    static let empty = Font.system(size: 40)
    /// The microphone in a text field.
    static let mic = Font.system(size: 20)
    /// The language code on the microphone.
    static let badge = Font.system(size: 9, weight: .bold)
}

/// Colour roles, from brand/tokens.json. Amber means "waiting on you" and green means money saved,
/// everywhere; neither is decoration.
enum Palette {
    static let background = Color(uiColor: .systemGroupedBackground)
    static let surface = Color(uiColor: .secondarySystemGroupedBackground)
    static let text = Color(uiColor: .label)
    static let textSecondary = Color(uiColor: .secondaryLabel)
    static let textTertiary = Color(uiColor: .tertiaryLabel)
    static let border = Color(uiColor: .quaternarySystemFill)
    static let track = Color(uiColor: .tertiarySystemFill)
    static let primary = Color.brand(light: 0x3A4AA8, dark: 0x9AA7F2)
    static let onPrimary = Color.brand(light: 0xFFFFFF, dark: 0x0E1015)
    static let needsYou = Color.brand(light: 0xA65400, dark: 0xF2B04B)
    static let saving = Color.brand(light: 0x13734A, dark: 0x4CC98A)
    static let danger = Color.brand(light: 0xB42318, dark: 0xF87166)

    /// Tints of the roles above: a letter tile, the older bars of a chart, a chip.
    static let primaryTint = primary.opacity(0.14)
    static let primaryMuted = primary.opacity(0.35)
    static let dangerTint = danger.opacity(0.14)
    /// The selected segment of a switch: white in light, a lifted grey in dark.
    static let selectedSegment = Color.brand(light: 0xFFFFFF, dark: 0x3A3A3C)
    /// A control laid over the camera.
    static let scrim = Color.black.opacity(0.6)
}

extension Color {
    /// A colour that follows the appearance. Values are sRGB hex.
    static func brand(light: UInt32, dark: UInt32) -> Color {
        Color(uiColor: UIColor { traits in
            let hex = traits.userInterfaceStyle == .dark ? dark : light
            return UIColor(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                           blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
        })
    }
}

/// A chip's tint for any status colour.
extension Color {
    var chipTint: Color { opacity(0.14) }
}
