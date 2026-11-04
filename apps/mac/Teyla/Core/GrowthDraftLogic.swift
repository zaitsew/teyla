import Foundation

// The words and the arithmetic of the review queue on the Mac's Growth page. Its own file so the iPhone app can compile
// `GrowthLogic.swift` without `GrowthDrafts.swift` and the Mac's command allow-list: the phone shows no draft.

extension GrowthLogic {
    // MARK: Drafts

    /// "Editor 4.2 of 5", or nothing when no editor pass ran.
    static func editorWords(_ draft: GrowthDraft) -> String? {
        draft.editorScore.map { "Editor \(String(format: "%.1f", $0)) of 5" }
    }

    /// The line under a draft's title: its channel and format, and its product when it names one.
    static func draftDetail(_ draft: GrowthDraft) -> String {
        [channelName(platform: draft.platform, language: draft.language), formatName(draft.format), draft.product]
            .filter { !$0.isEmpty }.joined(separator: " · ")
    }

    /// The draft's title: its idea, else the first line of its body.
    static func draftTitle(_ draft: GrowthDraft) -> String {
        let idea = draft.idea.trimmingCharacters(in: .whitespacesAndNewlines)
        if !idea.isEmpty { return idea }
        let first = draft.body.split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
        return first.isEmpty ? "Untitled draft" : first
    }

    /// Why Approve is off, in one line, or nil when it is on.
    static func approveBlock(_ draft: GrowthDraft) -> String? {
        if draft.canApprove { return nil }
        if draft.voiceOK == nil || draft.leakOK == nil { return "The voice and leak checks have not run. Edit the draft and they run again." }
        let why = draft.checkNotes.first.map { " \($0)." } ?? ""
        return "A check failed.\(why) Edit the draft and they run again."
    }

    /// Whether a reason can be sent: not empty, within the limit.
    static func canReject(reason: String) -> Bool {
        let trimmed = reason.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && trimmed.count <= GrowthActions.reasonLimit
    }

    /// Save is on when the text is within limits and the text or the hook changed.
    static func canSave(body: String, original: String, hook: String = "", originalHook: String = "") -> Bool {
        let text = body.trimmingCharacters(in: .whitespacesAndNewlines)
        let newHook = hook.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text.count <= GrowthActions.bodyLimit, newHook.count <= GrowthActions.hookLimit else { return false }
        return text != original.trimmingCharacters(in: .whitespacesAndNewlines) || newHook != originalHook.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
