import SwiftUI

/// The startup page of one product (docs/STARTUP.md): the stage the evidence shows, the one fact it is missing, the ladder
/// and the metrics in five groups. The CLI decides all of it; this view shows what comes back. A figure the CLI does not
/// know is a dash with the reason. Nothing here suggests closing a product: zero sale attempts reads "not tried yet".
struct ProductStartupSection: View {
    @Environment(AppModel.self) private var model
    let productID: String
    let title: String
    let portfolio: PortfolioProduct?

    var body: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            SectionHeader(title: "Startup", note: "The stage the evidence shows, and the next fact it is missing.")
            if let block = portfolio?.startup {
                StartupHead(productID: productID, block: block)
                StartupLadder(block: block)
                StartupMetricGroups(block: block)
                StartupYCRow(productID: productID, title: title, block: block)
            } else {
                EmptyState(symbol: "questionmark.circle",
                           title: portfolio == nil ? "The portfolio report has not loaded."
                                                   : "The startup facts are not available for this product.",
                           detail: portfolio == nil ? "" : "Update the teyla command, then check again.")
            }
        }
    }
}

/// The answer first: the stage and the type as two chips, the one sentence, the command that moves it, and when the usage was read.
private struct StartupHead: View {
    @Environment(AppModel.self) private var model
    let productID: String
    let block: StartupBlock

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            FlowLayout(spacing: Space.s) {
                Chip(text: block.stageTitle, color: Palette.primary)
                    .help("The stage the evidence shows")
                Chip(text: StartupText.typeWord(block), color: block.typeSet ? Palette.textSecondary : Palette.needsYou)
                    .help(block.typeSet ? "Type" : "Nobody chose a type")
                if block.parked { Chip(text: "Parked", color: Palette.textSecondary) }
                if block.stale { Chip(text: "Stale", color: Palette.needsYou).help("The usage read is older than 7 days") }
            }
            Text(StartupText.sentence(block))
                .font(Typo.cardTitle)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if let command = block.next?.command, !command.isEmpty {
                Text(command)
                    .font(Typo.code)
                    .foregroundStyle(Palette.textSecondary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            TimelineView(.periodic(from: .now, by: 60)) { context in
                Text(StartupText.asOf(block, now: context.date))
                    .font(Typo.caption)
                    .foregroundStyle(block.stale ? Palette.needsYou : Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            typeLine
        }
        .card()
    }

    /// The type is the owner's to choose. A product with none reads as venture and says so; the picker is in the full app.
    @ViewBuilder private var typeLine: some View {
        let effective = StartupType(rawValue: block.type)
        VStack(alignment: .leading, spacing: Space.xs) {
            if let note = StartupText.typeNote(block) {
                Text(note).font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
            }
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                if let effective {
                    Text("North star: \(effective.northStar)")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: Space.s)
                if model.capabilities.editProducts { picker }
            }
            if !block.typeSet, !model.capabilities.editProducts {
                Text("Choose it on your Mac: teyla product set \(productID) type=venture")
                    .font(Typo.code)
                    .foregroundStyle(Palette.textSecondary)
                    .textSelection(.enabled)
            }
        }
    }

    private var picker: some View {
        Menu {
            ForEach(StartupType.allCases, id: \.self) { type in
                Button {
                    model.productPage.setType(type)
                } label: {
                    if block.typeSet && block.type == type.rawValue {
                        Label(type.title, systemImage: "checkmark")
                    } else {
                        Text(type.title)
                    }
                }
                .help(type.northStar)
            }
        } label: {
            Text(block.typeSet ? "Change type" : "Choose type")
        }
        .menuStyle(.button)
        .controlSize(.small)
        .fixedSize()
        .disabled(model.productPage.isChanging)
        .help("teyla product set \(productID) type=<type>. You choose it; Teyla never guesses.")
    }
}

/// The rungs in the order the CLI sends them, each with its status in words and a symbol.
private struct StartupLadder: View {
    let block: StartupBlock

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text("Ladder").font(Typo.cardTitle)
            if block.rungs.isEmpty {
                EmptyState(symbol: "questionmark.circle", title: "No steps were sent for this product.")
            } else {
                RowGroup {
                    ForEach(block.rungs) { rung in
                        row(rung)
                    }
                }
            }
        }
    }

    private func row(_ rung: StartupRung) -> some View {
        let state = RungState(rawValue: rung.status)
        let next = StartupText.isNext(rung, in: block)
        return RowCard(title: rung.title, detail: rung.detail, wraps: true) {
            Image(systemName: state?.symbol ?? "questionmark.circle")
                .font(Typo.body)
                .foregroundStyle(color(state))
                .frame(width: Space.glyph)
        } trailing: {
            HStack(spacing: Space.s) {
                if next { Chip(text: "Next", color: Palette.needsYou) }
                Text(RungState.word(for: rung.status))
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }
        }
        .padding(.vertical, Space.xs)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(rung.title): \(RungState.word(for: rung.status)). \(rung.detail)")
    }

    private func color(_ state: RungState?) -> Color {
        switch state {
        case .met: return Palette.primary
        case .stale: return Palette.needsYou
        default: return Palette.textSecondary
        }
    }
}

/// The metrics in their groups. A tile with no figure shows a dash and says why.
private struct StartupMetricGroups: View {
    let block: StartupBlock

    var body: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            ForEach(StartupText.groups(block), id: \.id) { group in
                VStack(alignment: .leading, spacing: Space.s) {
                    Text(group.title).font(Typo.cardTitle)
                    StatStrip {
                        ForEach(group.tiles, id: \.label) { tile in
                            StatTile(label: tile.label, value: tile.value, detail: tile.detail)
                        }
                    }
                    if !group.note.isEmpty {
                        Text(group.note)
                            .font(Typo.caption)
                            .foregroundStyle(Palette.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            if block.type == "personal" {
                Text("A personal product is not for sale, so it has no sales steps.")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
            }
        }
    }
}

/// The YC sheet, for a venture. The full app opens the sheet; the store build shows the count from the snapshot and nothing
/// else, because the answers are customer text and the relay is signed, not encrypted.
private struct StartupYCRow: View {
    @Environment(AppModel.self) private var model
    let productID: String
    let title: String
    let block: StartupBlock

    var body: some View {
        if let yc = block.yc, yc.eligible {
            VStack(alignment: .leading, spacing: Space.s) {
                Text("Y Combinator").font(Typo.cardTitle)
                RowGroup {
                    RowCard(title: StartupText.ycCount(yc), detail: YCText.notABar, wraps: true) {
                        if model.capabilities.startupSheet {
                            Button("Open sheet") { model.startup.open(id: productID, title: title) }
                                .controlSize(.small)
                        }
                    }
                    .padding(.vertical, Space.xs)
                }
            }
        }
    }
}
