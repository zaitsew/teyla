import SwiftUI

// The startup part of a product page (docs/STARTUP.md): the next fact, the ladder, the metrics and the YC line.
// The Mac computes all of it; these views show what it sent. A null figure is a dash with its reason, never 0.

/// The sentence that leads the page, then the earned stage and type, and when the figures were read.
struct StartupSummary: View {
    let startup: PhoneStartup
    let now: Date

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            if let sentence = StartupFormat.nextSentence(startup) {
                Text(sentence)
                    .font(Typo.section)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(StartupFormat.headline(startup))
                .font(Typo.body.weight(.semibold))
                .foregroundStyle(Palette.primary)
                .fixedSize(horizontal: false, vertical: true)
            Text(StartupFormat.asOfLine(startup, now: now))
                .font(Typo.caption)
                .foregroundStyle(startup.stale ? Palette.needsYou : Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if !startup.typeSet {
                Text(StartupFormat.typeNotChosen)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .card()
        .accessibilityElement(children: .combine)
    }
}

/// The ladder: one row per rung, in the Mac's order, with its status in words and a symbol.
struct StartupLadder: View {
    let startup: PhoneStartup

    var body: some View {
        if !startup.rungs.isEmpty {
            VStack(alignment: .leading, spacing: Space.m) {
                SectionHeader(title: "Stage ladder", note: "Each rung is checked on its own.")
                RowGroup {
                    ForEach(startup.rungs) { rung in
                        RungRow(rung: rung, next: startup.next)
                    }
                }
            }
        }
    }
}

private struct RungRow: View {
    let rung: PhoneStartup.Rung
    let next: PhoneStartup.Next?

    private var tone: Color {
        switch rung.status {
        case "met": return Palette.saving
        case "stale": return Palette.needsYou
        case "not_applicable": return Palette.textTertiary
        default: return Palette.textSecondary
        }
    }

    var body: some View {
        let word = StartupFormat.rungWord(rung, next: next)
        HStack(alignment: .firstTextBaseline, spacing: Space.m) {
            Image(systemName: StartupFormat.statusSymbol(rung.status))
                .font(Typo.body)
                .foregroundStyle(tone)
                .frame(width: Space.glyph)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: Space.xxs) {
                Text(rung.title.isEmpty ? rung.id.capitalizedFirst : rung.title)
                    .font(Typo.body.weight(.semibold))
                    .fixedSize(horizontal: false, vertical: true)
                Text(word)
                    .font(Typo.caption.weight(.semibold))
                    .foregroundStyle(tone)
                if !rung.detail.isEmpty {
                    Text(rung.detail)
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, Space.s)
        .frame(minHeight: Space.touchMin)
        .accessibilityElement(children: .combine)
    }
}

/// Marketing, Sales, Usage, Monetization and Growth, one list each.
struct StartupMetricGroups: View {
    let startup: PhoneStartup

    var body: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            ForEach(StartupFormat.groups(startup), id: \.title) { group in
                ConsoleRows(title: group.title, rows: group.rows)
            }
        }
    }
}

/// "2 of 15 boxes" and the next question, for a product that may apply. No percent and no ring: a box means "I can
/// answer this honestly", not "this number is good". The answers are on the Mac.
struct StartupYCLine: View {
    let yc: PhoneStartup.YC

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            SectionHeader(title: "YC application")
            VStack(alignment: .leading, spacing: Space.s) {
                Text(StartupFormat.ycHeadline(yc))
                    .font(Typo.cardTitle)
                if let question = StartupFormat.ycNextQuestion(yc) {
                    Text("Next: \(question)")
                        .font(Typo.body)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Text(StartupFormat.ycOnMac)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .card()
            .accessibilityElement(children: .combine)
        }
    }
}
