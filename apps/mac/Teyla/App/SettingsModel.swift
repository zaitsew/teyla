import Foundation
import Observation

/// The Settings page: Teyla's own settings file, read when the page opens and read again when it is old. The page only
/// reads; nothing here writes the file.
@MainActor
@Observable
final class SettingsModel {
    private(set) var config: TeylaConfig?
    private(set) var failure: String?

    @ObservationIgnored private let cli: any TeylaBackend
    @ObservationIgnored private var readAt: Date?
    @ObservationIgnored private var reading = false

    /// The file is small, so the page reads it again after a minute.
    static let staleAfter: TimeInterval = 60

    init(cli: any TeylaBackend) {
        self.cli = cli
    }

    /// The page opened, or the owner asked again. A fresh read is not repeated unless `force` is set.
    func load(force: Bool = false) {
        if reading { return }
        if !force, let readAt, Date().timeIntervalSince(readAt) < Self.staleAfter, config != nil, failure == nil { return }
        reading = true
        Task {
            defer { reading = false }
            do {
                config = try await cli.teylaConfig()
                failure = nil
                readAt = Date()
            } catch {
                // A file that cannot be read is shown as such; an older read must not pass for the current file.
                failure = error.localizedDescription
                config = nil
            }
        }
    }
}
