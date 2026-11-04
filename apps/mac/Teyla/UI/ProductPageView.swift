import SwiftUI

/// One product: its stage and focus, what waits on the owner, its notes, its recent sessions and its spend.
struct ProductPageView: View {
    @Environment(AppModel.self) private var model
    let id: String
    @State private var width: CGFloat = 0

    var body: some View {
        let page = model.productPage
        let portfolioProduct = model.snapshot?.portfolio?.product(id)
        Page(maxWidth: .infinity) {
            if let data = page.page, data.product.id == id {
                ProductHeaderView(header: data.product, spend: data.spend, reading: page.readingSessions,
                                  portfolio: portfolioProduct)
                content(data, page: page, portfolio: portfolioProduct, wide: width >= Space.wideWindow)
            } else if let error = page.error {
                ErrorRow(section: Format.product(id), message: error) { page.reload() }
            } else {
                // The snapshot already knows the product's health and platforms, so they show while the page reads.
                if let portfolioProduct {
                    PageHeader(title: portfolioProduct.title)
                    ProductStatusBlock(product: portfolioProduct)
                }
                ReadingLine(text: "Reading \(Format.product(id))…")
            }
        }
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
        .navigationTitle(model.snapshot?.products.first { $0.name == id }?.title ?? Format.product(id))
    }

    /// The sections stop at the reading width. On a wide window the platform details take the room beside them.
    @ViewBuilder
    private func content(_ data: ProductPageData, page: ProductPageModel, portfolio: PortfolioProduct?, wide: Bool) -> some View {
        let sections = VStack(alignment: .leading, spacing: Space.xl) {
            ProductAsksSection(asks: data.asks)
            if model.capabilities.console {
                ProductSellingSection(productID: id, parked: data.product.stage == "parked", portfolio: portfolio)
            }
            if model.capabilities.notes { ProductNotesSection(productID: id, notes: data.notes) }
            ProductSessionsSection(sessions: data.sessions, reading: page.readingSessions)
            if let error = page.error {
                ErrorRow(section: "This product", message: error)
            }
        }
        .readingWidth()
        if wide, let portfolio {
            HStack(alignment: .top, spacing: Space.xxl) {
                sections
                ProductFiguresColumn(product: portfolio)
                    .frame(minWidth: Space.sideColumn, maxWidth: .infinity, alignment: .leading)
            }
        } else {
            sections
        }
    }
}

/// A quiet inline progress line: a tiny spinner and small grey text.
struct ReadingLine: View {
    let text: String

    var body: some View {
        HStack(spacing: Space.xs) {
            ProgressView().controlSize(.mini)
            Text(text).font(Typo.caption).foregroundStyle(Palette.textSecondary)
        }
        .accessibilityElement(children: .combine)
    }
}

private struct ProductHeaderView: View {
    @Environment(AppModel.self) private var model
    let header: ProductHeader
    let spend: ProductSpend?
    let reading: Bool
    let portfolio: PortfolioProduct?

    var body: some View {
        let page = model.productPage
        VStack(alignment: .leading, spacing: Space.m) {
            HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                PageHeader(title: header.name) {
                    if header.registered { focusStar }
                }
            }
            HStack(spacing: Space.s) {
                if header.registered {
                    if model.capabilities.editProducts {
                        stageMenu
                    } else if !header.stage.isEmpty {
                        Chip(text: header.stage.capitalized, color: Palette.textSecondary)
                            .help("Stage")
                    }
                }
                if !header.primary.isEmpty {
                    Chip(text: platform(header.primary), color: Palette.textSecondary)
                        .help("Primary platform")
                }
                if header.registered {
                    Button {
                        model.selectProduct(header.id)
                    } label: {
                        Text(model.selectedProduct == header.id ? "New tasks start here" : "Start new tasks here")
                    }
                    .controlSize(.small)
                    .disabled(model.selectedProduct == header.id)
                    Button("New task…") {
                        model.selectProduct(header.id)
                        model.openNewTask()
                    }
                    .controlSize(.small)
                }
                switch page.change {
                case .sending(let text):
                    ProgressView().controlSize(.small)
                    Text(text).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                case .failed(let message):
                    Label(message, systemImage: "exclamationmark.triangle.fill")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.danger)
                        .textSelection(.enabled)
                        .onTapGesture { page.dismissChange() }
                default:
                    EmptyView()
                }
            }
            if let portfolio { ProductStatusBlock(product: portfolio) }
            spendLine
        }
    }

    @ViewBuilder private var focusStar: some View {
        if !model.capabilities.editProducts {
            if header.focus {
                Image(systemName: "star.fill")
                    .font(Typo.cardTitle)
                    .foregroundStyle(Palette.needsYou)
                    .help("In focus")
                    .accessibilityLabel("In focus")
            }
        } else {
            focusButton
        }
    }

    private var focusButton: some View {
        Button {
            model.productPage.setFocus(!header.focus)
        } label: {
            Image(systemName: header.focus ? "star.fill" : "star")
                .font(Typo.cardTitle)
                .foregroundStyle(header.focus ? Palette.needsYou : Palette.textSecondary)
        }
        .buttonStyle(.plain)
        .disabled(model.productPage.isChanging)
        .help(header.focus ? "In focus. Click to take it out of focus" : "Put this product in focus")
        .accessibilityLabel(header.focus ? "In focus" : "Not in focus")
        .accessibilityAddTraits(.isButton)
    }

    private var stageMenu: some View {
        Menu {
            ForEach(ProductStage.allCases, id: \.self) { stage in
                Button {
                    model.productPage.setStage(stage)
                } label: {
                    if header.stage == stage.rawValue {
                        Label(stage.title, systemImage: "checkmark")
                    } else {
                        Text(stage.title)
                    }
                }
            }
        } label: {
            Text(header.stage.isEmpty ? "No stage" : header.stage.capitalized)
        }
        .menuStyle(.button)
        .controlSize(.small)
        .fixedSize()
        .disabled(model.productPage.isChanging)
        .help("Stage. Parked products stay quiet in the lists")
    }

    @ViewBuilder
    private var spendLine: some View {
        if spend != nil || portfolio != nil {
            StatStrip {
                StatTile(label: "List price, 7 days", value: spend.map { Format.spent($0.days7) })
                StatTile(label: "List price, 30 days", value: spend.map { Format.spent($0.days30) })
                if let portfolio {
                    StatTile(label: "Open PRs", value: "\(portfolio.prs.open)",
                             detail: PortfolioText.prDetail(portfolio.prs))
                    StatTile(label: "Waiting", value: "\(portfolio.waiting)", detail: PortfolioText.oldestWait(portfolio),
                             tone: portfolio.waiting > 0 ? .needsYou : .neutral)
                }
            }
        }
        if reading && spend == nil {
            ReadingLine(text: "Reading the last 30 days of sessions…")
        }
    }

    private func platform(_ id: String) -> String { PortfolioText.platformName(id) }
}

private struct ProductAsksSection: View {
    @Environment(AppModel.self) private var model
    let asks: [ProductAsk]

    var body: some View {
        let open = asks.filter { !model.isHidden($0.id) }
        let split = AskFold.partition(open) { model.age(plus: $0.ageSeconds) }
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Needs you", count: open.isEmpty ? nil : open.count)
            if open.isEmpty {
                Label("Nothing is waiting for an answer.", systemImage: "checkmark.circle")
                    .foregroundStyle(Palette.textSecondary)
            }
            ForEach(split.fresh) { item in card(item, older: false) }
            if !split.older.isEmpty {
                OlderGroup(count: split.older.count, revealsFocus: split.older.contains { $0.id == model.focusedAskID }) {
                    ForEach(split.older) { item in card(item, older: true) }
                }
            }
        }
    }

    /// The live card when the window has the question (it can be answered here); otherwise the page's own line.
    @ViewBuilder
    private func card(_ item: ProductAsk, older: Bool) -> some View {
        if let ask = model.visibleAsks.first(where: { $0.id == item.id }) {
            AskCard(ask: ask, older: older)
        } else {
            ProductAskRow(item: item, older: older)
        }
    }
}

private struct ProductAskRow: View {
    @Environment(AppModel.self) private var model
    let item: ProductAsk
    var older = false

    /// Close shows when nothing is in flight; after a failed close it shows again, so the owner can retry.
    private var canClose: Bool {
        switch model.cards[item.id] {
        case nil, .failed: return true
        default: return false
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(spacing: Space.s) {
                if item.critical { Chip(text: "critical", color: Palette.danger) }
                Text(Format.age(seconds: model.age(plus: item.ageSeconds)))
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                Spacer(minLength: Space.s)
                if older, canClose, model.capabilities.closeQuestions {
                    Button(AskCard.closeLabel) { model.markDone(id: item.id) }
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                }
                if !item.link.isEmpty {
                    Button("Open session") { model.openSession(item.link, noteKey: item.id) }
                        .controlSize(.small)
                }
            }
            Text(item.question)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if let note = model.notes[item.id] {
                Text(note).font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
            switch model.cards[item.id] {
            case .sending(let text):
                ReadingLine(text: text)
            case .done(let text):
                Label(text, systemImage: "checkmark.circle.fill").font(Typo.caption).foregroundStyle(Palette.saving)
            case .failed(let message):
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.danger)
                    .textSelection(.enabled)
            case nil:
                EmptyView()
            }
        }
        .card()
    }
}

private struct ProductNotesSection: View {
    @Environment(AppModel.self) private var model
    let productID: String
    let notes: [ProductNote]

    /// The notes filed here now: the window's note list once it is read, so a note added or linked after the page loaded shows.
    private var shown: [NoteItem] {
        ProductNotes.shown(productID: productID, page: notes, list: model.noteList.items, listLoaded: model.noteList.loaded)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: Space.s) {
                SectionHeader(title: "Notes", count: shown.isEmpty ? nil : shown.count) {
                    Button("New note") { model.openQuickNote() }
                        .controlSize(.small)
                        .help("Keep an idea in a second")
                }
            }
            if shown.isEmpty {
                Text("No open notes for this product.")
                    .foregroundStyle(Palette.textSecondary)
                    .padding(.vertical, Space.s)
            }
            ForEach(shown) { note in
                NoteRow(note: note)
            }
        }
    }
}

private struct ProductSessionsSection: View {
    @Environment(AppModel.self) private var model
    let sessions: [ProductSession]?
    let reading: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionHeader(title: "Recent sessions")
            if let sessions {
                if sessions.isEmpty {
                    Text("No sessions in the last 30 days.")
                        .foregroundStyle(Palette.textSecondary)
                        .padding(.vertical, Space.s)
                }
                ForEach(sessions) { session in
                    row(session)
                }
            } else {
                Text(reading ? "Reading sessions…" : "Sessions were not read.")
                    .foregroundStyle(Palette.textSecondary)
                    .padding(.vertical, Space.s)
            }
        }
    }

    private func row(_ session: ProductSession) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.m) {
            VStack(alignment: .leading, spacing: Space.xxs) {
                Text(session.title.isEmpty ? "Untitled session" : session.title)
                    .lineLimit(1)
                Text(detail(session))
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }
            Spacer(minLength: Space.s)
            if session.costUSD > 0 {
                Text(Format.spent(session.costUSD))
                    .monospacedDigit()
                    .foregroundStyle(Palette.textSecondary)
            }
        }
        .padding(.vertical, Space.s)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityElement(children: .combine)
    }

    private func detail(_ session: ProductSession) -> String {
        var parts: [String] = []
        if let date = session.date {
            let age = Format.age(seconds: model.clock().timeIntervalSince(date))
            parts.append(age == "just now" ? age : "\(age) ago")
        }
        parts.append(session.harness)
        if !session.modelName.isEmpty { parts.append(session.modelName) }
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }
}
