import AppKit
import Observation
import SwiftUI
import UserNotifications
import os

/// What a card is doing right now. A card with no entry is idle.
enum CardStatus: Equatable {
    case sending(String)
    case done(String)
    case failed(String)
}

@MainActor
@Observable
final class AppModel {
    static let shared = AppModel()

    private(set) var snapshot: Snapshot?
    private(set) var fetchedAt: Date?
    private(set) var lastError: String?
    private(set) var isRefreshing = false
    private(set) var cards: [String: CardStatus] = [:]
    /// Short-lived messages shown on a card (or running row), keyed by ask id or session id.
    private(set) var notes: [String: String] = [:]

    /// Ids the user has answered, snoozed or closed. They stay hidden until a snapshot no
    /// longer lists them, so a refresh racing the CLI cannot bring a card back.
    private var hidden: Set<String> = []
    private var knownAskIDs: Set<String> = []
    private var firstLoadDone = false
    private var refreshQueued = false

    /// Set by the main window so the menu bar and the Dock can reopen it after it was closed.
    var openMainWindow: (() -> Void)?

    @ObservationIgnored private let cli = TeylaCLI()
    @ObservationIgnored private var watcher: SessionWatcher?
    @ObservationIgnored private var timerTask: Task<Void, Never>?
    @ObservationIgnored private var started = false
    @ObservationIgnored private let log = Logger(subsystem: "com.zaitsew.teyla", category: "app")

    var usesFixture: Bool { cli.usesFixture }

    // MARK: Derived

    var visibleAsks: [Ask] {
        (snapshot?.asks ?? []).filter { !hidden.contains($0.id) }
    }

    /// The reference "now" for ages: the snapshot's own clock plus the time since it was read.
    /// With a live CLI this is the wall clock; with a fixture it keeps the preview stable.
    func clock(at date: Date = Date()) -> Date {
        guard let generated = snapshot?.generatedDate, let fetchedAt else { return date }
        return generated.addingTimeInterval(date.timeIntervalSince(fetchedAt))
    }

    func age(of ask: Ask, at date: Date = Date()) -> Double {
        guard let fetchedAt else { return ask.ageSeconds }
        return ask.ageSeconds + max(0, date.timeIntervalSince(fetchedAt))
    }

    var briefLine: String {
        if let line = snapshot?.brief?.line, !line.isEmpty { return line }
        let n = visibleAsks.count
        if snapshot == nil { return lastError == nil ? "Reading your sessions…" : "Teyla cannot read your sessions." }
        return n == 0 ? "Nothing needs you right now." : "\(n) \(n == 1 ? "question needs" : "questions need") you."
    }

    // MARK: Lifecycle

    func start() {
        guard !started else { return }
        started = true
        requestNotificationPermission()
        let watcher = SessionWatcher { [weak self] in
            Task { @MainActor in self?.refresh() }
        }
        if !watcher.start() { log.info("No session store directory exists yet; relying on the 60 s timer") }
        self.watcher = watcher
        timerTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(60))
                self?.refresh()
            }
        }
        refresh()
    }

    func refresh() {
        if isRefreshing {
            refreshQueued = true
            return
        }
        isRefreshing = true
        Task {
            defer {
                isRefreshing = false
                if refreshQueued {
                    refreshQueued = false
                    refresh()
                }
            }
            do {
                let next = try await cli.state()
                apply(next)
            } catch {
                lastError = error.localizedDescription
                log.error("state failed: \(error.localizedDescription, privacy: .public)")
            }
        }
    }

    private func apply(_ next: Snapshot) {
        snapshot = next
        fetchedAt = Date()
        lastError = nil
        let ids = Set(next.asks.map(\.id))
        hidden.formIntersection(ids)
        if firstLoadDone {
            for ask in next.asks where !knownAskIDs.contains(ask.id) && !hidden.contains(ask.id) {
                notify(ask)
            }
        }
        knownAskIDs.formUnion(ids)
        firstLoadDone = true
    }

    // MARK: Actions

    func answer(_ ask: Ask, text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isBusy(ask) else { return }
        cards[ask.id] = .sending("Sending…")
        Task {
            do {
                let result = try await cli.answer(id: ask.id, text: trimmed)
                finish(ask, message: Format.sentLine(via: result.via))
            } catch {
                cards[ask.id] = .failed(error.localizedDescription)
            }
        }
    }

    func snooze(_ ask: Ask, days: Int = 1) {
        guard !isBusy(ask) else { return }
        cards[ask.id] = .sending("Snoozing…")
        Task {
            do {
                try await cli.snooze(id: ask.id, days: days)
                finish(ask, message: "Snoozed for \(days) day\(days == 1 ? "" : "s")")
            } catch {
                cards[ask.id] = .failed(error.localizedDescription)
            }
        }
    }

    func markDone(_ ask: Ask) {
        guard !isBusy(ask) else { return }
        cards[ask.id] = .sending("Marking done…")
        Task {
            do {
                try await cli.markDone(id: ask.id)
                finish(ask, message: "Marked done")
            } catch {
                cards[ask.id] = .failed(error.localizedDescription)
            }
        }
    }

    func dismissError(_ ask: Ask) {
        if case .failed = cards[ask.id] { cards[ask.id] = nil }
    }

    /// Opens a URL link in its app. A link without a URL scheme is a shell command (Claude Code
    /// sessions): it goes to the clipboard, with a note under `noteKey`, and is never handed to NSWorkspace.
    func openSession(_ link: String, noteKey: String) {
        switch SessionLink(link) {
        case .none:
            return
        case .url(let url):
            NSWorkspace.shared.open(url)
        case .command(let command):
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(command, forType: .string)
            notes[noteKey] = "Command copied: paste it in a terminal"
            Task {
                try? await Task.sleep(for: .seconds(4))
                notes[noteKey] = nil
            }
        }
    }

    func copyQuestion(_ ask: Ask) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(ask.question, forType: .string)
    }

    func showMainWindow() {
        openMainWindow?()
        NSApp.activate()
    }

    private func isBusy(_ ask: Ask) -> Bool {
        if case .sending = cards[ask.id] { return true }
        return false
    }

    /// Show the confirmation line for a moment, then remove the card.
    private func finish(_ ask: Ask, message: String) {
        cards[ask.id] = .done(message)
        Task {
            try? await Task.sleep(for: .seconds(3))
            withAnimation(.easeOut(duration: 0.25)) {
                hidden.insert(ask.id)
                cards[ask.id] = nil
            }
            refresh()
        }
    }

    // MARK: Notifications

    private func requestNotificationPermission() {
        guard Bundle.main.bundleURL.pathExtension == "app" else { return }
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { [log] granted, error in
            if let error { log.error("notification permission failed: \(error.localizedDescription, privacy: .public)") }
            else if !granted { log.info("notification permission not granted") }
        }
    }

    private func notify(_ ask: Ask) {
        guard Bundle.main.bundleURL.pathExtension == "app" else { return }
        let content = UNMutableNotificationContent()
        content.title = Format.product(ask.product)
        content.body = ask.question
        content.sound = .default
        let request = UNNotificationRequest(identifier: "ask-\(ask.id)", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request) { [log] error in
            if let error { log.error("notification failed: \(error.localizedDescription, privacy: .public)") }
        }
    }
}
