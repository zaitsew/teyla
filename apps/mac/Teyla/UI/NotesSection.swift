import SwiftUI

/// Notes: the Inbox count and the newest open notes, each with Link… and Drop.
struct NotesSection: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let list = model.noteList
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: Space.s) {
                SectionLabel("Notes")
                Chip(text: "Inbox \(list.inbox)", color: list.inbox > 0 ? Palette.warning : Palette.info)
                    .padding(.bottom, Space.xs)
                    .accessibilityLabel("\(list.inbox) in the inbox")
                Spacer(minLength: Space.s)
                Button {
                    model.openQuickNote()
                } label: {
                    Text(newNoteTitle)
                }
                .controlSize(.small)
                .help("Keep an idea in a second")
            }
            if list.newest.isEmpty {
                Text(emptyLine(error: list.error))
                    .foregroundStyle(Palette.textSecondary)
                    .padding(.vertical, Space.s)
            } else {
                ForEach(list.newest) { note in
                    NoteRow(note: note)
                }
                if list.hiddenCount > 0 {
                    Text("\(list.hiddenCount) more open \(list.hiddenCount == 1 ? "note" : "notes") · teyla notes lists them")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .padding(.top, Space.s)
                }
            }
        }
    }

    private var newNoteTitle: String {
        model.quickNoteActive.map { "New note \($0.display)" } ?? "New note"
    }

    private func emptyLine(error: String?) -> String {
        if let error { return "Could not read the notes: \(error)" }
        let how = model.quickNoteActive.map { "Press \($0.display)" } ?? "Choose New note"
        return "No open notes. \(how) to keep an idea."
    }
}

struct NoteRow: View {
    @Environment(AppModel.self) private var model
    let note: NoteItem

    var body: some View {
        let list = model.noteList
        let row = list.rows[note.id]
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack(spacing: Space.s) {
                chip
                Text(age)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                Spacer(minLength: Space.s)
                if case .sending(let text) = row {
                    ProgressView().controlSize(.small)
                    Text(text).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                } else {
                    linkMenu(list)
                    Button("Drop") { list.drop(note) }
                        .controlSize(.small)
                        .help("Set this note aside (teyla note undrop brings it back)")
                }
            }
            Text(note.text)
                .font(Typo.body)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if case .failed(let message) = row {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.danger)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                    .onTapGesture { list.dismissError(note) }
            }
        }
        .padding(.vertical, Space.m)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityElement(children: .contain)
    }

    /// The product chip; a click opens that product's page.
    @ViewBuilder
    private var chip: some View {
        let chip = Chip(text: Notes.productLabel(note.product), color: note.isInbox ? Palette.warning : Palette.info)
        if !note.isInbox && model.hasPage(note.product) {
            Button { model.openProduct(note.product) } label: { chip }
                .buttonStyle(.plain)
                .help("Open the \(Notes.productLabel(note.product)) page")
        } else {
            chip
        }
    }

    private func linkMenu(_ list: NotesModel) -> some View {
        Menu("Link…") {
            Button("Inbox") { list.link(note, to: NoteItem.inbox) }
                .disabled(note.isInbox)
            Divider()
            ForEach(list.linkTargets, id: \.self) { id in
                Button(Notes.productLabel(id)) { list.link(note, to: id) }
                    .disabled(note.product == id)
            }
        }
        .menuStyle(.button)
        .controlSize(.small)
        .fixedSize()
        .help("File this note under a product")
    }

    private var age: String {
        guard let created = note.createdDate else { return "" }
        return Format.age(seconds: model.clock().timeIntervalSince(created))
    }
}
