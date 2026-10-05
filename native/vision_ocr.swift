import Foundation
import Vision
import ImageIO

// Input is a server-owned normalized JPEG. No networking or shell commands.
do {
    guard CommandLine.arguments.count == 2 else { throw NSError(domain: "input", code: 1) }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["ja-JP", "en-US"]
    request.usesLanguageCorrection = false
    let supported = try request.supportedRecognitionLanguages()
    guard supported.contains("ja-JP") else { throw NSError(domain: "JapaneseUnsupported", code: 2) }
    let handler = VNImageRequestHandler(url: URL(fileURLWithPath: CommandLine.arguments[1]), options: [:])
    try handler.perform([request])
    let lines: [[String: Any]] = (request.results ?? []).compactMap { observation in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let box = observation.boundingBox
        return ["text": candidate.string, "confidence": candidate.confidence,
                "x": box.minX, "y": 1 - box.maxY, "width": box.width, "height": box.height,
                "slope": -(observation.topRight.y - observation.topLeft.y) / max(0.001, observation.topRight.x - observation.topLeft.x)]
    }
    let output: [String: Any] = ["engine": "Apple Vision", "languages": request.recognitionLanguages, "lines": lines]
    let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
} catch {
    // No private text, paths or exception detail on stderr.
    FileHandle.standardError.write(Data("Local Vision recognition failed\n".utf8))
    exit(1)
}
