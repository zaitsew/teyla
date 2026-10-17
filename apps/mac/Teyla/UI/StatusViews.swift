import SwiftUI

/// The side column: where each product stands, and what runs now.
struct StatusColumn: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xl) {
            VStack(alignment: .leading, spacing: Space.xs) {
                SectionLabel("Products")
                let split = Format.splitProducts(model.snapshot?.products ?? [], running: model.snapshot?.running ?? [])
                ForEach(split.shown) { product in
                    ProductRow(product: product)
                }
                if split.rest > 0 {
                    Text("\(split.rest) more with no question and no session running")
                        .font(Typo.body)
                        .foregroundStyle(Palette.textSecondary)
                        .padding(.top, Space.xs)
                }
                if (model.snapshot?.products ?? []).isEmpty {
                    Text("No products yet.").foregroundStyle(Palette.textSecondary)
                }
            }
            VStack(alignment: .leading, spacing: Space.xs) {
                SectionLabel("Running now")
                ForEach(model.snapshot?.running ?? []) { session in
                    RunningRow(session: session)
                }
                if (model.snapshot?.running ?? []).isEmpty {
                    Text("No session active in the last 10 minutes.").foregroundStyle(Palette.textSecondary)
                }
            }
        }
    }
}

private struct ProductRow: View {
    @Environment(AppModel.self) private var model
    let product: Product

    var body: some View {
        let selected = model.selectedProduct == product.name
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack {
                Text(Format.product(product.name)).font(Typo.body.weight(.semibold))
                Spacer(minLength: Space.s)
                StatePill(state: product.state, waiting: product.waiting)
            }
            if !product.line.isEmpty {
                Text(product.line)
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            let counts = Format.counts(issues: product.issues, prsWaiting: product.prsWaiting)
            if !counts.isEmpty {
                Text(counts)
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
            }
            if !product.next.isEmpty {
                Text("Next: \(product.next)")
                    .font(Typo.body)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if selected {
                Text("New tasks start here")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.accent)
            }
        }
        .padding(.vertical, Space.s)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .leading) {
            if selected { Rectangle().fill(Palette.accent).frame(width: 2).offset(x: -Space.s) }
        }
        .overlay(alignment: .bottom) { Divider() }
        .contentShape(Rectangle())
        .onTapGesture { model.selectProduct(product.name) }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
        .accessibilityHint("Makes this the product for new tasks")
        .help("Click to start new tasks in \(Format.product(product.name))")
    }
}

private struct StatePill: View {
    let state: ProductState
    let waiting: Int

    var body: some View {
        Chip(text: label, color: color)
    }

    private var label: String {
        switch state {
        case .waiting: return "\(waiting) waiting"
        case .shipped: return "shipped"
        case .quiet: return "quiet"
        case .active: return "active"
        }
    }

    private var color: Color {
        switch state {
        case .waiting: return Palette.warning
        case .shipped: return Palette.success
        case .quiet: return Palette.textSecondary
        case .active: return Palette.info
        }
    }
}

/// A session that is active now. A Codex session takes a one-line correction; any other opens.
private struct RunningRow: View {
    @Environment(AppModel.self) private var model
    let session: RunningSession

    @State private var draft = ""

    private var canCorrect: Bool { session.correct == "codex-queue" && !session.ref.isEmpty }
    private var status: CardStatus? { model.cards[session.ref] }

    var body: some View {
        let seconds = ISODate.parse(session.since).map { model.clock().timeIntervalSince($0) }
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(title).font(Typo.body).lineLimit(1)
                    Text(model.notes[session.id] ?? detail(seconds: seconds))
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(1)
                }
                Spacer(minLength: Space.s)
                if !canCorrect {
                    Button("Open") { model.openSession(session.link, noteKey: session.id) }
                        .disabled(session.link.isEmpty)
                }
            }
            if canCorrect { correction }
        }
        .padding(.vertical, Space.s)
        .overlay(alignment: .bottom) { Divider() }
        .contextMenu {
            Button("Open session") { model.openSession(session.link, noteKey: session.id) }
                .disabled(session.link.isEmpty)
        }
        .onChange(of: status) { _, new in
            if case .done = new { draft = "" }
        }
    }

    private var correction: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            switch status {
            case .sending(let text):
                HStack(spacing: Space.s) {
                    ProgressView().controlSize(.small)
                    Text(text).font(Typo.body).foregroundStyle(Palette.textSecondary)
                }
            case .done(let text):
                Label(text, systemImage: "checkmark.circle.fill")
                    .font(Typo.body)
                    .foregroundStyle(Palette.success)
                    .fixedSize(horizontal: false, vertical: true)
            case .failed(let message):
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.body)
                    .foregroundStyle(Palette.danger)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                Button("Back") { model.dismissCorrectionError(session) }
            case nil:
                HStack(spacing: Space.xs) {
                    TextField("Correct this session", text: $draft)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit(send)
                    MicButton(target: "say:\(session.ref)", text: $draft)
                    Button("Send", action: send)
                        .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                DictationNote(target: "say:\(session.ref)")
            }
        }
    }

    private func send() {
        model.say(session, text: draft)
    }

    private var title: String {
        let product = Format.product(session.product)
        return product.isEmpty ? session.title : "\(product) · \(session.title)"
    }

    private func detail(seconds: Double?) -> String {
        var parts: [String] = []
        if !session.model.isEmpty { parts.append(Format.model(session.model)) }
        if let seconds { parts.append(Format.duration(seconds: seconds)) }
        return parts.joined(separator: " · ")
    }
}
