import SwiftUI

/// One product: its stage and focus, what waits on the owner, its notes, its recent sessions and its spend.
struct ProductPageView: View {
    @Environment(AppModel.self) private var model
    let id: String

    var body: some View {
        let page = model.productPage
        let portfolioProduct = model.snapshot?.portfolio?.product(id)
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: Space.xl) {
                    if let data = page.page, data.product.id == id {
                        ProductHeaderView(header: data.product, spend: data.spend, reading: page.readingSessions,
                                          portfolio: portfolioProduct)
                        content(data, page: page, portfolio: portfolioProduct, wide: proxy.size.width >= Space.wideWindow)
                    } else if let error = page.error {
                        VStack(alignment: .leading, spacing: Space.s) {
                            Label("Could not read \(Format.product(id))", systemImage: "exclamationmark.triangle")
                                .font(Typo.lead)
                                .foregroundStyle(Palette.warning)
                            Text(error)
                                .foregroundStyle(Palette.textSecondary)
                                .textSelection(.enabled)
                            Button("Try again") { page.reload() }
                        }
                    } else {
                        // The snapshot already knows the product's health and platforms, so they show while the page reads.
                        if let portfolioProduct {
                            Text(portfolioProduct.title).font(Typo.brief)
                            ProductStatusBlock(product: portfolioProduct)
                        }
                        ReadingLine(text: "Reading \(Format.product(id))…")
                    }
                }
                .padding(.horizontal, Space.xl + Space.xs)
                .padding(.vertical, Space.xl)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .background(Palette.background)
        .navigationTitle(model.snapshot?.products.first { $0.name == id }?.title ?? Format.product(id))
    }

    /// The sections stop at the reading width. On a wide window the platform details take the room beside them.
    @ViewBuilder
    private func content(_ data: ProductPageData, page: ProductPageModel, portfolio: PortfolioProduct?, wide: Bool) -> some View {
        let sections = VStack(alignment: .leading, spacing: Space.xl) {
            ProductAsksSection(asks: data.asks)
            ProductNotesSection(productID: id, notes: data.notes)
            ProductSessionsSection(sessions: data.sessions, reading: page.readingSessions)
            if let error = page.error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.warning)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .readingWidth()
        if wide, let portfolio {
            HStack(alignment: .top, spacing: Space.xxl) {
                sections
                ProductFiguresColumn(product: portfolio)
                    .frame(minWidth: Space.sideColumn, maxWidth: Space.sideColumnMax, alignment: .leading)
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
        HStack(spacing: Space.xs + Space.xxs) {
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
                Text(header.name)
                    .font(Typo.brief)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                if header.registered { focusStar }
                Spacer(minLength: Space.s)
            }
            HStack(spacing: Space.s) {
                if header.registered { stageMenu }
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

    private var focusStar: some View {
        Button {
            model.productPage.setFocus(!header.focus)
        } label: {
            Image(systemName: header.focus ? "star.fill" : "star")
                .font(Typo.lead)
                .foregroundStyle(header.focus ? Palette.warning : Palette.textSecondary)
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
        if let spend {
            Text("\(Format.spent(spend.days7)) in 7 days · \(Format.spent(spend.days30)) in 30 days at API list price")
                .foregroundStyle(Palette.textSecondary)
                .monospacedDigit()
        } else if reading {
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
            SectionLabel(open.isEmpty ? "Needs you" : "Needs you · \(open.count)")
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
                if older, canClose {
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
                Label(text, systemImage: "checkmark.circle.fill").font(Typo.caption).foregroundStyle(Palette.success)
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
                SectionLabel(shown.isEmpty ? "Notes" : "Notes · \(shown.count)")
                Spacer(minLength: Space.s)
                Button("New note") { model.openQuickNote() }
                    .controlSize(.small)
                    .help("Keep an idea in a second")
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
            SectionLabel("Recent sessions")
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
            Text(Format.spent(session.costUSD))
                .monospacedDigit()
                .foregroundStyle(Palette.textSecondary)
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
