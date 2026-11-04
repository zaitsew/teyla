import SwiftUI

// The visual grammar of Teyla: every page of the Mac and iPhone apps is built from these pieces.
// The iPhone target compiles this file by path, so both apps show one design. It depends only on SwiftUI and on
// the tokens, which have the same names in each app. Product icons differ per platform, so they come in as views.
// How to use them: apps/mac/README.md, "The visual grammar".

extension EnvironmentValues {
    /// True when a `Page` draws without its scroll view, so a screenshot can hold all of it.
    @Entry var pageFlat = false
}

// MARK: A page

/// The scaffold of a page: the scroll view, the gutter, the column and the gap between blocks.
struct Page<Content: View>: View {
    var maxWidth: CGFloat = Space.pageMax
    @ViewBuilder var content: Content
    @Environment(\.pageFlat) private var flat

    var body: some View {
        if flat {
            column
        } else {
            ScrollView { column }
                .background(Palette.background)
        }
    }

    /// An eager stack on purpose: `scrollTo` can only reach a card that exists, and a notification opens
    /// a question far down the page.
    private var column: some View {
        VStack(alignment: .leading, spacing: Space.xl) { content }
            .padding(.horizontal, Space.page)
            .padding(.vertical, Space.xl)
            .frame(maxWidth: maxWidth, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.background)
    }
}

/// The title of a page and one line of context. A control may sit at its right edge.
struct PageHeader<Trailing: View>: View {
    let title: String
    var context = ""
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.m) {
            VStack(alignment: .leading, spacing: Space.xxs) {
                Text(title)
                    .font(Typo.pageTitle)
                    .lineLimit(1)
                    .accessibilityAddTraits(.isHeader)
                if !context.isEmpty {
                    Text(context)
                        .font(Typo.body)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: Space.m)
            trailing
        }
    }
}

extension PageHeader where Trailing == EmptyView {
    init(title: String, context: String = "") {
        self.init(title: title, context: context) { EmptyView() }
    }
}

/// The title of a block, the rule that says what is in it, and how many.
struct SectionHeader<Trailing: View>: View {
    let title: String
    var note = ""
    var count: Int?
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.m) {
            VStack(alignment: .leading, spacing: Space.xxs) {
                HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                    Text(title)
                        .font(Typo.section)
                        .lineLimit(1)
                        .accessibilityAddTraits(.isHeader)
                    if let count {
                        Text("\(count)")
                            .font(Typo.body)
                            .foregroundStyle(Palette.textSecondary)
                            .monospacedDigit()
                    }
                }
                if !note.isEmpty {
                    Text(note)
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: Space.m)
            trailing
        }
    }
}

extension SectionHeader where Trailing == EmptyView {
    init(title: String, note: String = "", count: Int? = nil) {
        self.init(title: title, note: note, count: count) { EmptyView() }
    }
}

// MARK: Surfaces

extension View {
    /// The surface of a card or a row group: a quiet fill and a hairline, the same on every page.
    func surface(radius: CGFloat = Radius.card, padding: CGFloat = Space.l, highlighted: Bool = false) -> some View {
        self
            .padding(padding)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(highlighted ? Palette.primary : Palette.border,
                                  lineWidth: highlighted ? Space.xxs : Space.hairline)
            )
            .contentShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
    }
}

// MARK: Numbers

extension StatTone {
    var color: Color {
        switch self {
        case .neutral: return Palette.text
        case .needsYou: return Palette.needsYou
        case .danger: return Palette.danger
        case .saving: return Palette.saving
        }
    }
}

/// One figure in a tile: what it counts, the number, one small line. No number shows a dash, never a made-up zero;
/// then `detail` says why.
struct StatTile: View {
    let label: String
    let value: String?
    var detail = ""
    var tone = StatTone.neutral
    var action: (() -> Void)?

    var body: some View {
        if let action {
            Button(action: action) { tile }
                .buttonStyle(.plain)
                .accessibilityAddTraits(.isButton)
        } else {
            tile
        }
    }

    private var tile: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            Text(label)
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(1)
            Text(value ?? Format.dash)
                .font(Typo.number)
                .foregroundStyle(value == nil ? Palette.textTertiary : tone.color)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            Text(detail.isEmpty ? " " : detail)
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(2, reservesSpace: true)
                .help(detail)
        }
        .surface(padding: Space.m)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(label): \(value ?? "unknown"). \(detail)")
    }
}

/// Tiles in equal columns that fill the width, and wrap when they no longer fit.
/// A short last row shares the whole width, so it never leaves a hole.
struct StatStrip<Content: View>: View {
    @ViewBuilder var content: Content
    @State private var width: CGFloat = Space.pageMax

    var body: some View {
        Group(subviews: content) { tiles in
            let fit = Int((width + Space.m) / Space.statTileStep)
            let perRow = max(1, min(tiles.count, fit))
            VStack(alignment: .leading, spacing: Space.m) {
                ForEach(Array(stride(from: 0, to: tiles.count, by: perRow)), id: \.self) { start in
                    HStack(alignment: .top, spacing: Space.m) {
                        ForEach(tiles[start..<min(start + perRow, tiles.count)]) { $0 }
                    }
                    .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .onGeometryChange(for: CGFloat.self, of: \.size.width) { width = $0 }
    }
}

/// A few options, one chosen: Week / Month / Year, All / Needs attention. One look on every page.
struct SegmentSwitch<Value: Hashable>: View {
    let options: [(value: Value, label: String)]
    @Binding var selection: Value
    var spokenLabel = ""
    /// True where the segments share the whole width, as on a phone.
    var fills = false

    var body: some View {
        HStack(spacing: Space.xxs) {
            ForEach(options, id: \.value) { option in
                let chosen = option.value == selection
                Button {
                    selection = option.value
                } label: {
                    Text(option.label)
                        .font(Typo.body.weight(.semibold))
                        .foregroundStyle(chosen ? Palette.text : Palette.textSecondary)
                        .lineLimit(1)
                        .padding(.horizontal, Space.l)
                        .frame(maxWidth: fills ? .infinity : nil, minHeight: Space.controlMin)
                        .background(chosen ? Palette.selectedSegment : Color.clear,
                                    in: RoundedRectangle(cornerRadius: Radius.control))
                        .contentShape(RoundedRectangle(cornerRadius: Radius.control))
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(chosen ? .isSelected : [])
            }
        }
        .padding(Space.xs)
        .background(Palette.track, in: RoundedRectangle(cornerRadius: Radius.card))
        .fixedSize(horizontal: !fills, vertical: false)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(spokenLabel)
    }
}

/// A number and what it counts, for the numbers row of a `Scorecard`.
struct ScoreNumber: Identifiable {
    let value: String?
    let label: String
    var id: String { label }
}

/// A product, or anything with a score: who it is, a row of numbers, and a footer.
struct Scorecard<Icon: View, Footer: View>: View {
    let title: String
    var badge = ""
    var summary = ""
    let numbers: [ScoreNumber]
    @ViewBuilder var icon: Icon
    @ViewBuilder var footer: Footer

    var body: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            HStack(alignment: .top, spacing: Space.m) {
                icon
                VStack(alignment: .leading, spacing: Space.xxs) {
                    HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                        Text(title).font(Typo.section).lineLimit(1)
                        if !badge.isEmpty {
                            Text(badge).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
                        }
                    }
                    if !summary.isEmpty {
                        Text(summary)
                            .font(Typo.body)
                            .foregroundStyle(Palette.textSecondary)
                            .lineLimit(2, reservesSpace: true)
                            .help(summary)
                    }
                }
            }
            HStack(alignment: .top, spacing: Space.m) {
                ForEach(numbers) { number in
                    VStack(alignment: .leading, spacing: Space.xxs) {
                        Text(number.value ?? Format.dash)
                            .font(Typo.number)
                            .foregroundStyle(number.value == nil ? Palette.textTertiary : Palette.text)
                            .lineLimit(1)
                            .minimumScaleFactor(0.6)
                        Text(number.label)
                            .font(Typo.caption)
                            .foregroundStyle(Palette.textSecondary)
                            .lineLimit(1)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            Spacer(minLength: 0)
            Divider()
            footer
        }
        .surface(radius: Radius.panel)
    }
}

/// Commits per week as small bars; the newest week stands out. Nothing is drawn for a product with no weeks.
struct SparklineView: View {
    let heights: [Double]
    let label: String
    var height = Space.sparkCardHeight
    var barWidth = Space.sparkCardBar

    var body: some View {
        HStack(alignment: .bottom, spacing: Space.xxs) {
            ForEach(heights.indices, id: \.self) { index in
                RoundedRectangle(cornerRadius: Radius.bar)
                    .fill(color(index))
                    .frame(width: barWidth, height: max(Space.xxs, height * heights[index]))
            }
        }
        .frame(height: height, alignment: .bottom)
        .accessibilityElement()
        .accessibilityLabel(label)
    }

    private func color(_ index: Int) -> Color {
        if index == heights.count - 1 { return Palette.primary }
        return heights[index] > 0 ? Palette.primaryMuted : Palette.border
    }
}

// MARK: Rows

/// One line of a list: a leading view, a title, a line of detail, a trailing view. One line each, and the full
/// text sits in the tooltip and on the page the row opens.
struct RowCard<Leading: View, Trailing: View>: View {
    let title: String
    var detail = ""
    /// True where the words may run over several lines (a phone), so none is cut off. The default is one line each.
    var wraps = false
    @ViewBuilder var leading: Leading
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(spacing: Space.m) {
            leading
            VStack(alignment: .leading, spacing: Space.xxs) {
                Text(title)
                    .font(Typo.body.weight(.semibold))
                    .lineLimit(wraps ? nil : 1)
                    .fixedSize(horizontal: false, vertical: wraps)
                    .help(title)
                if !detail.isEmpty {
                    Text(detail)
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(wraps ? nil : 1)
                        .fixedSize(horizontal: false, vertical: wraps)
                        .help(detail)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            trailing
        }
        .frame(minHeight: Space.touchMin)
        .contentShape(Rectangle())
    }
}

extension RowCard where Leading == EmptyView {
    init(title: String, detail: String = "", wraps: Bool = false, @ViewBuilder trailing: () -> Trailing) {
        self.init(title: title, detail: detail, wraps: wraps, leading: { EmptyView() }, trailing: trailing)
    }
}

/// Rows on one surface, with a line between them.
struct RowGroup<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Group(subviews: content) { rows in
                ForEach(rows.indices, id: \.self) { index in
                    rows[index]
                    if index < rows.count - 1 { Divider() }
                }
            }
        }
        .padding(.horizontal, Space.l)
        .padding(.vertical, Space.xs)
        .surface(padding: 0)
    }
}

// MARK: Nothing to show, and failures

/// What a block says when it holds nothing: what is missing and the next step, in at most two sentences.
struct EmptyState: View {
    var symbol = "checkmark.circle"
    let title: String
    var detail = ""
    var actionTitle = ""
    var action: (() -> Void)?

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.s) {
            Image(systemName: symbol)
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .frame(width: Space.glyph)
            VStack(alignment: .leading, spacing: Space.xxs) {
                Text(title).font(Typo.body)
                if !detail.isEmpty {
                    Text(detail)
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: Space.s)
            if let action, !actionTitle.isEmpty {
                Button(actionTitle, action: action)
            }
        }
        .padding(.vertical, Space.s)
    }
}

/// A block that failed to load: it names the block and says why, so the rest of the page keeps working.
struct ErrorRow: View {
    let section: String
    let message: String
    var retry: (() -> Void)?

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.s) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(Typo.body)
                .foregroundStyle(Palette.danger)
                .frame(width: Space.glyph)
            VStack(alignment: .leading, spacing: Space.xxs) {
                Text("Could not read \(section)").font(Typo.body.weight(.semibold))
                ClampedText(text: message, lines: 2, font: Typo.caption)
            }
            Spacer(minLength: Space.s)
            if let retry { Button("Try again", action: retry) }
        }
        .surface(padding: Space.m)
        .accessibilityElement(children: .combine)
    }
}

// MARK: Long text

/// Text that stops after `lines` and offers the rest. Use it for anything a person or a model wrote, outside a row
/// that opens a page, so nothing runs on or gets cut off for good.
struct ClampedText: View {
    let text: String
    var lines = 3
    var font = Typo.body
    var color = Palette.textSecondary
    @State private var open = false
    @State private var fullHeight: CGFloat = 0
    @State private var shownHeight: CGFloat = 0

    private var cut: Bool { fullHeight > shownHeight + Space.hairline }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            Text(text)
                .font(font)
                .foregroundStyle(color)
                .lineLimit(open ? nil : lines)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { shownHeight = $0 }
                .background(alignment: .topLeading) {
                    Text(text)
                        .font(font)
                        .fixedSize(horizontal: false, vertical: true)
                        .hidden()
                        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { fullHeight = $0 }
                }
            if cut || open {
                Button(open ? "Less" : "More") { open.toggle() }
                    .buttonStyle(.plain)
                    .font(Typo.caption.weight(.medium))
                    .foregroundStyle(Palette.primary)
            }
        }
    }
}
