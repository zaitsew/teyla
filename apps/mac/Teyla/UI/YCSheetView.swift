import SwiftUI

/// The YC sheet (docs/STARTUP.md, "The YC sheet"): fifteen boxes, each a question the owner can answer honestly with
/// evidence. The count is "2 of 15", with no ring and no percent. An unchecked box never reads as a reason not to apply,
/// and Teyla never submits: when every box is checked the sheet links to the application and the owner applies himself.
/// The answers are customer text. They live in this window while it is open and in `~/.teyla/startup/`, nowhere else.
struct YCSheetView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let startup = model.startup
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text("Y Combinator sheet").font(Typo.section).accessibilityAddTraits(.isHeader)
                    Text(startup.title).font(Typo.body).foregroundStyle(Palette.textSecondary)
                }
                Spacer(minLength: Space.m)
                if startup.isLoading { ProgressView().controlSize(.small) }
                Button("Done") { startup.close() }
                    .keyboardShortcut(.cancelAction)
            }
            .padding(Space.xl)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: Space.xl) {
                    if let sheet = startup.sheet {
                        YCLead(sheet: sheet)
                        YCBoxes(sheet: sheet)
                        YCFactsView(facts: sheet.facts)
                        if let why = startup.failure {
                            ClampedText(text: "This is the last sheet that was read. \(why)", lines: 2, font: Typo.caption)
                        }
                    } else if let why = startup.failure {
                        ErrorRow(section: "the YC sheet", message: why) { startup.reload() }
                    } else {
                        ReadingLine(text: "Reading the sheet…")
                    }
                }
                .padding(Space.xl)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(width: Space.ycSheetWidth, height: Space.ycSheetHeight)
        .background(Palette.background)
    }
}

/// The count first, then the next box or the way to the application.
private struct YCLead: View {
    @Environment(\.openURL) private var openURL
    let sheet: YCSheet

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                Text("\(YCText.count(sheet)) boxes checked").font(Typo.section)
                Spacer(minLength: Space.m)
                if YCText.canApply(sheet) {
                    Button("Apply") { openURL(YCText.applyURL) }
                        .buttonStyle(.borderedProminent)
                        .help("Opens ycombinator.com/apply in your browser. Teyla does not submit anything.")
                }
            }
            Text(YCText.lead(sheet)).font(Typo.body).fixedSize(horizontal: false, vertical: true)
            Text("\(YCText.notABar) \(YCText.neverSubmits)")
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct YCBoxes: View {
    let sheet: YCSheet

    var body: some View {
        RowGroup {
            ForEach(sheet.boxes) { box in
                YCBoxRow(box: box)
            }
        }
    }
}

private struct YCBoxRow: View {
    @Environment(AppModel.self) private var model
    let box: YCBox

    var body: some View {
        let startup = model.startup
        HStack(alignment: .top, spacing: Space.m) {
            Image(systemName: box.checked ? "checkmark.square.fill" : "square")
                .font(Typo.body)
                .foregroundStyle(box.checked ? Palette.primary : Palette.textSecondary)
                .frame(width: Space.glyph)
                .accessibilityLabel(box.checked ? "Checked" : "Not checked")
            VStack(alignment: .leading, spacing: Space.xs) {
                Text(box.question).font(Typo.body.weight(.semibold)).fixedSize(horizontal: false, vertical: true)
                Text(YCText.status(box))
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                if box.origin == "teyla" {
                    Text("Added by Teyla. It is not on the founder list.")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                }
                if !box.auto { editor(startup) }
                if !box.checked, !box.command.isEmpty, box.auto || box.answer?.isDraft == true {
                    Text(box.command).font(Typo.code).foregroundStyle(Palette.textSecondary).textSelection(.enabled)
                }
            }
        }
        .padding(.vertical, Space.m)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private func editor(_ startup: StartupModel) -> some View {
        let draft = startup.drafts[box.id] ?? ""
        VStack(alignment: .leading, spacing: Space.s) {
            TextField(YCText.hint(for: box), text: Binding(get: { startup.drafts[box.id] ?? "" }, set: { startup.drafts[box.id] = $0 }), axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...5)
                .disabled(startup.isSaving(box.id))
            HStack(spacing: Space.s) {
                Button(YCText.saveLabel(box, draft: draft)) { startup.save(box: box.id) }
                    .controlSize(.small)
                    .disabled(!YCText.canSave(box, draft: draft) || startup.isSaving(box.id))
                if startup.isSaving(box.id) { ProgressView().controlSize(.small) }
                if draft.count > StartupCommands.maxAnswer {
                    Text("\(draft.count) of \(StartupCommands.maxAnswer) characters. Shorten it.")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.danger)
                }
                if let why = startup.failures[box.id] {
                    Label(why, systemImage: "exclamationmark.triangle.fill")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.danger)
                        .textSelection(.enabled)
                        .lineLimit(2)
                }
            }
        }
    }
}

private struct YCFactsView: View {
    let facts: YCFacts

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text(YCText.factsHeader(facts)).font(Typo.cardTitle)
            ForEach(Array(facts.lines.enumerated()), id: \.offset) { _, line in
                Text(line)
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let warning = YCText.staleFacts(facts) {
                Label(warning, systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.needsYou)
            }
        }
    }
}
