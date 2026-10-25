import AppKit
import SwiftUI

// The design tokens for Teyla for Mac. Views use these names and never a literal size, colour
// or gap (templates/design/STANDARD.md, Part 2). The colours mirror brand/tokens.json, the single
// source; tests/test_brand.py fails when the two differ. Each role carries its light and dark value.

/// Spacing on a 4-based scale.
enum Space {
    static let xxs: CGFloat = 2
    static let xs: CGFloat = 4
    static let s: CGFloat = 8
    static let m: CGFloat = 12
    static let l: CGFloat = 16
    static let xl: CGFloat = 24
    static let xxl: CGFloat = 32
    /// The width of the products and running column.
    static let sideColumn: CGFloat = 340
    /// The width of the menu-bar popover.
    static let menuWidth: CGFloat = 320
    /// Width at which the window shows two columns.
    static let wideWindow: CGFloat = 880
    /// The quick-note panel: its size, and how far from the top of the screen it sits (a fraction of the height).
    static let capturePanelWidth: CGFloat = 580
    static let capturePanelHeight: CGFloat = 244
    static let captureTopFraction: CGFloat = 0.16
    /// The quick-note text area.
    static let captureFieldHeight: CGFloat = 72
    /// The shortcut field in Settings.
    static let shortcutFieldWidth: CGFloat = 160
    /// The sidebar: Today, Diagnosis and the products.
    static let sidebarMin: CGFloat = 190
    static let sidebarIdeal: CGFloat = 220
    static let sidebarMax: CGFloat = 280
    /// The line length of the welcome, the not-found screen and the diagnosis.
    static let readingWidth: CGFloat = 560
    /// The lockup on the welcome and not-found screens, and the mark in the sidebar header.
    static let lockupHeight: CGFloat = 48
    static let markSize: CGFloat = 24
}

enum Radius {
    static let card: CGFloat = 10
    static let panel: CGFloat = 14
}

/// Type: the brief, a lead line, body text and fine print. Hierarchy comes from weight and colour first.
enum Typo {
    static let brief = Font.system(size: 28, weight: .semibold)
    /// The one big number on the diagnosis.
    static let display = Font.system(size: 40, weight: .semibold)
    static let lead = Font.system(size: 16, weight: .medium)
    static let body = Font.body
    static let caption = Font.caption
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

    // The names views already use, mapped onto the brand roles.
    static let accent = primary
    static let info = primary
    static let warning = needsYou
    static let success = saving
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
                    .strokeBorder(highlighted ? Palette.accent : Palette.border, lineWidth: highlighted ? 2 : 1)
            )
    }
}

extension View {
    func card(highlighted: Bool = false) -> some View {
        modifier(CardBackground(highlighted: highlighted))
    }
}

/// A small coloured label: a status on a result card, a state on a product.
struct Chip: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .font(Typo.caption.weight(.medium))
            .padding(.horizontal, Space.s)
            .padding(.vertical, Space.xxs)
            // The text leans toward the primary colour so it stays readable on the pale tint, in light and dark.
            .foregroundStyle(color.mix(with: .primary, by: 0.35))
            .background(color.opacity(0.16), in: Capsule())
            .fixedSize()
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
