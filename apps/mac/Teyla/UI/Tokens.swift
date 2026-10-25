import SwiftUI

// The design tokens for Teyla for Mac. Views use these names and never a literal size, colour
// or gap (templates/design/STANDARD.md, Part 2). Light and dark come from the system colours.

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
    static let wideWindow: CGFloat = 800
    /// The quick-note panel: its size, and how far from the top of the screen it sits (a fraction of the height).
    static let capturePanelWidth: CGFloat = 580
    static let capturePanelHeight: CGFloat = 244
    static let captureTopFraction: CGFloat = 0.16
    /// The quick-note text area.
    static let captureFieldHeight: CGFloat = 72
    /// The shortcut field in Settings.
    static let shortcutFieldWidth: CGFloat = 160
}

enum Radius {
    static let card: CGFloat = 10
    static let panel: CGFloat = 14
}

/// Type: the brief, a lead line, body text and fine print. Hierarchy comes from weight and colour first.
enum Typo {
    static let brief = Font.system(size: 28, weight: .semibold)
    static let lead = Font.system(size: 16, weight: .medium)
    static let body = Font.body
    static let caption = Font.caption
}

/// Colour roles.
enum Palette {
    static let surface = Color(nsColor: .controlBackgroundColor)
    static let border = Color(nsColor: .separatorColor)
    static let background = Color(nsColor: .windowBackgroundColor)
    static let textSecondary = Color.secondary
    static let accent = Color.accentColor
    static let success = Color.green
    static let warning = Color.orange
    static let danger = Color.red
    static let info = Color.blue
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
