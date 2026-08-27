import Foundation

/// Maps NSTextView UTF-16 indices to Python `len(str)` / Unicode scalar offsets
/// used by `POST .../boundary` `left_char_count`.
enum SegmentBoundaryOffset {
    static func unicodeOffset(utf16Index: Int, in text: String) -> Int {
        let ns = text as NSString
        guard ns.length > 0 else { return 0 }
        var index = min(max(0, utf16Index), ns.length)
        if index > 0, index < ns.length {
            let unit = ns.character(at: index)
            if UTF16.isTrailSurrogate(unit) {
                index -= 1
            }
        }
        return (ns.substring(to: index) as String).unicodeScalars.count
    }

    static func utf16Index(forUnicodeOffset offset: Int, in text: String) -> Int {
        if offset <= 0 { return 0 }
        var remaining = offset
        var utf16 = 0
        for scalar in text.unicodeScalars {
            if remaining <= 0 { break }
            utf16 += String(scalar).utf16.count
            remaining -= 1
        }
        return utf16
    }

    static func split(_ text: String, unicodeOffset: Int) -> (String, String) {
        let total = text.unicodeScalars.count
        let clamped = min(max(0, unicodeOffset), total)
        let left = String(String.UnicodeScalarView(text.unicodeScalars.prefix(clamped)))
        let right = String(String.UnicodeScalarView(text.unicodeScalars.dropFirst(clamped)))
        return (left, right)
    }
}
