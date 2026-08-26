import Foundation

struct TTSSettings: Codable, Equatable {
    var engine: String
    var priority: [String]
    var model: String
    var voice: String
    var speed: Double

    static let `default` = TTSSettings(
        engine: "system",
        priority: ["openai"],
        model: "gpt-4o-mini-tts",
        voice: "nova",
        speed: 1.0
    )

    init(
        engine _: String = "system",
        priority: [String] = ["openai"],
        model: String = "gpt-4o-mini-tts",
        voice: String = "nova",
        speed: Double = 1.0
    ) {
        self.engine = "system"
        self.priority = priority
        self.model = model
        self.voice = voice
        self.speed = min(4.0, max(0.25, speed))
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        engine = "system"
        priority = try c.decodeIfPresent([String].self, forKey: .priority) ?? ["openai"]
        model = try c.decodeIfPresent(String.self, forKey: .model) ?? "gpt-4o-mini-tts"
        voice = try c.decodeIfPresent(String.self, forKey: .voice) ?? "nova"
        speed = try c.decodeIfPresent(Double.self, forKey: .speed) ?? 1.0
    }

    enum CodingKeys: String, CodingKey {
        case engine, priority, model, voice, speed
    }
}

enum ListenPreferences {
    private static var defaults: UserDefaults { .standard }
    private static let rateKey = "lumina.listen.rate"
    private static let voiceKey = "lumina.listen.systemVoiceId"

    static let rates: [Float] = [0.8, 1.0, 1.25, 1.5, 2.0]
    static let maxConsecutiveSkips = 3

    static var rate: Float {
        get {
            let stored = defaults.object(forKey: rateKey) as? Float
            let value = stored ?? 1.0
            return rates.min(by: { abs($0 - value) < abs($1 - value) }) ?? 1.0
        }
        set {
            let snapped = rates.min(by: { abs($0 - newValue) < abs($1 - newValue) }) ?? 1.0
            defaults.set(snapped, forKey: rateKey)
        }
    }

    static var systemVoiceIdentifier: String? {
        get { defaults.string(forKey: voiceKey) }
        set { defaults.set(newValue, forKey: voiceKey) }
    }

    static func syncFromSettings(_ tts: TTSSettings?) {
        guard let tts else { return }
        if tts.speed > 0 {
            rate = Float(tts.speed)
        }
    }
}
