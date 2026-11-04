package teyla.review

/**
 * Every word review mode says. The English is the web package's wording with "page" and "browser" turned
 * into "screen" and "device". A product replaces any of them: `ReviewStrings(send = "Enviar")`.
 */
class ReviewStrings(
    val button: String = "Review",
    val modeTitle: String = "Review mode",
    val modeHint: String = "The screen is paused. Tap a spot or drag over an area.",
    val dpadHint: String = "The screen is paused. Use the arrow keys to move the cross, then press OK.",
    val commentTitle: String = "What is wrong here?",
    val spotChosen: String = "Spot chosen. Choose again to change it.",
    val areaChosen: String = "Area chosen. Drag again to change it.",
    val wholeScreen: String = "About the whole screen",
    val next: String = "Next",
    val exit: String = "Exit",
    val back: String = "Back",
    val placeholder: String = "Write what is wrong",
    val send: String = "Send",
    val retry: String = "Retry",
    val saving: String = "Saving",
    val saveFailed: String = "Could not save the capture on this device. Your comment and the screenshot are still here. Free some space, then tap Retry.",
    val pictureFailed: String = "Could not take a picture of this screen. Nothing was sent.",
    val secureScreen: String = "This screen is protected from screenshots by the app, so review mode cannot take a picture of it. Nothing was sent.",
    val blankNote: String = "A map, video or 3D area can come out blank in this picture. If that is the problem, say so in your comment.",
    val sentTitle: String = "Sent. Thank you!",
    val sentDetail: String = "Your comment and the screenshot are on their way.",
    val savedTitle: String = "Saved on this device",
    val savedDetail: String = "It has not been sent yet. It will be sent again when the review server can be reached.",
    val done: String = "Done",
    val noticeTitle: String = "Before you send",
    val noticeCaptured: String = "What is sent: a picture of this screen exactly as it looks now, your comment, the name and build of this app, the device and system, and the element you pointed at. The picture shows everything on the screen, including other people's names or data when they are visible.",
    val noticeRecipient: String = "Who gets it: the developer of this app, through a review server. Nobody else.",
    val noticeWhy: String = "Why: to find and fix what you pointed at.",
    val noticeRetention: String = "How long: the copy on the server is gone within the hour. The developer's Mac keeps its copy for 30 days after the report is closed, or 90 days if it is never opened.",
    val noticeOK: String = "OK, send",
    val noticeCancel: String = "Cancel",
    val previewCaption: String = "This picture is what is sent. Black boxes hide private areas.",
    val healthConsent: String = "This screen may show my health data. I agree to send it for review.",
)
