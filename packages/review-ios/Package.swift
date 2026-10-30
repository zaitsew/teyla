// swift-tools-version:5.9
import PackageDescription
import Foundation

// TEYLA_REVIEW compiles the overlay, the anchors' bounds probe, the screenshot and the shake
// shortcut. Without it the public API is still there, and every call does nothing, so a product
// can call it unconditionally. The flag is on unless the environment says TEYLA_REVIEW=0.
// The overlay also refuses to open in an App Store build (BuildChannel), whatever the flag says.
let review: [SwiftSetting] =
    ProcessInfo.processInfo.environment["TEYLA_REVIEW"] == "0" ? [] : [.define("TEYLA_REVIEW")]

let package = Package(
    name: "TeylaReview",
    platforms: [.iOS(.v17), .macOS(.v14)],   // macOS only so `swift test` runs on the Mac without a simulator
    products: [
        .library(name: "TeylaReview", targets: ["TeylaReview"]),
    ],
    targets: [
        .target(name: "TeylaReview", swiftSettings: review),
        .testTarget(name: "TeylaReviewTests", dependencies: ["TeylaReview"], swiftSettings: review),
    ]
)
