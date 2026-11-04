import Foundation

// The failures a Teyla call can end in. Its own file so the iPhone app can compile the console parsers, which
// throw `badOutput`, without the Mac's backend.

enum TeylaError: LocalizedError, Equatable {
    case binaryNotFound
    case fixtureUnreadable(String)
    case failed(code: Int32, message: String)
    case badOutput(String)
    case timedOut
    /// The build or the data source cannot do this (the store build has no `teyla` command to run).
    case unavailable(String)

    var errorDescription: String? {
        switch self {
        case .binaryNotFound:
            return "The teyla command was not found. Install Teyla, or choose the file."
        case .fixtureUnreadable(let path):
            return "Could not read the state fixture at \(path)."
        case .failed(let code, let message):
            let text = message.trimmingCharacters(in: .whitespacesAndNewlines)
            return text.isEmpty ? "teyla exited with status \(code)." : text
        case .badOutput(let why):
            return "teyla printed something the app could not read (\(why))."
        case .timedOut:
            return "teyla did not answer in time."
        case .unavailable(let what):
            return what
        }
    }
}
