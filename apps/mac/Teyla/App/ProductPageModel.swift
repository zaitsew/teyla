import Observation
import SwiftUI

/// One product page. The facts are `teyla product show <id> --json`; stage and focus are written by
/// `teyla product set`. The page reads the quick form first (asks and notes, at once), then the full one
/// (sessions and spend, which read 30 days of sessions and can take a minute).
@MainActor
@Observable
final class ProductPageModel {
    private(set) var id: String?
    private(set) var page: ProductPageData?
    private(set) var error: String?
    /// The sessions and the spend are still being read.
    private(set) var readingSessions = false
    /// What a stage or focus change is doing, or why it failed.
    private(set) var change: CardStatus?

    @ObservationIgnored private let cli: any TeylaBackend
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var quickGeneration = 0
    /// Called after the registry changed, so the sidebar and the Today list re-read state.
    @ObservationIgnored var changed: () -> Void = {}

    init(cli: any TeylaBackend) {
        self.cli = cli
    }

    /// Opens a product. Reading the same product again keeps what is on screen until the new answer arrives.
    func open(_ id: String) {
        if self.id != id {
            self.id = id
            page = nil
            error = nil
            change = nil
        }
        reload()
    }

    /// Forgets the open product, for a data source that just changed.
    func reset() {
        generation += 1
        quickGeneration += 1
        id = nil
        page = nil
        error = nil
        change = nil
        readingSessions = false
    }

    func reload() {
        guard let id else { return }
        generation += 1
        let mine = generation
        readingSessions = true
        Task {
            do {
                let quick = try await cli.productPage(id: id, quick: true)
                guard mine == generation else { return }
                if page?.product.id != id { page = quick } else { page?.product = quick.product; page?.asks = quick.asks; page?.notes = quick.notes }
                error = nil
            } catch {
                guard mine == generation else { return }
                self.error = error.localizedDescription
                readingSessions = false
                return
            }
            do {
                let full = try await cli.productPage(id: id, quick: false)
                guard mine == generation else { return }
                page = full
            } catch {
                guard mine == generation else { return }
                // The quick answer stays; only the sessions are missing.
                self.error = "Sessions and spend could not be read: \(error.localizedDescription)"
            }
            readingSessions = false
        }
    }

    /// Re-reads the quick form (the header, the questions and the notes) and keeps the sessions on screen.
    /// The window calls it on every refresh and after a note is added, linked or dropped.
    func refreshQuick() {
        guard let id, page != nil else { return }
        quickGeneration += 1
        let mine = quickGeneration
        Task {
            guard let quick = try? await cli.productPage(id: id, quick: true),
                  mine == quickGeneration, self.id == id, page?.product.id == id else { return }
            page?.product = quick.product
            page?.asks = quick.asks
            page?.notes = quick.notes
        }
    }

    func setStage(_ stage: ProductStage) {
        guard let id, page?.product.stage != stage.rawValue, !isChanging else { return }
        write("Saving…") { try await self.cli.setStage(id: id, stage: stage) } done: { $0.stage = stage.rawValue }
    }

    func setFocus(_ focus: Bool) {
        guard let id, page?.product.focus != focus, !isChanging else { return }
        write("Saving…") { try await self.cli.setFocus(id: id, focus: focus) } done: { $0.focus = focus }
    }

    var isChanging: Bool {
        if case .sending = change { return true }
        return false
    }

    func dismissChange() { change = nil }

    private func write(_ label: String, _ action: @escaping () async throws -> Void, done: @escaping (inout ProductHeader) -> Void) {
        change = .sending(label)
        // The write belongs to the product that was open when it started; the answer may arrive after another opened.
        let target = id
        Task {
            do {
                try await action()
                if id == target {
                    if let target { page?.applyWrite(to: target, done) }
                    change = nil
                }
                changed()
            } catch {
                if id == target { change = .failed(error.localizedDescription) }
            }
        }
    }
}
