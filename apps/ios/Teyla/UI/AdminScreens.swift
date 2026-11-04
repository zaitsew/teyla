import SwiftUI

// Money, Operations and Playbook on the phone. Each reads only the compact part the Mac sends (`PhoneConsole`); what the
// phone does not get is a dash with "On your Mac".

struct MoneyScreen: View {
    var body: some View {
        ConsoleScreen(page: ConsoleText.money, pick: { $0.money }) { money in
            ConsoleTiles(tiles: PhoneConsole.moneyTiles(money))
            OnMacNote(title: "The list of subscriptions is on your Mac",
                      detail: "The phone gets the total and the next renewal. Add or change a subscription on your Mac.")
        }
        .navigationTitle(ConsoleText.money.title)
        .navigationBarTitleDisplayMode(.large)
    }
}

struct OperationsScreen: View {
    var body: some View {
        ConsoleScreen(page: ConsoleText.operations, pick: { $0.operations }) { operations in
            ConsoleTiles(tiles: PhoneConsole.operationsTiles(operations))
            failures(operations)
        }
        .navigationTitle(ConsoleText.operations.title)
        .navigationBarTitleDisplayMode(.large)
    }

    @ViewBuilder
    private func failures(_ operations: OperationsCompact) -> some View {
        let split = OperationsLogic.failuresInOrder(operations.failures)
        let shown = split.act + split.info
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "What failed", count: operations.failuresRead ? shown.count : nil)
            if !operations.failuresRead {
                EmptyState(symbol: "desktopcomputer", title: PhoneConsole.onMac,
                           detail: "This update from your Mac has no list of failures.")
            } else if shown.isEmpty {
                EmptyState(symbol: "checkmark.circle", title: "Nothing is failing")
            } else {
                RowGroup {
                    ForEach(shown) { failure in
                        VStack(alignment: .leading, spacing: Space.xxs) {
                            Text(PhoneConsole.severityWord(failure))
                                .font(Typo.caption.weight(.semibold))
                                .foregroundStyle(failure.needsYou ? Palette.danger : Palette.textSecondary)
                            Text(failure.title)
                                .font(Typo.body.weight(.semibold))
                                .fixedSize(horizontal: false, vertical: true)
                            if !failure.detail.isEmpty {
                                ClampedText(text: failure.detail, lines: 3, font: Typo.caption)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, Space.s)
                    }
                }
            }
            if let more = PhoneConsole.moreFailures(operations) {
                Text(more).font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
        }
    }
}

struct PlaybookScreen: View {
    var body: some View {
        ConsoleScreen(page: ConsoleText.playbook, pick: { $0.playbook }) { playbook in
            ConsoleTiles(tiles: PhoneConsole.playbookTiles(playbook))
            ConsoleRows(title: "What you have written down", rows: PhoneConsole.knowledgeRows(playbook))
            if let quote = playbook.quote, !quote.isEmpty {
                VStack(alignment: .leading, spacing: Space.m) {
                    SectionHeader(title: "From your own words")
                    ClampedText(text: quote, lines: 6, font: Typo.body)
                        .surface(padding: Space.l)
                }
            }
        }
        .navigationTitle(ConsoleText.playbook.title)
        .navigationBarTitleDisplayMode(.large)
    }
}
