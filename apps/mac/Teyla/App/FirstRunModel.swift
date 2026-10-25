import Observation
import SwiftUI

/// The first run: the read-only diagnosis (`teyla start --json`) and the offers it makes (`teyla apply <id> --yes`).
/// Nothing is kept between launches: the diagnosis is read again when the owner asks.
@MainActor
@Observable
final class FirstRunModel {
    private(set) var phase: DiagnosisPhase = .idle
    private(set) var startedAt: Date?
    private(set) var offers: [String: OfferStatus] = [:]
    /// The offer the confirm sheet is about.
    var pending: StartOffer?

    @ObservationIgnored private let cli: TeylaCLI
    @ObservationIgnored private var running: Task<Void, Never>?
    /// Called after an offer was applied, so the window re-reads state.
    @ObservationIgnored var applied: () -> Void = {}

    init(cli: TeylaCLI) {
        self.cli = cli
    }

    var report: StartReport? {
        if case .ready(let report) = phase { return report }
        return nil
    }

    var isRunning: Bool { phase == .running }

    /// Runs the diagnosis in the background. A second press while it runs does nothing.
    func run() {
        guard !isRunning else { return }
        phase = .running
        startedAt = Date()
        offers = [:]
        running = Task {
            do {
                let report = try await cli.start()
                phase = .ready(report)
            } catch {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    func status(of offer: StartOffer) -> OfferStatus? { offers[offer.id] }

    func ask(_ offer: StartOffer) {
        guard OfferStatus.allowsConfirmation(offers[offer.id]) else { return }
        pending = offer
    }

    func cancel() { pending = nil }

    /// The confirm sheet's button: runs `teyla apply <id> --yes` once.
    func confirm() {
        guard let offer = pending else { return }
        pending = nil
        guard OfferStatus.allowsConfirmation(offers[offer.id]) else { return }
        offers[offer.id] = .applying
        Task {
            do {
                let lines = try await cli.apply(offerID: offer.id)
                offers[offer.id] = .applied(lines)
                applied()
            } catch {
                offers[offer.id] = .failed(error.localizedDescription)
            }
        }
    }

    private func isFailed(_ offer: StartOffer) -> Bool {
        if case .failed = offers[offer.id] { return true }
        return false
    }

    func dismissError(_ offer: StartOffer) {
        if isFailed(offer) { offers[offer.id] = nil }
    }
}
