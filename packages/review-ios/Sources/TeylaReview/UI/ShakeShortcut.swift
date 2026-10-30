#if TEYLA_REVIEW && canImport(UIKit)
import CoreMotion
import UIKit

/// Shake to open review mode, read from the accelerometer, which needs no permission and no
/// first-responder trick. It is a shortcut: the explicit button is always the way in.
final class ShakeShortcut {
    static let shared = ShakeShortcut()

    private let motion = CMMotionManager()
    private var lastFired = Date.distantPast
    private var observing = false

    func set(enabled: Bool) {
        guard enabled else {
            motion.stopAccelerometerUpdates()
            return
        }
        guard motion.isAccelerometerAvailable, !motion.isAccelerometerActive else { return }
        motion.accelerometerUpdateInterval = 0.1
        motion.startAccelerometerUpdates(to: .main) { [weak self] data, _ in
            guard let self, let a = data?.acceleration else { return }
            let magnitude = (a.x * a.x + a.y * a.y + a.z * a.z).squareRoot()
            guard magnitude > 2.6, Date().timeIntervalSince(self.lastFired) > 2 else { return }
            self.lastFired = Date()
            MainActor.assumeIsolated { TeylaReview.present() }     // the handler runs on the main queue
        }
    }
}

/// Copies captures that did not reach the relay when the app comes to the foreground.
enum ReviewLifecycle {
    private static var installed = false

    static func installOnce() {
        guard !installed else { return }
        installed = true
        NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { _ in
            guard TeylaReview.isActive else { return }
            DispatchQueue.global(qos: .utility).async { ReviewDelivery.retryPending() }
        }
    }
}
#endif
