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

    public init() {}
}
