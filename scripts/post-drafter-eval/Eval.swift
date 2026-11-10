import Foundation
@main struct Eval {
 static func main() async throws {
  let data = FileHandle.standardInput.readDataToEndOfFile()
  let notes = (try? JSONSerialization.jsonObject(with: data)) as? [[String: String]] ?? []
  var out: [[String: String]] = []
  for n in notes {
      let note = PostRules.prepare(n["text"] ?? "")
      let d = await PostDrafter.draft(note: note)
      out.append(["id": n["id"] ?? "", "note": note, "linkedin": d.linkedIn, "x": d.x, "source": d.source.rawValue,
                  "li_findings": PostRules.findings(d.linkedIn, note: note).joined(separator: "; "),
                  "x_findings": PostRules.findings(d.x, note: note, limit: PostRules.xLimit).joined(separator: "; ")])
  }
  let j = try JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted, .sortedKeys])
  FileHandle.standardOutput.write(j)
 }
}
