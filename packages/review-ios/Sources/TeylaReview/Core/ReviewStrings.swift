/// Every word review mode says. English by default; a product in other languages fills these from
/// its own catalog: `TeylaReview.configure { $0.strings = { var s = ReviewStrings(); s.next = …; return s } }`.
public struct ReviewStrings {
    public var modeTitle = "Review mode"
    public var modeHint = "The app is paused. Tap a spot or circle an area."
    public var commentTitle = "What is wrong here?"
    public var spotChosen = "Spot chosen. Tap elsewhere to change it."
    public var areaChosen = "Area chosen. Draw again to change it."
    public var wholeScreen = "About the whole screen"
    public var next = "Next"
    public var exit = "Exit"
    public var back = "Back"
    public var placeholder = "Write what is wrong"
    public var dictate = "Dictate"
    public var listening = "Listening. Tap the microphone to stop."
    public var microphoneUnavailable = "The microphone is not available. Please type instead."
    public var send = "Send"
    public var retry = "Retry"
    public var saving = "Saving"
    public var saveFailed = "Could not save the capture on this device. Your comment and the screenshot are still here. Free some space, then tap Retry."
    public var sentTitle = "Sent. Thank you!"
    public var sentDetail = "Your comment and the screenshot are on their way."
    public var savedTitle = "Saved on this phone"
    public var savedDetail = "It has not been sent: this phone is not connected to the review inbox yet."
    public var done = "Done"
    /// Shown under the comment field when the capture leaves the device through the product's
    /// channel: who receives the comment and the screenshot. Empty shows nothing.
    public var deliveryNote = ""

    // The first-send notice (shown once per install, before the first capture leaves the phone).
    public var noticeTitle = "Before you send"
    public var noticeCaptured = "What is sent: a picture of this screen exactly as it looks now, your comment, the name and build of this app, the kind of device and system, and the element you pointed at. The picture shows everything on the screen, including other people's names or data when they are visible."
    public var noticeRecipient = "Who gets it: the developer of this app, through a review server. Nobody else."
    public var noticeWhy = "Why: to find and fix what you pointed at."
    public var noticeRetention = "How long: the copy on the server is gone within the hour. The developer's Mac keeps its copy for 30 days after the report is closed, or 90 days if it is never opened."
    public var noticeOK = "OK, send"
    public var noticeCancel = "Cancel"
    /// Shown above Send: the picture below is the one that is sent, with private areas painted over.
    public var previewCaption = "This picture is what is sent. Black boxes hide private areas."
    /// The checkbox shown before Send when `requiresHealthConsent` is on.
    public var healthConsent = "This screen may show my health data. I agree to send it for review."

    /// The notice as one text, in the order a reader needs it.
    var noticeMessage: String {
        [noticeCaptured, noticeRecipient, noticeWhy, noticeRetention].joined(separator: "\n\n")
    }

    public init() {}
}
