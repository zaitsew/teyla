#if TEYLA_REVIEW && (canImport(UIKit) || os(macOS))
import Foundation
#if canImport(UIKit)
import UIKit
#else
import AppKit
#endif

/// Session boundaries and the send: the app comes to the front (a session starts), goes to the background
/// (it pauses, and what is waiting is sent), or ends. Idle time in the background is not counted.
enum UsageLifecycle {
    private static var installed = false

    static func installOnce() {
        guard !installed else { return }
        installed = true
        let center = NotificationCenter.default
        #if canImport(UIKit)
        let active = UIApplication.didBecomeActiveNotification
        let resign = UIApplication.willResignActiveNotification
        let terminate = UIApplication.willTerminateNotification
        #else
        let active = NSApplication.didBecomeActiveNotification
        let resign = NSApplication.willResignActiveNotification
        let terminate = NSApplication.willTerminateNotification
        #endif
        center.addObserver(forName: active, object: nil, queue: .main) { _ in
            guard let engine = TeylaUsage.engine else { return }
            engine.recorder.appBecameActive()
            Task.detached(priority: .utility) { await engine.sender.sendPending() }
        }
        center.addObserver(forName: resign, object: nil, queue: .main) { _ in
            guard let engine = TeylaUsage.engine else { return }
            engine.recorder.appWentToBackground()
            Task.detached(priority: .utility) { await engine.sender.sendPending() }
        }
        center.addObserver(forName: terminate, object: nil, queue: .main) { _ in
            TeylaUsage.engine?.recorder.appWillTerminate()
        }
        // The app may already be in front when configure runs; the first notification then does nothing.
        DispatchQueue.main.async {
            #if canImport(UIKit)
            let front = UIApplication.shared.applicationState != .background
            #else
            let front = NSApp?.isActive ?? false
            #endif
            if front { TeylaUsage.engine?.recorder.appBecameActive() }
        }
    }
}
#endif
