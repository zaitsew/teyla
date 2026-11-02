import Foundation
import Observation

/// The ⌘K sheet: a text field over a fixed list. It holds the query and the highlighted row; the list itself comes
/// from `CommandBar.entries`, and choosing a row is the app model's job.
@MainActor
@Observable
final class CommandBarModel {
    var presented = false
    var query = "" {
        didSet { selection = CommandBar.clamped(0, count: results.count) }
    }
    private(set) var selection = 0

    /// The entries for the current state; set by the app model.
    @ObservationIgnored var source: () -> [CommandEntry] = { [] }

    var results: [CommandEntry] { CommandBar.filter(source(), query: query) }

    func open() {
        query = ""
        selection = 0
        presented = true
    }

    func close() { presented = false }

    func move(by step: Int) {
        selection = CommandBar.moved(selection, by: step, count: results.count)
    }

    func select(_ index: Int) {
        selection = CommandBar.clamped(index, count: results.count)
    }

    /// The highlighted entry, if the list is not empty.
    var highlighted: CommandEntry? {
        let list = results
        return list.isEmpty ? nil : list[CommandBar.clamped(selection, count: list.count)]
    }
}
