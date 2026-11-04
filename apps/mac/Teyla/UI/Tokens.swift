import AppKit
import SwiftUI

// The design tokens for Teyla for Mac. Views use these names and never a literal size, colour
// or gap (templates/design/STANDARD.md, Part 2). The colours mirror brand/tokens.json, the single
// source; tests/test_brand.py fails when the two differ. Each role carries its light and dark value.

/// Spacing on a 4-based scale. Views use a step as it is: `Space.xs + Space.xxs` is not a gap.
enum Space {
    static let xxs: CGFloat = 2
    static let xs: CGFloat = 4
    static let s: CGFloat = 8
    static let m: CGFloat = 12
    static let l: CGFloat = 16
    static let xl: CGFloat = 24
    static let xxl: CGFloat = 32
    /// The gutter of every page.
    static let page: CGFloat = 28
    /// The line under a card, a row or a field.
    static let hairline: CGFloat = 1
    /// A status dot.
    static let dot: CGFloat = 6
    /// The column a symbol takes beside a line of text, so the text after it aligns.
    static let glyph: CGFloat = 20
    /// A round icon button.
    static let iconButton: CGFloat = 28
    /// The width of the side column on a product page.
    static let sideColumn: CGFloat = 340
    /// How far the side column may grow when the window is wide: the extra room goes here, not to the cards.
    static let sideColumnMax: CGFloat = 480
    /// A hero card on Home is at least this wide; the grid fits 1 to 3 in a row.
    static let heroCardMin: CGFloat = 320
    /// A "Being built" card is at least this wide.
    static let builtCardMin: CGFloat = 300
    /// A wide page stops here, so three cards in a row stay readable.
    static let pageMax: CGFloat = 1100
    /// A reading page stops here: `readingCard` and the gutter on each side.
    static let readingPage: CGFloat = 776
    /// A `StatTile` is at least this wide; the strip fits as many as the page has room for.
    static let statTileMin: CGFloat = 150
    /// The tap area of the star on a product.
    static let starTarget: CGFloat = 24
    /// The least height of anything a person presses (a switch segment, a row).
    static let touchMin: CGFloat = 44
    /// A segment inside a switch whose track carries the rest of `touchMin`.
    static let controlMin: CGFloat = 36
    /// Product icons on Home: hero card, "Being built" card, "Quiet" row.
    static let iconHero: CGFloat = 56
    static let iconCard: CGFloat = 44
    static let iconRow: CGFloat = 30
    /// The commits-per-week bars: height and width on a hero card, and on a card.
    static let sparkHeroHeight: CGFloat = 34
    static let sparkHeroBar: CGFloat = 7
    static let sparkCardHeight: CGFloat = 18
    static let sparkCardBar: CGFloat = 3
    /// The product name column of a Quiet row.
    static let quietName: CGFloat = 160
    /// Ask cards, done cards, task rows and prose stop here (45 to 75 characters a line).
    static let readingCard: CGFloat = 720
    /// The figures column on a Portfolio row.
    static let portfolioFigures: CGFloat = 220
    /// The width of the menu-bar popover.
    static let menuWidth: CGFloat = 320
    /// Width at which a product page shows two columns.
    static let wideWindow: CGFloat = 880
    /// The quick-note panel: its size, and how far from the top of the screen it sits (a fraction of the height).
    static let capturePanelWidth: CGFloat = 580
    static let capturePanelHeight: CGFloat = 244
    static let captureTopFraction: CGFloat = 0.16
    /// The quick-note text area.
    static let captureFieldHeight: CGFloat = 72
    /// The shortcut field in Settings.
    static let shortcutFieldWidth: CGFloat = 160
    /// The ⌘K command bar.
    static let commandBarWidth: CGFloat = 560
    static let commandBarList: CGFloat = 320
    /// The most height a preview's output takes on a Tools card before it scrolls.
    static let previewMax: CGFloat = 180
    /// The sidebar: Home, Decisions, All products and Tools.
    static let sidebarMin: CGFloat = 190
    static let sidebarIdeal: CGFloat = 220
    static let sidebarMax: CGFloat = 280
    /// The line length of the welcome, the not-found screen and the diagnosis.
    static let readingWidth: CGFloat = 560
    /// The pairing QR code in the "Connect iPhone" sheet, large enough for a phone held at arm's length.
    static let qrCode: CGFloat = 280
    /// The width of the "Connect iPhone" sheet.
    static let sheetWidth: CGFloat = 440
    /// The lockup on the welcome and not-found screens, and the mark in the sidebar header.
    static let lockupHeight: CGFloat = 48
    static let markSize: CGFloat = 24
    /// The confirmation inside a diagnosis.
    static let confirmSheet: CGFloat = 528
    /// The Settings window and the new-task sheet.
    static let settingsWidth: CGFloat = 460
    static let taskSheetWidth: CGFloat = 520
    /// The main window never gets smaller than this.
    static let windowMinWidth: CGFloat = 760
    static let windowMinHeight: CGFloat = 460
    static let windowDefaultWidth: CGFloat = 1180
    static let windowDefaultHeight: CGFloat = 760
}

enum Radius {
    /// A button, a field, a switch segment: anything inside a card.
    static let control: CGFloat = 8
    static let card: CGFloat = 10
    static let panel: CGFloat = 14
    /// A product icon, by size: hero, card, row.
    static let iconHero: CGFloat = 13
    static let iconCard: CGFloat = 10
    static let iconRow: CGFloat = 7
    /// A bar of the commits chart.
    static let bar: CGFloat = 2
}

/// Type: exactly five levels, plus one style for big numbers. A view picks a level and may change its
/// weight; it never sets a size. `tests/test_app_design_tokens.py` fails on anything else.
enum Typo {
    /// One per page, in `PageHeader`.
    static let pageTitle = Font.system(size: 26, weight: .semibold)
    /// A block on a page, in `SectionHeader`.
    static let section = Font.system(size: 17, weight: .semibold)
    /// The name of a card, a row or a product.
    static let cardTitle = Font.system(size: 14, weight: .semibold)
    /// Reading text.
    static let body = Font.system(size: 13)
    /// A label, a fact under a title, a figure's unit.
    static let caption = Font.system(size: 12)
    /// A big figure: the value of a `StatTile` or a `Scorecard`. Digits share one width, so columns align.
    static let number = Font.system(size: 26, weight: .semibold).monospacedDigit()

    /// A command or a tool's output: `caption`'s size in the monospaced face. Not a sixth level.
    static let code = Font.system(size: 12, design: .monospaced)
    /// The letter on a product with no icon scales with the tile, like the icon it stands in for.
    static func monogram(side: CGFloat) -> Font { Font.system(size: side * 0.42, weight: .bold) }
    /// The text field of a note, in AppKit: `body` plus room to write.
    @MainActor static var noteField: NSFont { NSFont.systemFont(ofSize: 15) }
}

/// Symbols that stand alone. A symbol beside text takes the font of its text instead.
enum Glyph {
    /// The one large symbol of an empty or error screen.
    static let empty = Font.system(size: 40)
    /// The microphone in the note field.
    static let mic = Font.system(size: 20)
    /// The dot of a bulleted line.
    static let bullet = Font.system(size: 5)
}

/// Colour roles, from brand/tokens.json. Amber means "waiting on you" and green means money saved,
/// everywhere; neither is decoration.
enum Palette {
    static let background = Color(light: 0xF7F7F9, dark: 0x0E1015)
    static let surface = Color(light: 0xFFFFFF, dark: 0x171A21)
    static let border = Color(light: 0xDCDEE5, dark: 0x2B2F3A)
    static let text = Color(light: 0x14161D, dark: 0xECEDF2)
    static let textSecondary = Color(light: 0x585E6D, dark: 0xA2A7B5)
    static let primary = Color(light: 0x3A4AA8, dark: 0x9AA7F2)
    static let onPrimary = Color(light: 0xFFFFFF, dark: 0x0E1015)
    static let needsYou = Color(light: 0xA65400, dark: 0xF2B04B)
    static let saving = Color(light: 0x13734A, dark: 0x4CC98A)
    static let danger = Color(light: 0xB42318, dark: 0xF87166)

    /// Tints of the roles above: a letter tile, the older bars of a chart, the track of a segmented switch.
    static let primaryTint = primary.opacity(0.14)
    static let primaryMuted = primary.opacity(0.35)
    static let dangerTint = danger.opacity(0.14)
    static let track = border.opacity(0.55)
    /// Fine print a reader can skip, and a control that is off.
    static let textTertiary = textSecondary.opacity(0.7)
}

extension Color {
    /// A colour that follows the window's appearance: `light` in Aqua, `dark` in Dark Aqua. Values are sRGB hex.
    init(light: UInt32, dark: UInt32) {
        self.init(nsColor: NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
            let hex = isDark ? dark : light
            return NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                           blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
        })
    }
}

/// A card: a quiet surface with a hairline border. `highlighted` marks the card a notification pointed at.
struct CardBackground: ViewModifier {
    var highlighted = false

    func body(content: Content) -> some View {
        content
            .padding(Space.l)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: Radius.card))
            .overlay(
                RoundedRectangle(cornerRadius: Radius.card)
                    .strokeBorder(highlighted ? Palette.primary : Palette.border, lineWidth: highlighted ? Space.xxs : Space.hairline)
            )
    }
}

extension View {
    func card(highlighted: Bool = false) -> some View {
        modifier(CardBackground(highlighted: highlighted))
    }
}

/// A small coloured label: a status on a result card, a state on a product. With a symbol it never
/// relies on colour alone.
struct Chip: View {
    let text: String
    let color: Color
    var symbol: String?

    var body: some View {
        HStack(spacing: Space.xs) {
            if let symbol { Image(systemName: symbol).imageScale(.small) }
            Text(text)
        }
        .font(Typo.caption.weight(.medium))
        .padding(.horizontal, Space.s)
        .padding(.vertical, Space.xxs)
        // The text leans toward the primary colour so it stays readable on the pale tint, in light and dark.
        .foregroundStyle(color.mix(with: Palette.text, by: 0.35))
        .background(color.opacity(0.16), in: Capsule())
        .fixedSize()
    }
}

extension View {
    /// Stops a card or a line of prose at the reading width, left-aligned.
    func readingWidth() -> some View {
        frame(maxWidth: Space.readingCard, alignment: .leading)
    }
}

struct SectionLabel: View {
    let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text)
            .font(Typo.body.weight(.semibold))
            .foregroundStyle(Palette.textSecondary)
            .padding(.bottom, Space.xs)
    }
}
