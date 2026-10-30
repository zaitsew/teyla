// ScreenshotTour.swift: the XCUITest that `teyla ux shots` drives. Generic; copy it into the
// product's UI-test target by hand and put that target in the scheme named under [ux.tour] in
// teyla.toml. docs/MATRIX.md has the whole contract.
//
// What it does, for every language x look x screen in the plan:
//   1. launches the app with launch arguments that pick the route, state, date, seed, language,
//      appearance and text size;
//   2. waits for the element with accessibility identifier "tour-ready" (the app sets it once the
//      route and state are on screen);
//   3. attaches a screenshot, an "elements" file (frames, labels and types of the accessibility
//      tree, in points) and an "audit" file (performAccessibilityAudit issues), all named
//      "<variant>__<route>.<state>[.elements|.audit]" so `teyla ux shots` can pair them.
//
// The plan is JSON in the environment variable TEYLA_TOUR_PLAN. `teyla ux shots` sets it as
// TEST_RUNNER_TEYLA_TOUR_PLAN; xcodebuild strips the prefix. It is generated from design/tour.yaml:
//   {"fixed_date": "...", "seed": 7, "network_stub": true, "languages": ["en"],
//    "looks": [{"name": "light", "style": "light", "content_size": "UICTContentSizeCategoryL"}],
//    "screens": [{"id": "today.loaded", "route": "today", "path": "/today", "state": "loaded"}]}
//
// The class is @MainActor: XCUIApplication is main-actor isolated and a Swift 6 target with strict
// concurrency refuses the snapshot and audit calls from a nonisolated test otherwise.
//
// Not compiled by Teyla's own checks: it needs Xcode 16 or later and an iOS 17 deployment target
// for the audit.

import XCTest

@MainActor
final class ScreenshotTour: XCTestCase {
    struct Plan: Decodable {
        struct Look: Decodable { let name: String; let style: String; let content_size: String }
        struct Screen: Decodable { let id: String; let route: String; let path: String; let state: String }
        let fixed_date: String
        let seed: Int
        let network_stub: Bool
        let languages: [String]
        let looks: [Look]
        let screens: [Screen]
    }

    override func setUpWithError() throws {
        continueAfterFailure = true
    }

    func testTour() throws {
        let plan = try loadPlan()
        for language in plan.languages {
            for look in plan.looks {
                let variant = "\(language)-\(look.name)"
                for screen in plan.screens {
                    XCTContext.runActivity(named: "\(variant) \(screen.id)") { _ in
                        capture(plan: plan, language: language, look: look, variant: variant, screen: screen)
                    }
                }
            }
        }
    }

    // MARK: - One screen

    private func capture(plan: Plan, language: String, look: Plan.Look, variant: String, screen: Plan.Screen) {
        let app = XCUIApplication()
        app.launchArguments = [
            // The app's side of the contract (docs/MATRIX.md): route, state, date, seed, network.
            "-tour-route", screen.path,
            "-tour-state", screen.state,
            "-tour-date", plan.fixed_date,
            "-tour-seed", String(plan.seed),
            "-tour-stub-network", plan.network_stub ? "1" : "0",
            // The system's side: language, appearance, text size.
            "-AppleLanguages", "(\(language))",
            "-AppleLocale", language.replacingOccurrences(of: "-", with: "_"),
            "-AppleInterfaceStyle", look.style == "dark" ? "Dark" : "Light",
            "-UIPreferredContentSizeCategoryName", look.content_size,
        ]
        app.launch()
        defer { app.terminate() }

        let ready = app.descendants(matching: .any)["tour-ready"]
        if !ready.waitForExistence(timeout: 15) {
            XCTFail("\(variant) \(screen.id): the app never showed the element with identifier tour-ready")
        }

        let name = "\(variant)__\(screen.id)"
        attach(data: XCUIScreen.main.screenshot().pngRepresentation, type: "public.png", name: name)
        attachJSON(elementsDocument(app), name: name + ".elements")
        attachJSON(auditDocument(app), name: name + ".audit")
    }

    // MARK: - Plan and attachments

    private func loadPlan() throws -> Plan {
        let env = ProcessInfo.processInfo.environment
        guard let text = env["TEYLA_TOUR_PLAN"], let data = text.data(using: .utf8) else {
            throw NSError(domain: "ScreenshotTour", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "TEYLA_TOUR_PLAN is not set; run this through `teyla ux shots`"])
        }
        return try JSONDecoder().decode(Plan.self, from: data)
    }

    private func attach(data: Data, type: String, name: String) {
        let a = XCTAttachment(data: data, uniformTypeIdentifier: type)
        a.name = name
        a.lifetime = .keepAlways
        add(a)
    }

    private func attachJSON(_ object: [String: Any], name: String) {
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else { return }
        attach(data: data, type: "public.json", name: name)
    }

    // MARK: - Accessibility tree

    /// {"screen": {"width", "height"}, "scale", "elements": [{"type", "label", "id", "x", "y", "w", "h",
    /// "interactive", "container", "in_scroll", "truncated"}]} in points.
    private func elementsDocument(_ app: XCUIApplication) -> [String: Any] {
        var out: [[String: Any]] = []
        var size = app.frame.size
        if let snapshot = try? app.snapshot() {
            size = snapshot.frame.size
            walk(snapshot, inScroll: false, into: &out)
        }
        return [
            "screen": ["width": size.width, "height": size.height],
            "scale": UIScreen.main.scale,
            "elements": out,
        ]
    }

    private func walk(_ s: XCUIElementSnapshot, inScroll: Bool, into out: inout [[String: Any]]) {
        let type = typeName(s.elementType)
        let scrolling = inScroll || ["scrollview", "table", "collectionview", "webview"].contains(type)
        let f = s.frame
        if f.width > 0, f.height > 0, type != "statusbar", type != "keyboard" {
            let label = s.label
            out.append([
                "type": type,
                "label": label,
                "id": s.identifier,
                "x": f.origin.x, "y": f.origin.y, "w": f.size.width, "h": f.size.height,
                "interactive": s.isEnabled && interactiveTypes.contains(type),
                "container": containerTypes.contains(type),
                "in_scroll": scrolling,
                // XCUITest does not say a label was cut. An ellipsis in the label is the one sign it
                // can see; the audit's text-clipped check catches the rest.
                "truncated": label.hasSuffix("\u{2026}") || label.hasSuffix("..."),
            ])
        }
        for child in s.children { walk(child, inScroll: scrolling, into: &out) }
    }

    private let interactiveTypes: Set<String> = [
        "button", "link", "switch", "toggle", "slider", "stepper", "textfield", "securetextfield", "searchfield",
        "segmentedcontrol", "tab", "checkbox", "radiobutton", "picker", "datepicker", "menuitem", "menubutton",
    ]
    private let containerTypes: Set<String> = [
        "other", "window", "application", "scrollview", "table", "collectionview", "cell", "navigationbar", "tabbar",
        "toolbar", "statusbar", "keyboard", "alert", "sheet", "popover", "group", "webview", "layoutitem", "map",
    ]

    private func typeName(_ t: XCUIElement.ElementType) -> String {
        switch t {
        case .application: return "application"
        case .window: return "window"
        case .button: return "button"
        case .staticText: return "statictext"
        case .textField: return "textfield"
        case .secureTextField: return "securetextfield"
        case .searchField: return "searchfield"
        case .textView: return "textview"
        case .switch: return "switch"
        case .toggle: return "toggle"
        case .slider: return "slider"
        case .stepper: return "stepper"
        case .image: return "image"
        case .icon: return "icon"
        case .link: return "link"
        case .tab: return "tab"
        case .tabBar: return "tabbar"
        case .tabGroup: return "group"
        case .segmentedControl: return "segmentedcontrol"
        case .picker, .pickerWheel: return "picker"
        case .datePicker: return "datepicker"
        case .cell: return "cell"
        case .table: return "table"
        case .collectionView: return "collectionview"
        case .scrollView: return "scrollview"
        case .webView: return "webview"
        case .navigationBar: return "navigationbar"
        case .toolbar: return "toolbar"
        case .statusBar: return "statusbar"
        case .keyboard, .key: return "keyboard"
        case .alert: return "alert"
        case .sheet: return "sheet"
        case .popover: return "popover"
        case .menuItem: return "menuitem"
        case .map: return "map"
        case .group: return "group"
        default: return "other"
        }
    }

    // MARK: - Accessibility audit

    /// {"ran": Bool, "issues": [{"type": Int, "description": String, "element": String}], "error": String?}.
    /// Every issue is collected and handled, so the tour goes on and the report holds all of them.
    private func auditDocument(_ app: XCUIApplication) -> [String: Any] {
        guard #available(iOS 17.0, *) else {
            return ["ran": false, "issues": [], "error": "performAccessibilityAudit needs iOS 17"]
        }
        var issues: [[String: Any]] = []
        do {
            try app.performAccessibilityAudit(for: .all) { issue in
                issues.append([
                    "type": Int(issue.auditType.rawValue),
                    "description": issue.compactDescription,
                    "element": issue.element?.label ?? "",
                ])
                return true
            }
            return ["ran": true, "issues": issues, "error": NSNull()]
        } catch {
            return ["ran": true, "issues": issues, "error": String(describing: error)]
        }
    }
}
