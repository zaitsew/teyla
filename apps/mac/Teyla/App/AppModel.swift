import AppKit
import Observation
import SwiftUI
import UserNotifications
import os

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
    private var askTracker = AskTracker()
    private var refreshQueued = false

    /// The question a notification pointed at; the window scrolls to its card and marks it for a moment.
    private(set) var focusedAskID: String?
    /// What Settings says about the ⌥⌘Space shortcut.
    private(set) var hotKeyLine = GlobalHotKey.describe(noErr)
    /// The quick-note shortcut the owner set (nil: turned off), and the one actually registered (nil: none works).
    private(set) var quickNoteSetting: Shortcut? = ShortcutStore().load()
    private(set) var quickNoteActive: Shortcut?
    private(set) var quickNoteLine = QuickNoteShortcut.describe(ShortcutStore().load(), status: nil)
    /// The product new tasks start in by default; chosen by clicking a product. Remembered.
    private(set) var selectedProduct: String? = UserDefaults.standard.string(forKey: "selectedProduct")

    /// What the detail pane shows; the sidebar sets it.
    var route: AppRoute = .today
    /// The teyla command was not found: the window shows how to install it, or lets the owner choose the file.
    private(set) var teylaMissing = false
    /// "Check again" is looking, and whether the last look found nothing.
    private(set) var recheckingBinary = false
    private(set) var recheckFailed = false
    /// What "Copy" last copied, for a moment.
    private(set) var installCopied = false

    /// Set by the main window so the menu bar and the Dock can reopen it after it was closed.
    var openMainWindow: (() -> Void)?

    @ObservationIgnored let cli: TeylaCLI
    let newTask: NewTaskModel
    let relay: RelayModel
    let quickNote: QuickNoteModel
    let noteList: NotesModel
    let firstRun: FirstRunModel
    let productPage: ProductPageModel
    @ObservationIgnored private var hotKeyTalk = PushToTalk()
    @ObservationIgnored private var watcher: SessionWatcher?
    @ObservationIgnored private var timerTask: Task<Void, Never>?
    @ObservationIgnored private var wakeObserver: NSObjectProtocol?
    @ObservationIgnored private var started = false
    @ObservationIgnored private let log = Logger(subsystem: "com.zaitsew.teyla", category: "app")

    var usesFixture: Bool { cli.usesFixture }

    init() {
        let cli = TeylaCLI()
        self.cli = cli
        newTask = NewTaskModel(cli: cli)
        relay = RelayModel(cli: cli)
        quickNote = QuickNoteModel(cli: cli)
        noteList = NotesModel(cli: cli)
        firstRun = FirstRunModel(cli: cli)
        productPage = ProductPageModel(cli: cli)
        let names: () -> [String] = { [weak self] in
            NewTask.products(self?.snapshot?.products ?? []).map(\.name)
        }
        quickNote.productNames = names
        noteList.productNames = names
        quickNote.saved = { [weak self] note in self?.noteList.saved(note) }
        quickNote.learnedCandidates = { [weak self] list in self?.noteList.setCandidates(list) }
        quickNote.close = { [weak self] in self?.closeQuickNote() }
        firstRun.applied = { [weak self] in self?.refresh() }
        productPage.changed = { [weak self] in self?.refresh() }
        noteList.changed = { [weak self] in self?.productPage.refreshQuick() }
    }

    /// The welcome alone, with no sidebar: nothing to read yet, one button to press.
    var showsWelcomeOnly: Bool {
        Shell.showsWelcomeOnly(snapshot: snapshot, diagnosis: firstRun.phase, teylaMissing: teylaMissing)
    }

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
        age(plus: ask.ageSeconds, at: date)
    }

    /// An age reported in the snapshot, plus the time since the snapshot was read.
    func age(plus seconds: Double, at date: Date = Date()) -> Double {
        guard let fetchedAt else { return seconds }
        return seconds + max(0, date.timeIntervalSince(fetchedAt))
    }

    var briefLine: String {
        if let line = snapshot?.brief?.line, !line.isEmpty { return line }
        let n = visibleAsks.count
        if snapshot == nil { return lastError == nil ? "Reading your sessions…" : "Teyla cannot read your sessions." }
        return n == 0 ? "Nothing needs you right now." : "\(n) \(n == 1 ? "question needs" : "questions need") you."
    }

    /// The toolbar indicator: whether the data on screen is being read, current, old, or failed.
    /// A fixture snapshot has a fixed `generated` time, so it is not counted against the clock.
    func syncIndicator(at date: Date = Date()) -> SyncIndicator {
        var pageLoading = false
        var pageError: String?
        if case .product = route {
            pageLoading = productPage.readingSessions
            pageError = productPage.error
        }
        let portfolio = snapshot?.portfolio
        return SyncStatus.indicator(
            now: date, fetchedAt: fetchedAt, generated: usesFixture ? nil : snapshot?.generatedDate,
            refreshing: isRefreshing, pageLoading: pageLoading, error: lastError ?? pageError,
            checkedStores: portfolio.flatMap { ISODate.parse($0.checkedStores) },
            checkedGitHub: portfolio.flatMap { ISODate.parse($0.checkedGitHub) },
            hasPortfolio: portfolio != nil)
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
        // The 60 s timer does not run while the Mac sleeps; read again as soon as it wakes.
        wakeObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        timerTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(60))
                self?.refresh()
            }
        }
        refresh()
    }

    func refresh() {
        noteList.refresh()
        if case .product = route { productPage.refreshQuick() }
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
                if let failure = error as? TeylaError, failure == .binaryNotFound { teylaMissing = true }
                log.error("state failed: \(error.localizedDescription, privacy: .public)")
            }
        }
    }

    // MARK: The teyla command

    /// "Check again": asks a login shell afresh, then reads state if the command is there.
    func recheckBinary() {
        guard !recheckingBinary else { return }
        recheckingBinary = true
        Task {
            cli.forgetBinary()
            let found = await cli.binaryPath()
            recheckingBinary = false
            recheckFailed = found == nil
            teylaMissing = found == nil
            if found != nil { refresh() }
        }
    }

    /// "Choose…": the owner picks the file; it is stored and tried first.
    func chooseBinary() {
        let panel = NSOpenPanel()
        panel.message = "Choose the teyla command"
        panel.prompt = "Choose"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.treatsFilePackagesAsDirectories = true
        panel.directoryURL = URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent(".local/bin")
        guard panel.runModal() == .OK, let url = panel.url else { return }
        TeylaBinary.choose(url.path)
        recheckBinary()
    }

    func copyInstallCommand() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(TeylaBinary.installCommand, forType: .string)
        installCopied = true
        Task {
            try? await Task.sleep(for: .seconds(2))
            installCopied = false
        }
    }

    // MARK: Diagnosis and product pages

    func runDiagnosis() {
        go(.diagnosis)
        firstRun.run()
    }

    /// The sidebar and every link to a product go through here, so a product page always reads its data.
    func go(_ next: AppRoute) {
        route = next
        if case .product(let id) = next { productPage.open(id) }
    }

    func openProduct(_ id: String) {
        guard ProductCommands.isProductID(id), !id.hasPrefix("(") else { return }
        showMainWindow()
        go(.product(id))
    }

    /// Whether a product name from an ask or a note has a page to open.
    func hasPage(_ id: String) -> Bool {
        snapshot?.products.first { $0.name == id }?.hasPage ?? false
    }

    private func apply(_ next: Snapshot) {
        snapshot = next
        fetchedAt = Date()
        lastError = nil
        teylaMissing = false
        let ids = Set(next.asks.map(\.id))
        hidden.formIntersection(ids)
        for ask in askTracker.fresh(in: next.asks, hidden: hidden) { notify(ask) }
        relay.reconcile(with: next.relay, usesFixture: usesFixture)
    }

    // MARK: Actions

    func answer(_ ask: Ask, text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isBusy(ask) else { return }
        Dictation.shared.stop()             // later results must not refill a field that was sent
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

    func markDone(_ ask: Ask) { markDone(id: ask.id) }

    /// Closes a question by id (`teyla asks done`). The product page uses it for questions the window does not hold as cards.
    func markDone(id: String) {
        guard !isBusy(id: id) else { return }
        cards[id] = .sending("Marking done…")
        Task {
            do {
                try await cli.markDone(id: id)
                finish(id: id, message: "Marked done")
            } catch {
                cards[id] = .failed(error.localizedDescription)
            }
        }
    }

    /// Whether the owner already answered, snoozed or closed this question in this window.
    func isHidden(_ id: String) -> Bool { hidden.contains(id) }

    func dismissError(_ ask: Ask) {
        if case .failed = cards[ask.id] { cards[ask.id] = nil }
    }

    /// A correction for a running session (`teyla say`). The result line shows for a few seconds.
    func say(_ session: RunningSession, text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = session.ref
        guard !trimmed.isEmpty, !key.isEmpty else { return }
        Dictation.shared.stop()
        if case .sending = cards[key] { return }
        cards[key] = .sending("Sending…")
        Task {
            do {
                let result = try await cli.say(ref: key, text: trimmed)
                cards[key] = .done(Format.saidLine(via: result.via))
                try? await Task.sleep(for: .seconds(8))
                if case .done = cards[key] { cards[key] = nil }
            } catch {
                cards[key] = .failed(error.localizedDescription)
            }
        }
    }

    func dismissCorrectionError(_ session: RunningSession) {
        if case .failed = cards[session.ref] { cards[session.ref] = nil }
    }

    func selectProduct(_ name: String) {
        selectedProduct = name
        UserDefaults.standard.set(name, forKey: "selectedProduct")
    }

    func clearFocus() { focusedAskID = nil }

    /// Registers ⌥⌘Space for push-to-talk and the quick-note shortcut. Called once at launch.
    func registerHotKey() {
        let key = GlobalHotKey.shared
        key.onPress = { Task { @MainActor in AppModel.shared.hotKeyDown() } }
        key.onRelease = { Task { @MainActor in AppModel.shared.hotKeyUp() } }
        hotKeyLine = GlobalHotKey.describe(key.register())
        GlobalHotKey.quickNote.onPress = { Task { @MainActor in AppModel.shared.toggleQuickNote() } }
        applyQuickNoteShortcut()
    }

    // MARK: Quick note

    /// Registers what is stored (or nothing, when the owner cleared it). A failure leaves the shortcut off and says why.
    func applyQuickNoteShortcut() {
        let wanted = ShortcutStore().load()
        quickNoteSetting = wanted
        guard let wanted else {
            GlobalHotKey.quickNote.unregister()
            quickNoteActive = nil
            quickNoteLine = QuickNoteShortcut.describe(nil, status: nil)
            return
        }
        let status = GlobalHotKey.quickNote.register(wanted)
        quickNoteActive = status == noErr ? wanted : nil
        quickNoteLine = QuickNoteShortcut.describe(wanted, status: status)
    }

    /// Saves the recorded shortcut (nil turns it off) and registers it at once.
    func setQuickNoteShortcut(_ shortcut: Shortcut?) {
        ShortcutStore().save(shortcut)
        applyQuickNoteShortcut()
    }

    /// While the recorder listens, both global shortcuts are released, so pressing either one reaches the
    /// recorder (and push-to-talk does not start dictation instead of showing the refusal).
    func pauseShortcuts() {
        GlobalHotKey.quickNote.unregister()
        GlobalHotKey.shared.unregister()
        quickNoteActive = nil
    }

    /// The recorder is done (a shortcut was saved, or it was cancelled): push-to-talk and the quick-note shortcut are registered again.
    func resumeShortcuts() {
        hotKeyLine = GlobalHotKey.describe(GlobalHotKey.shared.register())
        applyQuickNoteShortcut()
    }

    func openQuickNote() {
        QuickNotePanelController.shared.show(model: self)
    }

    func closeQuickNote() {
        QuickNotePanelController.shared.hide()
    }

    /// The shortcut: open the panel, or close it when it is already open.
    func toggleQuickNote() {
        if QuickNotePanelController.shared.isVisible { closeQuickNote() } else { openQuickNote() }
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
        NSApp.activate(ignoringOtherApps: true)
    }

    /// Opens the new-task sheet (⌘N, the toolbar, the menu bar).
    func openNewTask() {
        showMainWindow()
        newTask.prepare(products: snapshot?.products ?? [], selected: selectedProduct)
        newTask.presented = true
    }

    /// Brings a question's card forward (a clicked notification).
    func focus(askID: String) {
        showMainWindow()
        focusedAskID = askID
        Task {
            try? await Task.sleep(for: .seconds(3))
            if focusedAskID == askID { focusedAskID = nil }
        }
    }

    // MARK: Push-to-talk shortcut (⌥⌘Space)

    /// Key down: open the new-task sheet and start listening (or stop, if it was listening).
    func hotKeyDown() {
        if !newTask.presented { openNewTask() } else { showMainWindow() }
        let listening = Dictation.shared.activeTarget == NewTaskModel.dictationTarget
        switch hotKeyTalk.press(at: Date(), listening: listening) {
        case .start: startNewTaskDictation()
        case .stop: Dictation.shared.stop()
        case .none: break
        }
    }

    /// Key up: a held key stops listening; a tap keeps listening until the next press.
    func hotKeyUp() {
        if hotKeyTalk.release(at: Date()) == .stop { Dictation.shared.stop() }
    }

    func startNewTaskDictation() {
        let task = newTask
        Dictation.shared.start(target: NewTaskModel.dictationTarget, current: task.draft, read: { task.draft }) { task.draft = $0 }
    }

    private func isBusy(_ ask: Ask) -> Bool { isBusy(id: ask.id) }

    private func isBusy(id: String) -> Bool {
        if case .sending = cards[id] { return true }
        return false
    }

    private func finish(_ ask: Ask, message: String) { finish(id: ask.id, message: message) }

    /// Show the confirmation line for a moment, then remove the card.
    private func finish(id: String, message: String) {
        cards[id] = .done(message)
        Task {
            try? await Task.sleep(for: .seconds(3))
            withAnimation(.easeOut(duration: 0.25)) {
                hidden.insert(id)
                cards[id] = nil
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
        content.userInfo = ["ask": ask.id]
        let request = UNNotificationRequest(identifier: "ask-\(ask.id)", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request) { [log] error in
            if let error { log.error("notification failed: \(error.localizedDescription, privacy: .public)") }
        }
    }
}
