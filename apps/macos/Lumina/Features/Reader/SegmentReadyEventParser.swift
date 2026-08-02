import Foundation

/// Parses `segment_ready` SSE payloads into `summary_json` for Reader UI.
enum SegmentReadyEventParser {
    static func eventIndex(from event: [String: Any]) -> Int? {
        if let idx = event["idx"] as? Int {
            return idx
        }
        if let num = event["idx"] as? NSNumber {
            return num.intValue
        }
        return nil
    }

    static func extractSummaryJSON(from event: [String: Any]) -> String? {
        if let json = stringValue(from: event["summary_json"]), !json.isEmpty {
            return json
        }
        if let dict = event["summary_json"] as? [String: Any],
           let json = serializeJSONObject(dict), !json.isEmpty {
            return json
        }
        return assembleFromFlatFields(event)
    }

    private static func stringValue(from value: Any?) -> String? {
        if let text = value as? String {
            return text
        }
        if let text = value as? NSString {
            return text as String
        }
        return nil
    }

    private static func assembleFromFlatFields(_ event: [String: Any]) -> String? {
        guard event["sentences"] != nil || event["bullets"] != nil else {
            return nil
        }

        var obj: [String: Any] = [:]
        if let sentences = event["sentences"] {
            obj["sentences"] = sentences
        }
        if let bullets = event["bullets"] {
            obj["bullets"] = bullets
        }
        if let notes = event["notes"] {
            obj["notes"] = notes
        } else {
            obj["notes"] = []
        }
        if let followUps = event["follow_ups"] {
            obj["follow_ups"] = followUps
        } else {
            obj["follow_ups"] = []
        }
        if let label = stringValue(from: event["label"]), !label.isEmpty {
            obj["label"] = label
        }
        if let anchor = stringValue(from: event["anchor"] ?? event["anchor_label"]), !anchor.isEmpty {
            obj["anchor"] = anchor
        }
        return serializeJSONObject(obj)
    }

    private static func serializeJSONObject(_ object: [String: Any]) -> String? {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object),
              let json = String(data: data, encoding: .utf8)
        else {
            return nil
        }
        return json
    }

    static func formatBulletsPreview(_ json: String?) -> String? {
        let bullets = parseBullets(json)
        guard !bullets.isEmpty else { return nil }
        return bullets.joined(separator: " · ")
    }

    static func parseBullets(_ json: String?) -> [String] {
        guard let json, let data = json.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let bullets = obj["bullets"] as? [Any]
        else { return [] }
        return bullets.compactMap { item in
            if let text = item as? String, !text.isEmpty {
                return text
            }
            if let dict = item as? [String: Any] {
                let label = (dict["label"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
                let body = (dict["body"] as? String ?? dict["content"] as? String)?
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                if let body, !body.isEmpty {
                    if let label, !label.isEmpty {
                        return "\(label)：\(body)"
                    }
                    return body
                }
            }
            return nil
        }
    }
}
