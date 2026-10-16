import SwiftUI

/// Variant B, "morning brief": one sentence on what matters, then the questions, then status.
struct MainView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow

    private let wideThreshold: CGFloat = 800

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    header
                    if model.snapshot == nil {
                        EmptyStateView()
                    } else if proxy.size.width >= wideThreshold {
                        HStack(alignment: .top, spacing: 32) {
                            QuestionsColumn().frame(maxWidth: .infinity, alignment: .leading)
                            StatusColumn().frame(width: 340)
                        }
                    } else {
                        VStack(alignment: .leading, spacing: 28) {
                            QuestionsColumn()
                            StatusColumn()
                        }
                    }
                }
                .padding(.horizontal, 28)
                .padding(.vertical, 24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .toolbar {
            ToolbarItem(placement: .primaryAction) { LiveIndicator() }
            ToolbarItem(placement: .primaryAction) {
                Button {
                    model.refresh()
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
                .help("Refresh now")
                .disabled(model.isRefreshing)
            }
        }
        .navigationTitle("Teyla")
        .onAppear {
            model.openMainWindow = { openWindow(id: "main") }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            model.refresh()
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(model.briefLine)
                .font(.system(size: 28, weight: .semibold))
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if let snapshot = model.snapshot {
                Text(Format.subline(questions: model.visibleAsks.count,
                                    running: snapshot.running.count,
                                    spentUSD: snapshot.totals.spentTodayUSD))
                    .font(.body)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct LiveIndicator: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            HStack(spacing: 6) {
                Circle()
                    .fill(model.lastError == nil ? Color.green : Color.orange)
                    .frame(width: 7, height: 7)
                Text(label(at: context.date))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }
            .help(model.lastError ?? "Teyla re-reads your sessions when they change, and every minute.")
        }
    }

    private func label(at date: Date) -> String {
        guard let fetchedAt = model.fetchedAt else {
            return model.lastError == nil ? "Reading…" : "Offline"
        }
        let seconds = Int(date.timeIntervalSince(fetchedAt))
        if model.lastError != nil { return "Stale · updated \(max(0, seconds)) s ago" }
        return Format.updated(secondsAgo: seconds)
    }
}

private struct EmptyStateView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let error = model.lastError {
                Label("Could not read state", systemImage: "exclamationmark.triangle")
                    .font(.headline)
                    .foregroundStyle(.orange)
                Text(error)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                Button("Try again") { model.refresh() }
            } else {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Reading your sessions…").foregroundStyle(.secondary)
                }
            }
        }
        .padding(.top, 8)
    }
}

private struct QuestionsColumn: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionLabel("Needs you — ordered by what it unblocks")
            if model.visibleAsks.isEmpty {
                Label("Nothing is waiting for an answer.", systemImage: "checkmark.circle")
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 8)
            } else {
                ForEach(model.visibleAsks) { ask in
                    AskCard(ask: ask)
                        .transition(.opacity.combined(with: .scale(scale: 0.97)))
                }
            }
        }
        .animation(.easeOut(duration: 0.25), value: model.visibleAsks.map(\.id))
    }
}

private struct StatusColumn: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            VStack(alignment: .leading, spacing: 4) {
                SectionLabel("Products")
                let split = Format.splitProducts(model.snapshot?.products ?? [], running: model.snapshot?.running ?? [])
                ForEach(split.shown) { product in
                    ProductRow(product: product)
                }
                if split.rest > 0 {
                    Text("\(split.rest) more with no question and no session running")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .padding(.top, 4)
                }
                if (model.snapshot?.products ?? []).isEmpty {
                    Text("No products yet.").foregroundStyle(.secondary)
                }
            }
            VStack(alignment: .leading, spacing: 4) {
                SectionLabel("Running now")
                ForEach(model.snapshot?.running ?? []) { session in
                    RunningRow(session: session)
                }
                if (model.snapshot?.running ?? []).isEmpty {
                    Text("No session active in the last 10 minutes.").foregroundStyle(.secondary)
                }
            }
        }
    }
}

struct SectionLabel: View {
    let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(.secondary)
            .padding(.bottom, 4)
    }
}

private struct ProductRow: View {
    let product: Product

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(Format.product(product.name)).font(.body.weight(.semibold))
                Spacer(minLength: 8)
                StatePill(state: product.state, waiting: product.waiting)
            }
            if !product.line.isEmpty {
                Text(product.line)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 8)
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityElement(children: .combine)
    }
}

private struct StatePill: View {
    let state: ProductState
    let waiting: Int

    var body: some View {
        Text(label)
            .font(.caption.weight(.medium))
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .foregroundStyle(color)
            .background(color.opacity(0.14), in: Capsule())
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
        case .waiting: return .orange
        case .shipped: return .green
        case .quiet: return .secondary
        case .active: return .blue
        }
    }
}

private struct RunningRow: View {
    @Environment(AppModel.self) private var model
    let session: RunningSession

    var body: some View {
        let seconds = ISODate.parse(session.since).map { model.clock().timeIntervalSince($0) }
        Button {
            model.openSession(session.link, noteKey: session.id)
        } label: {
            HStack(alignment: .firstTextBaseline) {
                Text(title).lineLimit(1)
                Spacer(minLength: 8)
                Text(model.notes[session.id] ?? detail(seconds: seconds))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(session.link.isEmpty)
        .padding(.vertical, 6)
        .help(session.link.isEmpty ? "" : "Open session")
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
