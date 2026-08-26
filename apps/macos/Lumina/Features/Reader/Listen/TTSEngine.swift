import AVFoundation
import Foundation

struct ListenSpeakRequest: Equatable {
    var texts: [String]
    var language: String
    var rate: Float
    var bookId: String
    var idx: Int
    var mode: ListenMode
}

@MainActor
protocol ListenEngine: AnyObject {
    var isPaused: Bool { get }
    func speak(_ request: ListenSpeakRequest) async throws
    func pause()
    func resume()
    func stop()
}

@MainActor
final class SystemNeuralEngine: NSObject, ListenEngine, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private var continuation: CheckedContinuation<Void, Error>?
    private var stopped = false
    private var generation = 0
    private(set) var isPaused = false

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func speak(_ request: ListenSpeakRequest) async throws {
        stop()
        generation += 1
        let token = generation
        stopped = false
        isPaused = false
        let voice = Self.preferredVoice(
            language: request.language,
            identifier: ListenPreferences.systemVoiceIdentifier
        )
        if request.texts.isEmpty { return }
        for text in request.texts {
            try Task.checkCancellation()
            if stopped || token != generation { throw CancellationError() }
            try await speakOne(text, voice: voice, rate: request.rate, token: token)
        }
    }

    private func speakOne(_ text: String, voice: AVSpeechSynthesisVoice?, rate: Float, token: Int) async throws {
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            continuation = cont
            let utterance = TaggedUtterance(string: text, token: token)
            utterance.voice = voice
            utterance.rate = Self.speechRate(rate)
            utterance.preUtteranceDelay = 0.08
            utterance.postUtteranceDelay = 0.12
            synthesizer.speak(utterance)
        }
    }

    func pause() {
        guard synthesizer.isSpeaking else { return }
        synthesizer.pauseSpeaking(at: .word)
        isPaused = true
    }

    func resume() {
        guard synthesizer.isPaused else { return }
        synthesizer.continueSpeaking()
        isPaused = false
    }

    func stop() {
        generation += 1
        stopped = true
        synthesizer.stopSpeaking(at: .immediate)
        isPaused = false
        finish(.failure(CancellationError()))
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        let token = (utterance as? TaggedUtterance)?.token
        Task { @MainActor in
            guard let token, token == generation, !stopped else { return }
            finish(.success(()))
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        // stop() already finishes the continuation.
    }

    private func finish(_ result: Result<Void, Error>) {
        guard let continuation else { return }
        self.continuation = nil
        switch result {
        case .success:
            continuation.resume()
        case .failure(let error):
            continuation.resume(throwing: error)
        }
    }

    static func speechRate(_ multiplier: Float) -> Float {
        let base = AVSpeechUtteranceDefaultSpeechRate
        return min(AVSpeechUtteranceMaximumSpeechRate, max(AVSpeechUtteranceMinimumSpeechRate, base * multiplier))
    }

    static func preferredVoice(language: String, identifier: String?) -> AVSpeechSynthesisVoice? {
        if let identifier, let voice = AVSpeechSynthesisVoice(identifier: identifier) {
            return voice
        }
        let prefix = language == "en" ? "en" : "zh"
        let fallback = language == "en" ? "en-US" : "zh-CN"
        let voices = AVSpeechSynthesisVoice.speechVoices().filter { $0.language.lowercased().hasPrefix(prefix) }
        if let premium = voices.first(where: { $0.quality == .premium }) {
            return premium
        }
        if let enhanced = voices.first(where: { $0.quality == .enhanced }) {
            return enhanced
        }
        return voices.first ?? AVSpeechSynthesisVoice(language: fallback)
    }

    static func qualityLabel(for voice: AVSpeechSynthesisVoice) -> String {
        switch voice.quality {
        case .premium: return "高级"
        case .enhanced: return "增强"
        default: return "标准"
        }
    }

    static func hasDownloadedHighQualityVoice() -> Bool {
        AVSpeechSynthesisVoice.speechVoices().contains { voice in
            let lang = voice.language.lowercased()
            guard lang.hasPrefix("zh") || lang.hasPrefix("en") else { return false }
            return voice.quality == .premium || voice.quality == .enhanced
        }
    }
}

private final class TaggedUtterance: AVSpeechUtterance {
    let token: Int
    init(string: String, token: Int) {
        self.token = token
        super.init(string: string)
    }

    required init?(coder: NSCoder) {
        token = 0
        super.init(coder: coder)
    }
}
