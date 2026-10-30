// swift-tools-version:5.9
import PackageDescription
import Foundation

// A package cannot see the app's SWIFT_ACTIVE_COMPILATION_CONDITIONS, so a flag set in the app
// never reached this target. TEYLA_REVIEW here only decides whether the overlay code is compiled
// in at all (the environment variable TEYLA_REVIEW=0 at package resolution strips it).
// Whether review mode RUNS is a runtime switch: the app's Info.plist key TeylaReviewEnabled, filled
// from a build setting that exists only in Debug and TestFlight (TeylaReview.isEnabled). With the
// key absent every call does nothing, and the overlay also refuses to open in an App Store build
// (BuildChannel). See docs/REVIEW.md, "Adopt it".
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
