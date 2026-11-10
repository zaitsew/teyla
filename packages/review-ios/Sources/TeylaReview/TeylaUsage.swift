import Foundation
import SwiftUI

/// Usage capture for test builds: which screens and actions are used, how long a job takes, where people
/// get stuck. It runs only where `TeylaReview.isActive` is true (debug and TestFlight); in an App Store
/// build every call returns at once and nothing is stored. No content, no titles, no free text: only ids
/// the app declared in `configure`, so anything else is dropped. See docs/REVIEW.md, "Usage capture".
public enum TeylaUsage {
    public enum Result: String, Sendable { case done, cancelled, error, undone }
    public enum TaskPhase: String, Sendable { case start, success, cancel }

    /// Declare, once at launch, everything that may be recorded. An id not on these lists is dropped.
    /// Screens are routes ("trip.timeline"), actions are accessibility identifiers ("trip.addButton"; a
    /// dynamic suffix such as "trip.row.<uuid>" is stripped before the check), tasks are named jobs ("plan.day").
    public static func configure(screens: [String], actions: [String], tasks: [String]) {
        #if TEYLA_REVIEW
        guard let engine else { return }
        engine.recorder.configure(screens: screens, actions: actions, tasks: tasks)
        UsageLifecycle.installOnce()
        #endif
    }

    /// A screen came into view. Leaving it within 2 seconds records a dead end.
    public static func screen(_ route: String) {
        #if TEYLA_REVIEW
        engine?.recorder.screen(route)
        #endif
    }

    /// A sheet was dismissed. `changed` is false when the user left it without changing anything.
    public static func sheetDismissed(_ route: String, changed: Bool) {
        #if TEYLA_REVIEW
        engine?.recorder.sheetDismissed(route, changed: changed)
        #endif
    }

    /// An action ended: done, cancelled, error or undone.
    public static func action(_ id: String, result: Result) {
        #if TEYLA_REVIEW
        engine?.recorder.action(id, result: UsageActionResult(rawValue: result.rawValue) ?? .done)
        #endif
    }

    /// A tap on an element. Three within a second on one element records a repeat tap.
    public static func tap(_ id: String) {
        #if TEYLA_REVIEW
        engine?.recorder.tap(id)
        #endif
    }

    /// A named job started, succeeded or was cancelled. The time between start and the end is recorded.
    public static func task(_ name: String, _ phase: TaskPhase) {
        #if TEYLA_REVIEW
        engine?.recorder.task(name, UsageTaskPhase(rawValue: phase.rawValue) ?? .start)
        #endif
    }

    /// The variant of an open design decision that is switched on, for example from a Lab switch:
    /// `setVariant(decision: "nav", variant: "bottom-bar")`. Every later event carries it.
    public static func setVariant(decision: String, variant: String) {
        #if TEYLA_REVIEW
        engine?.recorder.setVariant(decision: decision, variant: variant)
        #endif
    }

    public static func clearVariant(decision: String) {
        #if TEYLA_REVIEW
        engine?.recorder.clearVariant(decision: decision)
        #endif
    }

    // MARK: consent

    /// True when this tester has not answered the notice yet and events could leave the device. The owner's
    /// device (paired with the owner's Mac) is never asked.
    public static var consentNeeded: Bool {
        #if TEYLA_REVIEW
        guard let engine else { return false }
        return engine.sender.transportAvailable
            && UsageConsent.noticeNeeded(isOwnerDevice: TeylaReview.isPaired, state: UsageConsent.state())
        #else
        return false
        #endif
    }

    /// The tester pressed Allow.
    public static func allow() {
        #if TEYLA_REVIEW
        guard let engine else { return }
        UsageConsent.set(.allowed)
        Task.detached(priority: .utility) { await engine.sender.sendPending() }
        #endif
    }

    /// The tester pressed Not now: what was recorded is deleted and nothing more is recorded or sent.
    public static func decline() {
        #if TEYLA_REVIEW
        guard let engine else { return }
        UsageConsent.set(.declined)
        engine.store.purge()
        #endif
    }

    /// Sends what is waiting, if the consent rule allows it. The package also calls it when the app goes to the background.
    public static func send() async {
        #if TEYLA_REVIEW
        await engine?.sender.sendPending()
        #endif
    }

    // MARK: the engine

    #if TEYLA_REVIEW
    final class Engine {
        let store: UsageStore
        let recorder: UsageRecorder
        let sender: UsageSender

        init() {
            let st = UsageStore(url: UsageStore.defaultURL())
            store = st
            let build: () -> String = { (Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String) ?? "0" }
            let rec = UsageRecorder(
                store: st,
                isActive: { TeylaReview.isActive },
                mayRecord: { UsageConsent.mayRecord(state: UsageConsent.state()) },
                build: build)
            recorder = rec
            sender = UsageSender(
                store: st,
                isActive: { TeylaReview.isActive },
                isOwnerDevice: { TeylaReview.isPaired },
                consent: { UsageConsent.state() },
                appInfo: { AppProbe.current() },
                declared: { rec.declared },
                install: { UsageInstall.id() },
                transport: {
                    UsageDelivery.transport(deliverUsage: TeylaReview.configuration.deliverUsage, channel: TeylaReview.bundleChannel)
                })
        }
    }

    private static let shared = Engine()

    /// Nil unless this build may record. The engine, and its file, are not made in an App Store build.
    static var engine: Engine? { TeylaReview.isActive ? shared : nil }
    #endif
}

public extension View {
    /// Records `route` as a screen when this view appears.
    func usageScreen(_ route: String) -> some View {
        #if TEYLA_REVIEW
        return onAppear { TeylaUsage.screen(route) }
        #else
        return self
        #endif
    }

    /// Counts taps on this element, to find a control people press again and again. It adds a gesture
    /// that runs beside the element's own.
    func usageTap(_ id: String) -> some View {
        #if TEYLA_REVIEW
        return simultaneousGesture(TapGesture().onEnded { TeylaUsage.tap(id) })
        #else
        return self
        #endif
    }

    /// Shows the one-time notice (Allow / Not now) to a tester who is not the owner. Put it once on the root view.
    func usageConsentNotice() -> some View {
        #if TEYLA_REVIEW
        return modifier(UsageNoticeModifier())
        #else
        return self
        #endif
    }
}

#if TEYLA_REVIEW
private struct UsageNoticeModifier: ViewModifier {
    @State private var show = false

    func body(content: Content) -> some View {
        let strings = TeylaReview.configuration.strings()
        content
            .onAppear { show = TeylaUsage.consentNeeded }
            .alert(strings.usageNoticeTitle, isPresented: $show) {
                Button(strings.usageAllow) { TeylaUsage.allow() }
                Button(strings.usageNotNow, role: .cancel) { TeylaUsage.decline() }
            } message: {
                Text(strings.usageNoticeMessage)
            }
    }
}
#endif
